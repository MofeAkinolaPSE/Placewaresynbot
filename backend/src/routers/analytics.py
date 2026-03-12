from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict, Any, List
from dataclasses import asdict
from datetime import datetime
import logging
from src.middleware import verify_jwt, require_role
from src.services.sage_adapter.service import kpis as fetch_sage_kpis
from src.services.sage_adapter.service import get_latest_gl_snapshot, ar_trend_summary
from src.services.margin_analysis import margin_driver_report
from src.services.scenario_engine import ScenarioEngine, Lever

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


def require_finance_trend_access(request: Request) -> Dict[str, Any]:
    """Dependency for dashboard-visible finance trend access."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "finance", "management", "ops"}

    if not any(r in allowed for r in roles):
        audit_logger.warning({
            "event": "access_denied",
            "endpoint": request.url.path,
            "user_id": payload.get("sub"),
            "role": roles,
            "timestamp": datetime.now().isoformat(),
        })
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Unauthorized",
                "code": "AUTH_403",
                "message": "User role not permitted to access finance trend",
            },
        )
    return payload


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _cashflow_summary(periods: int = 6, limit: int = 5000) -> Dict[str, Any]:
    rows = get_latest_gl_snapshot(limit=limit)
    buckets: Dict[str, Dict[str, float]] = {}

    for row in rows:
        period = row.get("period") or "Unknown"
        debit = _to_float(row.get("debit"))
        credit = _to_float(row.get("credit"))

        agg = buckets.setdefault(period, {"inflow": 0.0, "outflow": 0.0})
        if credit > 0:
            agg["inflow"] += credit
        if debit > 0:
            agg["outflow"] += debit

    sorted_periods = sorted(buckets.keys())[-max(1, periods):]
    chart_periods: List[Dict[str, Any]] = []
    for p in sorted_periods:
        inflow = buckets[p]["inflow"]
        outflow = buckets[p]["outflow"]
        chart_periods.append(
            {
                "period": p,
                "inflow": inflow,
                "outflow": outflow,
                "net": inflow - outflow,
                "amount": inflow,
            }
        )

    return {"mode": "cashflow", "periods": chart_periods}

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
async def get_financial_trend(user: Dict[str, Any] = Depends(require_finance_trend_access)):
    """
    Get 6-month AR/AP trend for charts.
    """
    try:
        return {"data": _cashflow_summary(periods=6)}
    except Exception as e:
        audit_logger.error(f"Trend fetch failed: {e}")
        return {"data": {"mode": "cashflow", "periods": []}}

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

@router.get("/margin_drivers")
async def get_margin_drivers(
    user: Dict[str, Any] = Depends(require_analytics_access),
):
    """Return margin driver decomposition across GL cost buckets.

    Breaks down costs by bucket (COGS, Cold-Chain, Workforce, QA/Compliance,
    Overheads, Other), showing MoM change and severity per driver.
    Roles: admin, finance
    """
    try:
        report = margin_driver_report()
        return {"data": report}
    except Exception as exc:
        audit_logger.error(f"margin_drivers failed: {exc}")
        raise HTTPException(status_code=500, detail="Margin driver analysis unavailable")


@router.post("/scenarios")
async def run_scenarios(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_analytics_access),
):
    """Run parameterised revenue scenario modelling.

    Accepts:  {levers: [{name, lever_type, magnitude_pct, product_filter?,
                         target_accounts?, revenue_base?, confidence?}],
              base_revenue?: float, base_cost?: float}
    Returns:  ScenarioResult with ranked weekly-uplift initiatives.
    Roles: admin, finance
    """
    try:
        levers_raw: List[Dict[str, Any]] = payload.get("levers", [])
        if not levers_raw:
            raise HTTPException(status_code=422, detail="'levers' list is required and must not be empty")

        levers = [
            Lever(
                name=lv["name"],
                lever_type=lv.get("lever_type", "volume"),
                magnitude_pct=float(lv.get("magnitude_pct", 0.05)),
                product_filter=lv.get("product_filter", []),
                target_accounts=lv.get("target_accounts", []),
                revenue_base=float(lv["revenue_base"]) if lv.get("revenue_base") is not None else None,
                confidence=lv.get("confidence", "medium"),
            )
            for lv in levers_raw
        ]

        # Use caller-supplied base, or fall back to live KPI totals
        if "base_revenue" in payload and "base_cost" in payload:
            base_revenue = float(payload["base_revenue"])
            base_cost = float(payload["base_cost"])
        else:
            kpi_data = fetch_sage_kpis()
            base_revenue = float(kpi_data.get("total_revenue") or 0.0)
            base_cost = float(kpi_data.get("total_cost") or 0.0)

        engine = ScenarioEngine()
        result = engine.run(base_revenue, base_cost, levers)

        # Convert dataclasses to plain dicts
        result_dict = asdict(result)
        return {"data": result_dict}
    except HTTPException:
        raise
    except Exception as exc:
        audit_logger.error(f"scenarios endpoint failed: {exc}")
        raise HTTPException(status_code=500, detail="Scenario engine failed")