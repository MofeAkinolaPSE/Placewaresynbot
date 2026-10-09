import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from pydantic import BaseModel
from src.db import db
from src.middleware import verify_jwt, require_role
from src.workflow.replenishment_actions import (
    create_replenishment_request,
    approve_replenishment,
    create_po_for_request,
    mark_replenishment_received,
    cancel_replenishment,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/replenishment", tags=["replenishment"])

# These three steps previously demanded role "procurement", which is not in
# app.py's ALLOWED_ROLES -- an account holding it cannot even log in. In
# practice only the admin superrole could advance a request, which is why all
# 774 of them sat at "recommended" and the reorder queue never moved. Gate on
# roles that actually exist and actually do this work instead.
_PROCUREMENT_ROLES = {"admin", "ops", "management", "finance"}


def _require_procurement(request: Request) -> Dict[str, Any]:
    payload = verify_jwt(request)
    roles = {str(r).lower() for r in (payload.get("roles") or [])}
    if not roles & _PROCUREMENT_ROLES:
        raise HTTPException(403, "Requires ops, finance, management or admin role")
    return payload


@router.get("")
@router.get("/")
def api_list_replenishment(
    status: Optional[str] = Query(None, description="recommended | approved | ordered | received | cancelled"),
    limit: int = Query(100, le=500),
    _u=Depends(verify_jwt),
):
    """List replenishment requests — the reorder queue.

    There was no list endpoint at all before this, so requests raised from the
    inventory workspace were write-only: nothing in the app could show them,
    approve them or receive them.
    """
    try:
        q = db.table("replenishment_requests").select("*")
        if status:
            q = q.eq("status", status)
        rows = q.order("created_at", desc=True).limit(limit).execute().data or []
        return {"data": rows, "total": len(rows)}
    except Exception as exc:
        logger.error("replenishment list error: %s", exc)
        raise HTTPException(500, detail="Failed to list replenishment requests")


@router.get("/summary")
def api_replenishment_summary(_u=Depends(verify_jwt)):
    """Counts per status, for the queue's tab badge and KPI."""
    try:
        rows = db.table("replenishment_requests").select("status").limit(5000).execute().data or []
        counts: Dict[str, int] = {}
        for r in rows:
            s = r.get("status") or "unknown"
            counts[s] = counts.get(s, 0) + 1
        return {"counts": counts, "total": len(rows)}
    except Exception as exc:
        logger.error("replenishment summary error: %s", exc)
        raise HTTPException(500, detail="Failed to summarise replenishment requests")


class ReplenishCreate(BaseModel):
    sku: str
    product_id: str | None = None
    requested_qty: float


@router.post("/create")
def api_create_replenishment(payload: ReplenishCreate, request: Request, user=Depends(verify_jwt)):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return create_replenishment_request(payload.sku, payload.product_id, payload.requested_qty, actor)


class ReplenishApprove(BaseModel):
    request_id: str


@router.post("/approve")
def api_approve_replenishment(payload: ReplenishApprove, request: Request, user=Depends(_require_procurement)):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return approve_replenishment(payload.request_id, actor)


class CreatePO(BaseModel):
    request_id: str
    po_id: str


@router.post("/create_po")
def api_create_po(payload: CreatePO, request: Request, user=Depends(_require_procurement)):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return create_po_for_request(payload.request_id, payload.po_id, actor)


class ReplenishReceived(BaseModel):
    request_id: str
    received_qty: float | None = None


@router.post("/received")
def api_replenishment_received(payload: ReplenishReceived, request: Request, user=Depends(_require_procurement)):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    result = mark_replenishment_received(payload.request_id, payload.received_qty, actor)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "request_not_found"))
    return result


class ReplenishCancel(BaseModel):
    request_id: str
    reason: str | None = None


@router.post("/cancel")
def api_cancel_replenishment(payload: ReplenishCancel, request: Request, user=Depends(_require_procurement)):
    """Cancel a reorder that hasn't been received. Sets status='cancelled'
    rather than deleting the row, so the request stays visible in history --
    matches how the 774-item stale backlog was cleared: marked cancelled, not
    dropped."""
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    result = cancel_replenishment(payload.request_id, actor, payload.reason)
    if not result.get("ok"):
        status = 409 if result.get("error") == "already_received" else 404
        raise HTTPException(status_code=status, detail=result.get("detail") or result.get("error", "request_not_found"))
    return result
