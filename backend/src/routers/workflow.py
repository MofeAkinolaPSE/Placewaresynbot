from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from src.workflow.batch_locking import lock_batch, unlock_batch, is_batch_locked, auto_release_batch
# TABLE_BATCHES not required here; removed to avoid import error
from src.middleware import verify_jwt, require_role
from src.db import db
from src.constants import TABLE_AUDIT_LOGS
from src.services.realtime import realtime_hub
from src.cache import invalidate_cache_tags
from datetime import datetime

router = APIRouter(prefix="/workflow", tags=["workflow"])


class LockRequest(BaseModel):
    batch_id: str
    reason: str | None = None


@router.post("/lock_batch")
async def api_lock_batch(req: LockRequest, request: Request, _u=Depends(require_role("compliance"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    res = lock_batch(req.batch_id, req.reason or "locked_by_system", actor)
    await realtime_hub.broadcast("workflow_updates", {
        "event": "batch_locked",
        "batch_id": req.batch_id,
        "reason": req.reason or "locked_by_system",
        "actor": actor,
        "at": datetime.utcnow().isoformat() + "Z",
    })
    await realtime_hub.broadcast("alerts_updates", {
        "event": "compliance_alert",
        "batch_id": req.batch_id,
        "severity": "high",
        "at": datetime.utcnow().isoformat() + "Z",
    })
    await realtime_hub.broadcast("finance_updates", {
        "event": "compliance_lock_changed",
        "batch_id": req.batch_id,
        "status": "locked",
        "at": datetime.utcnow().isoformat() + "Z",
    })
    invalidate_cache_tags("finance", "finance_kpis", "finance_trend", "executive", "alerts")
    return res


class UnlockRequest(BaseModel):
    batch_id: str


@router.post("/unlock_batch")
async def api_unlock_batch(req: UnlockRequest, request: Request, _u=Depends(require_role("compliance"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    res = unlock_batch(req.batch_id, actor)
    await realtime_hub.broadcast("workflow_updates", {
        "event": "batch_unlocked",
        "batch_id": req.batch_id,
        "actor": actor,
        "at": datetime.utcnow().isoformat() + "Z",
    })
    await realtime_hub.broadcast("finance_updates", {
        "event": "compliance_lock_changed",
        "batch_id": req.batch_id,
        "status": "unlocked",
        "at": datetime.utcnow().isoformat() + "Z",
    })
    invalidate_cache_tags("finance", "finance_kpis", "finance_trend", "executive", "alerts")
    return res


@router.get("/batch_locked/{batch_id}")
async def api_is_locked(batch_id: str, _u=Depends(verify_jwt)):
    return {"locked": is_batch_locked(batch_id)}


@router.post("/batch-approve/{batch_id}")
async def api_batch_approve(batch_id: str, request: Request, _u=Depends(require_role("compliance"))):
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    res = auto_release_batch(batch_id, actor)
    if not res.get("ok"):
        if res.get("error") == "lock_record_not_found":
            raise HTTPException(status_code=404, detail=res["error"])
        raise HTTPException(status_code=400, detail=res.get("error", "batch_approval_failed"))
    await realtime_hub.broadcast("workflow_updates", {
        "event": "batch_approved",
        "batch_id": batch_id,
        "actor": actor,
        "at": datetime.utcnow().isoformat() + "Z",
    })
    await realtime_hub.broadcast("finance_updates", {
        "event": "batch_approved",
        "batch_id": batch_id,
        "actor": actor,
        "at": datetime.utcnow().isoformat() + "Z",
    })
    await realtime_hub.broadcast("logistics_updates", {
        "event": "batch_approved",
        "batch_id": batch_id,
        "actor": actor,
        "at": datetime.utcnow().isoformat() + "Z",
    })
    invalidate_cache_tags("finance", "logistics", "ops_kpis", "executive", "alerts")
    return {"ok": True, "batch_id": batch_id, "auto_released": True}


@router.get("/compliance/export")
async def api_compliance_export(limit: int = 500, _u=Depends(require_role("compliance"))):
    safe_limit = max(1, min(limit, 2000))

    locks_resp = db.table("batch_status_locks").select("batch_id,locked,lock_reason,created_at,created_by").order("created_at", desc=True).limit(safe_limit).execute()
    locks = locks_resp.data if hasattr(locks_resp, "data") else []

    audits_resp = db.table(TABLE_AUDIT_LOGS).select("event_type,event_class,action,outcome,actor_id,subject_type,subject_id,details,created_at").eq("event_class", "compliance").order("created_at", desc=True).limit(safe_limit).execute()
    audits = audits_resp.data if hasattr(audits_resp, "data") else []

    return {
        "format": "json",
        "lock_events": locks,
        "audit_events": audits,
        "counts": {
            "lock_events": len(locks),
            "audit_events": len(audits),
        },
    }
