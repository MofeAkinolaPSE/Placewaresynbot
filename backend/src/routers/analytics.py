from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict, Any, List
from datetime import datetime
import logging
from src.middleware import verify_jwt
from src.services.sage_adapter.service import kpis as fetch_sage_kpis
from src.services.sage_adapter.service import get_latest_gl_snapshot, ar_trend_summary

router = APIRouter(prefix="/analytics", tags=["analytics"])


# Logger for audit trail
audit_logger = logging.getLogger("audit")

def require_analytics_access(request: Request) -> Dict[str, Any]:
    """Dependency to enforce role-based access for analytics."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    
    # Allowed roles for analytics
    allowed = {"admin", "finance"}
    
    # Check intersection
    if not any(r in allowed for r in roles):
        # Audit log for denied access
        audit_logger.warning({
            "event": "access_denied",
            "endpoint": request.url.path,
            "user_id": payload.get("sub"),
            "role": roles,
            "timestamp": datetime.now().isoformat()
        })
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Unauthorized",
                "code": "AUTH_403",
                "message": "User role not permitted to access analytics KPIs"
            }
        )
    
    return payload

@router.get("/kpis")
async def get_analytics_kpis(
    request: Request,
    user: Dict[str, Any] = Depends(require_analytics_access)
):
    """
    Get high-level KPIs for definitions.
    Roles: admin, finance
    """
    # 1. Fetch Data (Deterministic)
    try:
        raw_data = fetch_sage_kpis()
    except Exception as e:
        logging.error(f"Failed to fetch Sage KPIs: {e}")
        # Return graceful error or empty logic
        raise HTTPException(status_code=500, detail="Failed to retrieve analytics data")

    # 2. Return standard structure matching frontend expectations
    # Frontend expects { data: { ar: {...}, ap: {...}, cash: ... } }
    
    response_data = {
        "data": raw_data, 
        "meta": {
            "as_of": datetime.now().isoformat(),
            "source": ["Sage AR", "Sage AP"]
        }
    }

    # 3. Audit Log (Success)
    audit_logger.info({
        "event": "kpi_access_success",
        "user_id": user.get("sub"),
        "role": user.get("roles"),
        "timestamp": datetime.now().isoformat()
    })

    return response_data

@router.get("/trend")
async def get_financial_trend(user: Dict[str, Any] = Depends(require_analytics_access)):
    """
    Get 6-month AR/AP trend for charts.
    """
    try:
        return {"data": ar_trend_summary(periods=6)}
    except Exception as e:
        audit_logger.error(f"Trend fetch failed: {e}")
        return {"data": {"periods": []}}

@router.get("/gl")
async def get_general_ledger(
    limit: int = 1000,
    user: Dict[str, Any] = Depends(require_analytics_access)
):
    """
    Get General Ledger entries (Snapshot view).
    Roles: admin, finance
    """
    try:
        rows = get_latest_gl_snapshot(limit=limit)
        return {"data": rows}
    except Exception as e:
        audit_logger.error(f"GL fetch failed: {e}")
        raise HTTPException(500, "Failed to retrieve GL data")

@router.get("/transactions")
async def get_recent_transactions(
    limit: int = 5, 
    user: Dict[str, Any] = Depends(require_analytics_access)
):
    """
    Get recent financial movements from GL snapshot.
    """
    try:
        # Re-use GL snapshot but limit to top N
        rows = get_latest_gl_snapshot(limit=limit)
        # Transform for UI: { "description", "date", "amount", "type" }
        txs = []
        for r in rows:
            debit = float(r.get("debit") or 0)
            credit = float(r.get("credit") or 0)
            amount = debit if debit > 0 else credit
            type_ = "debit" if debit > 0 else "credit"
            txs.append({
                "id": r.get("id"),
                "description": r.get("account_name") or f"Account {r.get('account_code')}",
                "date": r.get("imported_at") or datetime.now().isoformat(),
                "amount": amount,
                "type": type_
            })
        return {"data": txs}
    except Exception as e:
        audit_logger.error(f"Transaction fetch failed: {e}")
        return {"data": []}


@router.get("/profitability")
async def get_profitability_summary(
    limit: int = 1000,
    user: Dict[str, Any] = Depends(require_analytics_access),
):
    """Compute simple profitability metrics from latest GL snapshot.

    This approximates revenue as credit entries and expenses as debit entries,
    aggregated by period.
    Roles: admin, finance
    """
    try:
        rows = get_latest_gl_snapshot(limit=limit)
        buckets: Dict[str, Dict[str, float]] = {}
        for r in rows:
            period = r.get("period") or "Unknown"
            try:
                debit = float(r.get("debit") or 0)
            except (TypeError, ValueError):
                debit = 0.0
            try:
                credit = float(r.get("credit") or 0)
            except (TypeError, ValueError):
                credit = 0.0

            agg = buckets.setdefault(period, {"revenue": 0.0, "expenses": 0.0})
            if credit > 0:
                agg["revenue"] += credit
            if debit > 0:
                agg["expenses"] += debit

        periods: List[str] = sorted(buckets.keys())
        series: List[Dict[str, Any]] = []
        total_revenue = 0.0
        total_expenses = 0.0
        for p in periods:
            rev = buckets[p]["revenue"]
            exp = buckets[p]["expenses"]
            total_revenue += rev
            total_expenses += exp
            series.append({
                "period": p,
                "revenue": rev,
                "expenses": exp,
                "profit": rev - exp,
            })

        total_profit = total_revenue - total_expenses
        margin = (total_profit / total_revenue) if total_revenue > 0 else 0.0

        return {
            "data": {
                "series": series,
                "totals": {
                    "revenue": total_revenue,
                    "expenses": total_expenses,
                    "profit": total_profit,
                    "margin": margin,
                },
            }
        }
    except Exception as e:
        audit_logger.error(f"Profitability fetch failed: {e}")
        return {
            "data": {
                "series": [],
                "totals": {
                    "revenue": 0.0,
                    "expenses": 0.0,
                    "profit": 0.0,
                    "margin": 0.0,
                },
            }
        }
