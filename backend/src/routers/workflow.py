from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from src.workflow.batch_locking import lock_batch, unlock_batch, is_batch_locked
from src.constants import TABLE_BATCHES
from src.middleware import verify_jwt

router = APIRouter(prefix="/workflow", tags=["workflow"])


class LockRequest(BaseModel):
    batch_id: str
    reason: str | None = None


@router.post("/lock_batch")
async def api_lock_batch(req: LockRequest, request: Request, _u=Depends(lambda r: verify_jwt(r, required_role="compliance"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    res = lock_batch(req.batch_id, req.reason or "locked_by_system", actor)
    return res


class UnlockRequest(BaseModel):
    batch_id: str


@router.post("/unlock_batch")
async def api_unlock_batch(req: UnlockRequest, request: Request, _u=Depends(lambda r: verify_jwt(r, required_role="compliance"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    res = unlock_batch(req.batch_id, actor)
    return res


@router.get("/batch_locked/{batch_id}")
async def api_is_locked(batch_id: str, _u=Depends(lambda r: verify_jwt(r))):
    return {"locked": is_batch_locked(batch_id)}
