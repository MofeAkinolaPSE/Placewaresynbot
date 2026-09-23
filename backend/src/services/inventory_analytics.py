"""
Inventory analytics — ACE / Placeware
=====================================
Demand velocity, risk tiering, reorder sizing and position reporting for the
inventory workspace. Heuristic decision support, not machine learning, per the
inventory design report in docs/Latestmods-TB/Inventory.

A note on where demand actually comes from, because it constrains everything
here: the Sage sales history (sage_invoice_lines_snapshot, 22k rows) is
aggregated per customer as invoice_id='SOLD_<customer>' with NO transaction
date, and it does not join to the dated AR rows. So it can tell us whether a
SKU has ever sold and in what lifetime volume, but it cannot support a windowed
rate ("units per day over the last 30 days").

The dated source is placeware_inventory_events, which records a SALE row per
dispatched line. That stream only began when dispatch was wired to deduct
stock, so it starts sparse and thickens with use. Rather than fabricate a rate
from undated lifetime totals, SKUs with no dated movement are reported with
confidence="no_recent_demand" and no stockout prediction -- the design report
calls for exactly this rather than a made-up estimate.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

from ..db import db
from .inventory_workspace import _family_key

logger = logging.getLogger(__name__)

DBClient = Any

# Planning parameters (environment-configurable, defaults from the design report)
LEAD_TIME_DAYS = int(os.getenv("INV_LEAD_TIME_DAYS", "14"))
SAFETY_STOCK_DAYS = int(os.getenv("INV_SAFETY_STOCK_DAYS", "7"))
REVIEW_CYCLE_DAYS = int(os.getenv("INV_REVIEW_CYCLE_DAYS", "14"))
EXPIRING_SOON_DAYS = int(os.getenv("INV_EXPIRING_SOON_DAYS", "30"))

# Percentage change between consecutive windows before demand is called a trend
# rather than noise.
TREND_THRESHOLD = 0.15


def _today() -> dt.date:
    return dt.date.today()


def _parse_date(raw: Any) -> Optional[dt.date]:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _days_until(raw: Any) -> Optional[int]:
    d = _parse_date(raw)
    return (d - _today()).days if d else None


# ── Demand velocity ───────────────────────────────────────────────────────────

def get_demand_metrics(
    window_days: int = 30, client: DBClient = db
) -> Dict[str, Dict[str, Any]]:
    """Per-SKU demand from dated SALE events, as {sku: {...}}.

    Fetched in ONE query for the whole catalogue rather than per SKU -- the
    design report records an 18-second scan caused by the per-item pattern.
    Compares the current window against the preceding equal window to derive
    direction.
    """
    today = _today()
    current_start = today - dt.timedelta(days=window_days)
    prior_start = today - dt.timedelta(days=window_days * 2)

    try:
        rows = (
            client.table("placeware_inventory_events")
            .select("sku,quantity_change,created_at")
            .eq("event_type", "SALE")
            .gte("created_at", prior_start.isoformat())
            .limit(20000)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("get_demand_metrics: failed to read SALE events: %s", exc)
        return {}

    current: Dict[str, float] = {}
    prior: Dict[str, float] = {}
    for r in rows:
        sku = r.get("sku")
        if not sku:
            continue
        when = _parse_date(r.get("created_at"))
        if not when:
            continue
        # SALE events are stored as negative deltas; demand is the magnitude.
        qty = abs(float(r.get("quantity_change") or 0))
        if when >= current_start:
            current[sku] = current.get(sku, 0.0) + qty
        elif when >= prior_start:
            prior[sku] = prior.get(sku, 0.0) + qty

    out: Dict[str, Dict[str, Any]] = {}
    for sku in set(current) | set(prior):
        cur_qty = current.get(sku, 0.0)
        prv_qty = prior.get(sku, 0.0)
        avg_daily = cur_qty / window_days if window_days else 0.0

        if cur_qty <= 0 and prv_qty <= 0:
            direction = "no_recent_demand"
        elif prv_qty <= 0:
            direction = "rising" if cur_qty > 0 else "stable"
        else:
            change = (cur_qty - prv_qty) / prv_qty
            direction = (
                "rising" if change > TREND_THRESHOLD
                else "falling" if change < -TREND_THRESHOLD
                else "stable"
            )

        out[sku] = {
            "avg_daily_demand": round(avg_daily, 3),
            "window_qty": cur_qty,
            "prior_window_qty": prv_qty,
            "direction": direction,
            "confidence": "estimated" if cur_qty > 0 else "no_recent_demand",
            "window_days": window_days,
        }
    return out


def assess_sku(
    qty: float,
    reorder_level: Optional[float],
    expiry_date: Any,
    demand: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Risk tier, coverage and reorder sizing for one SKU.

    Tiers follow the design report: coverage below lead time is CRITICAL,
    below lead+safety is WARNING, below lead+safety+review is MONITOR.
    Near-term expiry floors the result to at least WARNING, because stock that
    expires before it can sell is not really 'adequate'.
    """
    avg_daily = float((demand or {}).get("avg_daily_demand") or 0)
    days_to_expiry = _days_until(expiry_date)
    expiring_soon = days_to_expiry is not None and days_to_expiry <= EXPIRING_SOON_DAYS

    coverage_days: Optional[float] = None
    stockout_date: Optional[str] = None

    if qty <= 0:
        tier = "critical"
    elif avg_daily > 0:
        coverage_days = qty / avg_daily
        stockout_date = (_today() + dt.timedelta(days=int(coverage_days))).isoformat()
        if coverage_days < LEAD_TIME_DAYS:
            tier = "critical"
        elif coverage_days < LEAD_TIME_DAYS + SAFETY_STOCK_DAYS:
            tier = "warning"
        elif coverage_days < LEAD_TIME_DAYS + SAFETY_STOCK_DAYS + REVIEW_CYCLE_DAYS:
            tier = "monitor"
        else:
            tier = "adequate"
    else:
        # No dated demand to reason from: fall back to the stock threshold.
        threshold = reorder_level if reorder_level and reorder_level > 0 else 0
        tier = "critical" if threshold and qty <= threshold else "monitor"

    # Expiry overrides the demand-based tier rather than only nudging an
    # 'adequate' one. Without this, stock that expired weeks ago reads as
    # "monitor" purely because nothing has sold recently -- which is exactly
    # backwards: ~N64m of already-expired stock was being under-reported.
    if days_to_expiry is not None and days_to_expiry < 0:
        tier = "critical"
    elif expiring_soon and tier in ("adequate", "monitor"):
        tier = "warning"

    if avg_daily > 0:
        target = avg_daily * (LEAD_TIME_DAYS + SAFETY_STOCK_DAYS)
        recommended = max(0, round(target - qty))
    else:
        threshold = reorder_level if reorder_level and reorder_level > 0 else 10
        recommended = max(0, round(threshold * 2 - qty))

    return {
        "risk_tier": tier,
        "coverage_days": round(coverage_days, 1) if coverage_days is not None else None,
        "predicted_stockout_date": stockout_date,
        "recommended_reorder_qty": recommended,
        "days_to_expiry": days_to_expiry,
        "expiring_soon": expiring_soon,
        "demand_direction": (demand or {}).get("direction", "no_recent_demand"),
        "demand_confidence": (demand or {}).get("confidence", "no_recent_demand"),
        "avg_daily_demand": avg_daily,
    }


