from fastapi import APIRouter, Depends, HTTPException, Request, Response
from typing import Dict, Any, List
from src.middleware import verify_jwt, require_role
from src.services.intelligence import (
    get_inventory_dashboard,
    get_workforce_dashboard,
    get_active_alerts,
    filter_alerts_by_category,
    generate_executive_briefing,
    get_workstation_summary,
)
from src.services.crm import get_crm_stats
from src.services.sage_adapter.service import kpis as finance_kpis
import logging

router = APIRouter(prefix="/dashboard", tags=["dashboard", "intelligence"])
audit_logger = logging.getLogger("audit")

# --- Dependencies ---

def require_management(request: Request) -> Dict[str, Any]:
    """Roles: admin, management, finance (for specific views)."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "management", "finance", "ops"} 
    
    if not any(r in allowed for r in roles):
        raise HTTPException(403, "Insufficient privileges for dashboard access")
    return payload

def require_workforce_view(request: Request) -> Dict[str, Any]:
    """Separate, slightly wider gate than require_management just for
    /dashboard/workforce -- an hr-role account needs to see workforce/
    timesheet aggregates, but must NOT gain access to require_management's
    other endpoints (finance/inventory/CRM/alerts) as a side effect, so this
    is its own dependency rather than adding "hr" to require_management
    itself. Was previously gated by require_management, which doesn't
    include "hr" at all -- every hr-role login 403'd on the HR Overview
    tab's own workforce KPI card."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "management", "finance", "ops", "hr"}
    if not any(r in allowed for r in roles):
        raise HTTPException(403, "Insufficient privileges for dashboard access")
    return payload


def require_executive(request: Request) -> Dict[str, Any]:
    """Strategic View: Admin, Management, Finance."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "management", "finance"}
    if not any(r in allowed for r in roles):
        raise HTTPException(403, "Executive Briefing is restricted")
    return payload

# --- Endpoints ---

@router.get("/finance")
async def dashboard_finance(response: Response, user: Dict[str, Any] = Depends(require_management)):
    """Finance specific dashboard data."""
    if "finance" not in user.get("roles", []) and "admin" not in user.get("roles", []) and "management" not in user.get("roles", []):
         raise HTTPException(403, "Role not authorized for Finance view")
    response.headers["Cache-Control"] = "no-store, no-cache"
    try:
        return {"data": finance_kpis()}
    except Exception as e:
        logging.error(f"Finance dashboard error: {e}")
        raise HTTPException(500, "Failed to load finance metrics")

@router.get("/inventory")
async def dashboard_inventory(response: Response, user: Dict[str, Any] = Depends(require_management)):
    """Inventory specific dashboard data."""
    response.headers["Cache-Control"] = "no-store, no-cache"
    return {"data": get_inventory_dashboard()}

@router.get("/workforce")
async def dashboard_workforce(response: Response, user: Dict[str, Any] = Depends(require_workforce_view)):
    """Workforce specific dashboard data."""
    response.headers["Cache-Control"] = "no-store, no-cache"
    return {"data": get_workforce_dashboard()}

@router.get("/crm")
async def dashboard_crm(response: Response, user: Dict[str, Any] = Depends(require_management)):
    """CRM specific dashboard data."""
    response.headers["Cache-Control"] = "no-store, no-cache"
    return {"data": get_crm_stats()}

@router.get("/alerts")
async def list_alerts(response: Response, user: Dict[str, Any] = Depends(require_management)):
    """Active system alerts, filtered to only the categories the caller's
    roles may see (constants.ALERT_CATEGORY_VISIBILITY) -- require_management
    alone lets 'ops' through, but ops must never see finance-category alert
    text (e.g. "Treasury Alert" embeds a real ₦ figure)."""
    response.headers["Cache-Control"] = "no-store, no-cache"
    visible = filter_alerts_by_category(get_active_alerts(), user.get("roles", []))
    return {"data": visible}

@router.get("/workstation")
async def dashboard_workstation(response: Response, user: Dict[str, Any] = Depends(verify_jwt)):
    """
    ACE Workstation — org-wide cover-page summary. Any authenticated user
    gets a response (unlike every other /dashboard/* endpoint, which is
    role-restricted at the route boundary); the redaction of sensitive
    (₦-denominated) fields happens inside get_workstation_summary() based on
    the caller's own roles, not at this route's gate.
    """
    response.headers["Cache-Control"] = "no-store, no-cache"
    try:
        return {"data": get_workstation_summary(user.get("roles", []))}
    except Exception as e:
        logging.error(f"Workstation summary error: {e}")
        raise HTTPException(500, "Failed to load workstation summary")

@router.get("/executive")
def executive_overview(refresh: bool = False, user: Dict[str, Any] = Depends(require_executive)):
    """The company on one page, from the modules that own each figure (services/executive.py)."""
    from src.services.executive import overview
    try:
        return overview(refresh=refresh)
    except Exception:
        logging.getLogger(__name__).exception("executive overview failed")
        raise HTTPException(500, "Executive overview is unavailable")


@router.get("/executive-briefing")
async def executive_briefing(response: Response, user: Dict[str, Any] = Depends(require_executive)):
    """
    High-value unified report.
    Audited access.
    """
    audit_logger.info({"event": "executive_briefing_access", "user": user.get("sub")})
    response.headers["Cache-Control"] = "no-store, no-cache"
    try:
        return {"data": generate_executive_briefing()}
    except Exception as e:
        logging.error(f"Briefing generation failed: {e}")
        raise HTTPException(500, "Failed to generate briefing")
