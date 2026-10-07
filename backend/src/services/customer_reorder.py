"""customer_reorder.py — per-customer reorder-cadence prediction.

Predicts WHEN a customer is likely to place their next order, from real
dated invoice history in sage_ar_snapshot's LEDGER_<code>_<id> rows
(excludes the synthetic AGED_<code> aging-summary rows, which all carry the
same snapshot date and would corrupt gap statistics).

Deliberately does NOT attempt to predict which specific SKU a customer will
reorder next -- verified live against this DB that sage_invoice_lines_snapshot
(the only per-SKU sales table) is 100% undated lifetime aggregates
(invoice_id = 'SOLD_<code>'), so there is no dated line-item history to
build a per-SKU prediction on. Building that here would be fabrication, not
prediction -- the codebase's established convention (see the Report
Generator "insufficient data" fix) is to say so explicitly rather than
invent a plausible-looking number.
"""
from __future__ import annotations

import datetime
import logging
import statistics
from typing import Any, Dict, List, Optional
from typing import Any as DBClient

from ..db import db
from ..cache import ttl_cache
from .sage_adapter.service import _latest_batch_for_table

logger = logging.getLogger("customer_reorder")

_MIN_ORDER_DATES_FOR_PREDICTION = 3  # need >=2 gaps to compute a meaningful average
_HIGH_VARIABILITY_CV = 0.75  # coefficient of variation above this -> "low" confidence
# A customer whose last real order predates this cutoff has very likely
# churned or closed, not merely "overdue" -- extrapolating a short 2019-era
# ordering pattern forward to "predict" a 2026 order date isn't a meaningful
# reorder signal. Found live: without this cutoff, the priority queue's
# "most overdue first" sort surfaced 7-year-dormant accounts ahead of every
# genuinely actionable customer. Scoped to the priority queue only (not
# get_customer_reorder_profile) -- a single customer's own 360 page should
# still show its real historical cadence even if dormant.
_DORMANT_CUTOFF_DAYS = 365   # no order in a year = lapsed, not 'due'


def _order_dates_for_customer(customer_code: str, client: DBClient = db) -> List[Dict[str, Any]]:
    """Real dated invoice rows for one customer. Once ACE Books is live these come
    from v_customer_invoices (every Sage invoice since 2018 + ACE Books invoices),
    otherwise from the latest Sage AR batch."""
    from src.fin.readmodel import live
    if live():
        from src.services import books_analytics
        return books_analytics.customer_order_history(customer_code)
    batch = _latest_batch_for_table("sage_ar_snapshot", client)
    q = (
        client.table("sage_ar_snapshot")
        .select("date,amount")
        .eq("customer_id", customer_code)
        .like("invoice_id", "LEDGER_%")
    )
    if batch:
        q = q.eq("batch_id", batch)
    return q.limit(20000).execute().data or []


def _compute_profile(rows: List[Dict[str, Any]], today: Optional[datetime.date] = None) -> Dict[str, Any]:
    today = today or datetime.date.today()

    dates_amounts: Dict[datetime.date, float] = {}
    for r in rows:
        raw = r.get("date")
        if not raw:
            continue
        try:
            d = datetime.date.fromisoformat(str(raw)[:10])
        except Exception:
            continue
        amt = float(r.get("amount") or 0)
        dates_amounts[d] = dates_amounts.get(d, 0.0) + amt

    order_dates = sorted(dates_amounts.keys())
    order_values = [dates_amounts[d] for d in order_dates]

    base = {
        "order_count": len(order_dates),
        "last_order_date": order_dates[-1].isoformat() if order_dates else None,
        "avg_order_value": round(statistics.mean(order_values), 2) if order_values else None,
        "min_order_value": round(min(order_values), 2) if order_values else None,
        "max_order_value": round(max(order_values), 2) if order_values else None,
        "avg_gap_days": None,
        "predicted_next_order_date": None,
        "days_until_or_since": None,
        "churn_risk": False,
        "confidence": "insufficient_history",
    }

    if len(order_dates) < _MIN_ORDER_DATES_FOR_PREDICTION:
        return base

    gaps = [(order_dates[i] - order_dates[i - 1]).days for i in range(1, len(order_dates))]
    avg_gap = statistics.mean(gaps)
    stdev_gap = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    cv = (stdev_gap / avg_gap) if avg_gap > 0 else 0.0

    predicted = order_dates[-1] + datetime.timedelta(days=round(avg_gap))
    days_until_or_since = (today - predicted).days  # positive = overdue, negative = days until

    base.update({
        "avg_gap_days": round(avg_gap, 1),
        "gap_stddev_days": round(stdev_gap, 1),
        "predicted_next_order_date": predicted.isoformat(),
        "days_until_or_since": days_until_or_since,
        # Overdue by more than the customer's own typical cycle -- a
        # self-relative signal, not an arbitrary global constant.
        "churn_risk": days_until_or_since > avg_gap,
        "confidence": "low" if cv > _HIGH_VARIABILITY_CV else "normal",
    })
    return base


