from fastapi import APIRouter, Depends
from typing import Any

import src.db as db

router = APIRouter(prefix="/ui", tags=["ui"])


def auth_stub():
    # Placeholder auth dependency — in real app use JWT verification
    return True


@router.get('/metrics/summary')
def metrics_summary(_=Depends(auth_stub)) -> Any:
    """Return a small set of metrics for UI cards, aggregated live from Sage snapshot tables."""
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
