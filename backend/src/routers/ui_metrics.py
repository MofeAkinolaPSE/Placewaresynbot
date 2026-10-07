from fastapi import APIRouter, Depends
from typing import Any

import src.db as db

router = APIRouter(prefix="/ui", tags=["ui"])


def auth_stub():
    # Placeholder auth dependency — in real app use JWT verification
    return True


@router.get('/metrics/summary')
def metrics_summary(_=Depends(auth_stub)) -> Any:
    """Return a small set of metrics for UI cards (ACE Books once live, else Sage snapshots)."""
    from src.fin.readmodel import live
    if live():
        from src.services import books_analytics
        t = books_analytics.crm_totals()
        return {"total_leads": t["customer_count"], "pipeline_value": round(t["open_value"], 2),
                "forecast": round(t["invoiced"], 2), "pending_routes": t["open_count"]}
    try:
        ar_res = db.db.table("sage_ar_snapshot").select("amount, balance").execute()
        ar_rows = ar_res.data or []
    except Exception:
        ar_rows = []

    try:
        cust_res = db.db.table("sage_customers_snapshot").select("customer_id").execute()
        total_leads = len(set(
            r["customer_id"] for r in (cust_res.data or []) if r.get("customer_id")
        ))
    except Exception:
        total_leads = 0

    pipeline_value = sum(float(r.get("amount") or 0) for r in ar_rows if float(r.get("balance") or 0) > 0)
    forecast       = sum(float(r.get("amount") or 0) for r in ar_rows)
    pending_routes = sum(1 for r in ar_rows if float(r.get("balance") or 0) > 0)

    return {
        "total_leads":    total_leads,
        "pipeline_value": round(pipeline_value, 2),
        "forecast":       round(forecast, 2),
        "pending_routes": pending_routes,
    }