# ── Position reporting ────────────────────────────────────────────────────────

def get_expiry_exposure(
    company_id: Optional[str] = None, client: DBClient = db
) -> Dict[str, Any]:
    """Value of stock on hand bucketed by how soon it expires.

    This is the single most actionable number for a vaccine distributor: it
    converts 'these batches expire in October' into 'this much money walks out
    of the door unless it moves'.
    """
    try:
        q = client.table("v_inventory").select(
            "sku,name,current_stock,cost_price,expiry_date,company_id"
        ).gt("current_stock", 0)
        if company_id:
            q = q.eq("company_id", company_id)
        rows = q.limit(5000).execute().data or []
    except Exception as exc:
        logger.error("get_expiry_exposure failed: %s", exc)
        return {}

    buckets = {
        "expired": {"value": 0.0, "units": 0.0, "skus": 0},
        "within_30_days": {"value": 0.0, "units": 0.0, "skus": 0},
        "within_90_days": {"value": 0.0, "units": 0.0, "skus": 0},
        "beyond_90_days": {"value": 0.0, "units": 0.0, "skus": 0},
        "no_expiry_date": {"value": 0.0, "units": 0.0, "skus": 0},
    }
    at_risk: List[Dict[str, Any]] = []

    for r in rows:
        qty = float(r.get("current_stock") or 0)
        value = qty * float(r.get("cost_price") or 0)
        days = _days_until(r.get("expiry_date"))
        if days is None:
            key = "no_expiry_date"
        elif days < 0:
            key = "expired"
        elif days <= 30:
            key = "within_30_days"
        elif days <= 90:
            key = "within_90_days"
        else:
            key = "beyond_90_days"

        buckets[key]["value"] += value
        buckets[key]["units"] += qty
        buckets[key]["skus"] += 1

        if days is not None and days <= 90:
            at_risk.append({
                "sku": r.get("sku"), "name": r.get("name"),
                # family/company let the UI open this SKU's existing detail
                # panel instead of re-deriving the grouping key in TypeScript.
                "family": _family_key(r.get("name") or r.get("sku") or ""),
                "company_id": r.get("company_id"),
                "units": qty, "value": round(value, 2),
                "expiry_date": r.get("expiry_date"), "days_to_expiry": days,
            })

    for b in buckets.values():
        b["value"] = round(b["value"], 2)
    at_risk.sort(key=lambda x: x["days_to_expiry"])
    return {"buckets": buckets, "at_risk": at_risk[:20]}


