from fastapi import APIRouter, Depends, HTTPException, Request, Response
from typing import Dict, Any, List
from src.middleware import verify_jwt, require_role
from src.services.intelligence import (
    get_inventory_dashboard,
    get_workforce_dashboard,
    get_active_alerts,
    generate_executive_briefing
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

def require_executive(request: Request) -> Dict[str, Any]:
    """Strategic View: Admin, Management only."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "management"}
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
async def dashboard_workforce(response: Response, user: Dict[str, Any] = Depends(require_management)):
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
    """Active system alerts."""
    response.headers["Cache-Control"] = "no-store, no-cache"
    return {"data": get_active_alerts()}

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
