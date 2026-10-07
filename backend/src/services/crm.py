from __future__ import annotations

from typing import Dict, Any, List
from typing import Any as DBClient
from ..db import db
from ..cache import ttl_cache
from .sage_adapter.service import get_sage_kpi_batch_id


MAX_ANALYTICS_ROWS = 3000


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",), tags=("crm", "crm_risk_scores", "executive"))
def risk_scores(client: DBClient = db) -> Dict[str, Any]:
    """Compute CRM pipeline risk scores, combining pipeline with overdue AR.

    Deterministic formula:
    - overdue_ar_amount per customer from sage_ar_snapshot where due_date < today and balance > 0
    - open_pipeline_amount per customer from crm_pipeline_snapshot where status in ('open','pipeline')
    - risk_score = min(100, base + overdue_factor + pipeline_factor)
        base = 20
        overdue_factor = min(50, overdue_ar_amount / 1000 * 5)
        pipeline_factor = min(30, open_pipeline_amount / 10000 * 10)
    Returns list of customers with scores and components.
    """
    import datetime
    today = datetime.date.today()

    # Overdue AR by customer (balance > 0 skips the zero-value aged-summary rows).
    # Sage exports carry no due_date, so invoice date + 30-day standard terms is
    # used as the fallback when due_date is missing.
    from src.fin.readmodel import live
    books = live()
    sage_batch_id = get_sage_kpi_batch_id()
    ar_q = client.table("sage_ar_snapshot").select("customer_id,due_date,date,balance").gt("balance", 0)
    if sage_batch_id:
        ar_q = ar_q.eq("batch_id", sage_batch_id)
    ar_rows = [] if books else (ar_q.limit(50000).execute().data or [])
    def parse_date(s: str | None):
        if not s:
            return None
        try:
            return datetime.date.fromisoformat(str(s)[:10])
        except Exception:
            return None
    overdue_by_cust: Dict[str, float] = {}
    for r in ar_rows:
        dd = parse_date(r.get("due_date"))
        if dd is None:
            inv = parse_date(r.get("date"))
            dd = (inv + datetime.timedelta(days=30)) if inv else today
        bal = float(r.get("balance") or 0)
        cid = r.get("customer_id") or ""
        if cid and bal > 0 and dd < today:
            overdue_by_cust[cid] = overdue_by_cust.get(cid, 0.0) + bal

    if books:
        # ACE Books open items (overdue invoices, credits netted per customer)
        from src.services import books_analytics
        overdue_by_cust = books_analytics.overdue_by_customer()

    # Open pipeline by customer
    crm = client.table("crm_pipeline_snapshot").select("customer_id,amount,status").order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    crm_rows = crm.data or []
    open_by_cust: Dict[str, float] = {}
    for r in crm_rows:
        status = (r.get("status") or "").lower()
        if status in ("open", "pipeline", "pending"):
            cid = r.get("customer_id") or ""
            if cid:
                open_by_cust[cid] = open_by_cust.get(cid, 0.0) + float(r.get("amount") or 0)

    # Join keys
    customers = set(open_by_cust.keys()) | set(overdue_by_cust.keys())
    out: List[Dict[str, Any]] = []
    for cid in sorted(customers):
        overdue = overdue_by_cust.get(cid, 0.0)
        pipeline_amt = open_by_cust.get(cid, 0.0)
        base = 20.0
        overdue_factor = min(50.0, (overdue / 1000.0) * 5.0)
        pipeline_factor = min(30.0, (pipeline_amt / 10000.0) * 10.0)
        score = min(100.0, base + overdue_factor + pipeline_factor)
        out.append({
            "customer_id": cid,
            "overdue_ar_amount": overdue,
            "open_pipeline_amount": pipeline_amt,
            "risk_score": score,
            "explain": {
                "formula": "min(100, base + overdue_factor + pipeline_factor)",
                "base": 20.0,
                "overdue_factor": "min(50, overdue_ar_amount/1000*5)",
                "pipeline_factor": "min(30, open_pipeline_amount/10000*10)",
                "sources": ["ACE Books v_ar_open" if books else "sage_ar_snapshot", "crm_pipeline_snapshot"],
            }
        })
    return {"customers": out}

@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",), tags=("crm", "crm_dashboard", "executive"))
def get_crm_stats(client: DBClient = db) -> Dict[str, Any]:
    """
    High-level CRM Stats for Dashboard.
    """
    from src.fin.readmodel import live
    if live():
        # Real deals (services/crm_hub): open pipeline and win rate from the sales pipeline, customers
        # from ACE Books sales. (Open invoices are receivables, not pipeline; paid invoices are not "wins".)
        from src.services import crm_hub
        o = crm_hub.overview()
        risks = risk_scores(client).get("customers", [])
        return {
            "pipeline_value": o["open_pipeline_value"], "active_opps": o["open_deals"], "win_rate": o["win_rate_90d"] or 0,
            "avg_risk_score": sum(r["risk_score"] for r in risks) / len(risks) if risks else 0,
            "recent_deals": [{"customer_id": w["customer_id"], "name": w["company_name"], "amount": float(w["expected_value"] or 0),
                              "stage": "won", "close_date": str(w["won_at"])[:10]} for w in o["recently_won"]],
            "customer_count": o["customers"]["on_file"], "active_customers": o["customers"]["active_365"],
        }
    # 1. Pipeline Value — derived from sage_ar_snapshot (invoices as sales opportunities)
    crm = client.table("sage_ar_snapshot").select(
        "invoice_id,customer_id,amount,balance,status,date"
    ).gt("amount", 0).order("imported_at", desc=True).limit(5000).execute()
    rows = crm.data or []

    open_rows   = [r for r in rows if float(r.get("balance") or 0) > 0]
    closed_rows = [r for r in rows if float(r.get("balance") or 0) == 0 and float(r.get("amount") or 0) > 0]
    invoiced_rows = [r for r in rows if float(r.get("amount") or 0) > 0]

    pipeline_val = sum(float(r.get("amount") or 0) for r in open_rows)
    active_opps  = len(open_rows)

    # 2. Win Rate (fully-paid invoices as "won")
    total = len(invoiced_rows)
    win_rate = round(len(closed_rows) / total * 100, 1) if total > 0 else 0

    # 3. Risk Score (Avg)
    risks = risk_scores(client).get("customers", [])
    avg_risk = sum(r["risk_score"] for r in risks) / len(risks) if risks else 0

    # 4. Customer count — from Sage master data snapshot (deduplicated by customer_id)
    try:
        cust_res = client.table("sage_customers_snapshot").select("customer_id").execute()
        customer_count = len(set(
            r["customer_id"] for r in (cust_res.data or []) if r.get("customer_id")
        ))
        active_customers = customer_count
    except Exception:
        customer_count = 0
        active_customers = 0

    recent_deals = sorted(rows, key=lambda r: r.get("date") or "", reverse=True)[:5]

    return {
        "pipeline_value": pipeline_val,
        "active_opps": active_opps,
        "win_rate": win_rate,
        "avg_risk_score": avg_risk,
        "recent_deals": recent_deals,
        "customer_count": customer_count,
        "active_customers": active_customers,
    }