def get_lifetime_sales(client: DBClient = db) -> Dict[str, float]:
    """Lifetime units sold per SKU from the Sage export.

    Undated by nature (rows are 'SOLD_<customer>' aggregates), so this is only
    safe for 'has this ever sold, and roughly how much' -- never for a rate.
    """
    try:
        rows = (
            client.table("sage_invoice_lines_snapshot")
            .select("item_id,quantity").limit(50000).execute()
        ).data or []
    except Exception as exc:
        logger.error("get_lifetime_sales failed: %s", exc)
        return {}
    totals: Dict[str, float] = {}
    for r in rows:
        item = (r.get("item_id") or "").strip()
        if item:
            totals[item] = totals.get(item, 0.0) + float(r.get("quantity") or 0)
    return totals


def get_dead_stock(
    company_id: Optional[str] = None, limit: int = 20, client: DBClient = db
) -> List[Dict[str, Any]]:
    """Stock on hand that has never sold — capital sitting still."""
    lifetime = get_lifetime_sales(client=client)
    try:
        q = client.table("v_inventory").select(
            "sku,name,current_stock,cost_price,expiry_date,company_id"
        ).gt("current_stock", 0)
        if company_id:
            q = q.eq("company_id", company_id)
        rows = q.limit(5000).execute().data or []
    except Exception as exc:
        logger.error("get_dead_stock failed: %s", exc)
        return []

    dead = []
    for r in rows:
        sku = r.get("sku")
        if lifetime.get(sku, 0) > 0:
            continue
        qty = float(r.get("current_stock") or 0)
        dead.append({
            "sku": sku, "name": r.get("name"), "units": qty,
            "family": _family_key(r.get("name") or sku or ""),
            "company_id": r.get("company_id"),
            "value": round(qty * float(r.get("cost_price") or 0), 2),
            "expiry_date": r.get("expiry_date"),
            "days_to_expiry": _days_until(r.get("expiry_date")),
        })
    dead.sort(key=lambda x: x["value"], reverse=True)
    return dead[:limit]


def get_analytics_overview(
    company_id: Optional[str] = None, client: DBClient = db
) -> Dict[str, Any]:
    """Everything the inventory dashboard needs, in one call."""
    demand = get_demand_metrics(client=client)
    exposure = get_expiry_exposure(company_id=company_id, client=client)
    dead = get_dead_stock(company_id=company_id, client=client)

    try:
        q = client.table("v_inventory").select(
            "sku,name,current_stock,cost_price,reorder_level,expiry_date,company_id"
        ).gt("current_stock", 0)
        if company_id:
            q = q.eq("company_id", company_id)
        rows = q.limit(5000).execute().data or []
    except Exception as exc:
        logger.error("get_analytics_overview failed: %s", exc)
        rows = []

    tiers = {"critical": 0, "warning": 0, "monitor": 0, "adequate": 0}
    total_value = 0.0
    total_units = 0.0
    reorder_candidates: List[Dict[str, Any]] = []
    tracked_skus = 0

    for r in rows:
        qty = float(r.get("current_stock") or 0)
        total_units += qty
        total_value += qty * float(r.get("cost_price") or 0)
        d = demand.get(r.get("sku"))
        if d:
            tracked_skus += 1
        a = assess_sku(qty, r.get("reorder_level"), r.get("expiry_date"), d)
        tiers[a["risk_tier"]] = tiers.get(a["risk_tier"], 0) + 1
        if a["risk_tier"] in ("critical", "warning") and a["recommended_reorder_qty"] > 0:
            reorder_candidates.append({
                "sku": r.get("sku"), "name": r.get("name"),
                "family": _family_key(r.get("name") or r.get("sku") or ""),
                "company_id": r.get("company_id"),
                "current_stock": qty, **a,
            })

    reorder_candidates.sort(
        key=lambda c: (c["coverage_days"] if c["coverage_days"] is not None else 9999)
    )

    # Concentration: how much of the total value sits in the top 5 SKUs.
    values = sorted(
        (float(r.get("current_stock") or 0) * float(r.get("cost_price") or 0) for r in rows),
        reverse=True,
    )
    top5 = sum(values[:5])

    return {
        "totals": {
            "sku_count": len(rows),
            "total_units": round(total_units, 2),
            "total_value": round(total_value, 2),
            "top5_value_share_pct": round(top5 / total_value * 100, 1) if total_value else 0,
        },
        "risk_tiers": tiers,
        "expiry": exposure,
        "dead_stock": dead,
        "reorder_candidates": reorder_candidates[:20],
        "demand": {
            # Stated plainly so the UI never implies a forecast we can't make.
            "skus_with_dated_demand": tracked_skus,
            "window_days": 30,
            "source": "placeware_inventory_events (SALE)",
            "note": (
                "Demand rates are derived from dispatched sales recorded in-app. "
                "Historic Sage sales are aggregated without transaction dates, so "
                "they inform dead-stock detection but cannot produce a daily rate."
            ),
        },
        "planning": {
            "lead_time_days": LEAD_TIME_DAYS,
            "safety_stock_days": SAFETY_STOCK_DAYS,
            "review_cycle_days": REVIEW_CYCLE_DAYS,
            "expiring_soon_days": EXPIRING_SOON_DAYS,
        },
    }
