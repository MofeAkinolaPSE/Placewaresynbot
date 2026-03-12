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

    # Overdue AR by customer
    sage_batch_id = get_sage_kpi_batch_id()
    ar_q = client.table("sage_ar_snapshot").select("customer_id,due_date,balance")
    if sage_batch_id:
        ar_q = ar_q.eq("batch_id", sage_batch_id)
    ar = ar_q.order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    ar_rows = ar.data or []
    def parse_date(s: str | None):
        if not s:
            return None
        try:
            return datetime.date.fromisoformat(s)
        except Exception:
            return None
    overdue_by_cust: Dict[str, float] = {}
    for r in ar_rows:
        dd = parse_date(r.get("due_date")) or today
        bal = float(r.get("balance") or 0)
        cid = r.get("customer_id") or ""
        if cid and bal > 0 and dd < today:
            overdue_by_cust[cid] = overdue_by_cust.get(cid, 0.0) + bal

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
                "sources": ["sage_ar_snapshot", "crm_pipeline_snapshot"],
            }
        })
    return {"customers": out}

@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",), tags=("crm", "crm_dashboard", "executive"))
def get_crm_stats(client: DBClient = db) -> Dict[str, Any]:
    """
    High-level CRM Stats for Dashboard.
    """
    # 1. Pipeline Value
    # Using snapshot
    crm = client.table("crm_pipeline_snapshot").select("amount,status,stage").order("imported_at", desc=True).limit(1000).execute()
    rows = crm.data or []
    
    pipeline_val = sum(float(r.get("amount") or 0) for r in rows if r.get("status") in ["Open", "Pipeline", "Pending"])
    
    # 2. Win Rate (simulate or calc if historical data exists)
    won = len([r for r in rows if r.get("status") == "Won"])
    total = len(rows)
    win_rate = (won / total * 100) if total > 0 else 0
    
    # 3. Risk Score (Avg)
    risks = risk_scores(client).get("customers", [])
    avg_risk = sum(r["risk_score"] for r in risks) / len(risks) if risks else 0
    
    return {
        "pipeline_value": pipeline_val,
        "active_opps": len([r for r in rows if r.get("status") in ["Open", "Pipeline", "Pending"]]),
        "win_rate": win_rate,
        "avg_risk_score": avg_risk,
        "recent_deals": rows[:5]
    }