def get_customer_reorder_profile(customer_code: str, client: DBClient = db) -> Dict[str, Any]:
    """Single-customer reorder-cadence profile, additive key for /crm/customers/{id}/360."""
    if not customer_code:
        return _compute_profile([])
    try:
        rows = _order_dates_for_customer(customer_code, client)
    except Exception as e:
        logger.warning(f"get_customer_reorder_profile query failed for {customer_code!r}: {e}")
        rows = []
    return _compute_profile(rows)


@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",), tags=("crm", "reorder_queue"))
def get_reorder_priority_queue(limit: int = 50, client: DBClient = db) -> List[Dict[str, Any]]:
    """Ranked queue across every customer with enough history to predict:
    overdue first (most-overdue-relative-to-own-cycle first), then tiebroken
    by average order value, then not-yet-due customers by soonest first."""
    from src.fin.readmodel import live
    if live():
        from src.services import books_analytics
        rows = books_analytics.customer_order_history()
        return _rank_queue(rows, limit, client)
    batch = _latest_batch_for_table("sage_ar_snapshot", client)
    q = (
        client.table("sage_ar_snapshot")
        .select("customer_id,date,amount")
        .like("invoice_id", "LEDGER_%")
    )
    if batch:
        q = q.eq("batch_id", batch)
    rows = q.limit(50000).execute().data or []
    return _rank_queue(rows, limit, client)


def _rank_queue(rows: List[Dict[str, Any]], limit: int, client: DBClient = db) -> List[Dict[str, Any]]:
    by_customer: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        code = r.get("customer_id")
        if not code:
            continue
        by_customer.setdefault(code, []).append(r)

    today = datetime.date.today()
    profiles = []
    for code, crows in by_customer.items():
        profile = _compute_profile(crows, today=today)
        if profile["confidence"] == "insufficient_history":
            continue
        last_order = profile["last_order_date"]
        if last_order and (today - datetime.date.fromisoformat(last_order)).days > _DORMANT_CUTOFF_DAYS:
            continue
        profile["customer_code"] = code
        profiles.append(profile)

    # Resolve display names + numeric customers.id (needed by the frontend's
    # customer_360(id) lookup when a queue row is selected) in one batch query.
    if profiles:
        codes = [p["customer_code"] for p in profiles]
        try:
            cust_rows = (
                client.table("customers").select("id,customer_code,name").in_("customer_code", codes).execute().data or []
            )
            meta_by_code = {c["customer_code"]: c for c in cust_rows}
            for p in profiles:
                meta = meta_by_code.get(p["customer_code"])
                p["customer_name"] = meta.get("name") if meta else p["customer_code"]
                p["customer_pk"] = meta.get("id") if meta else None
        except Exception as e:
            logger.warning(f"reorder queue customer name enrichment failed (non-fatal): {e}")
            for p in profiles:
                p["customer_name"] = p["customer_code"]
                p["customer_pk"] = None

    # Actionable first: due now (overdue by no more than their own cycle), biggest accounts first;
    # then due within two weeks; lapsing accounts (overdue beyond their own cycle) last. Sorting
    # purely by "most overdue" put customers who stopped buying ~2 years ago at the top.
    for p in profiles:
        d, gap = p["days_until_or_since"], p["avg_gap_days"] or 0
        p["queue_status"] = "lapsing" if d > max(gap, 30) else "due" if d > 0 else "upcoming"
    due = sorted([p for p in profiles if p["queue_status"] == "due"], key=lambda p: (-(p["avg_order_value"] or 0), -p["days_until_or_since"]))
    upcoming = sorted([p for p in profiles if p["queue_status"] == "upcoming" and p["days_until_or_since"] >= -14], key=lambda p: -p["days_until_or_since"])
    lapsing = sorted([p for p in profiles if p["queue_status"] == "lapsing"], key=lambda p: -(p["avg_order_value"] or 0))
    return (due + upcoming + lapsing)[:limit]
