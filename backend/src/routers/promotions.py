from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from src.workflow.expiry_prevention import create_promotion, list_promotions
from src.middleware import verify_jwt

router = APIRouter(prefix="/promotions", tags=["promotions"])


class PromotionRequest(BaseModel):
    sku: str
    batch_id: str | None = None
    qty: float
    discount_pct: float


@router.post("/create")
async def api_create_promotion(req: PromotionRequest, request: Request, _u=Depends(lambda r: verify_jwt(r))):
    # allow only sales or procurement roles to create promotions
    roles = set(getattr(request.state, "user", {}).get("roles") or [])
    if not roles.intersection({"sales", "procurement", "marketing"}):
        raise HTTPException(status_code=403, detail="Insufficient role to create promotions")
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return create_promotion(req.sku, req.batch_id, req.qty, req.discount_pct, actor)


@router.get("/list")
async def api_list_promotions(_u=Depends(lambda r: verify_jwt(r))):
    return list_promotions()
