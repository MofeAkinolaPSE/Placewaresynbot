from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from src.middleware import verify_jwt
from src.workflow.replenishment_actions import create_replenishment_request, approve_replenishment, create_po_for_request

router = APIRouter(prefix="/replenishment", tags=["replenishment"])


class ReplenishCreate(BaseModel):
    sku: str
    product_id: str | None = None
    requested_qty: float


@router.post("/create")
async def api_create_replenishment(payload: ReplenishCreate, request: Request, user=Depends(lambda r: verify_jwt(r))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return create_replenishment_request(payload.sku, payload.product_id, payload.requested_qty, actor)


class ReplenishApprove(BaseModel):
    request_id: str


@router.post("/approve")
async def api_approve_replenishment(payload: ReplenishApprove, request: Request, user=Depends(lambda r: verify_jwt(r, required_role="procurement"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return approve_replenishment(payload.request_id, actor)


class CreatePO(BaseModel):
    request_id: str
    po_id: str


@router.post("/create_po")
async def api_create_po(payload: CreatePO, request: Request, user=Depends(lambda r: verify_jwt(r, required_role="procurement"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return create_po_for_request(payload.request_id, payload.po_id, actor)
