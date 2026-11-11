"""Phone / desktop notifications (Web Push) - turn on, turn off, test. See src/services/web_push.py."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from src.middleware import verify_jwt
from src.services import web_push

log = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["Notifications"])


@router.get("/public-key")
def public_key(_u=Depends(verify_jwt)):
    try:
        return {"public_key": web_push.public_key()}
    except Exception as exc:
        log.warning("web push keys unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Phone notifications are not available on this server yet")


@router.post("/subscribe")
def subscribe(request: Request, payload: Dict[str, Any] = Body(...), user=Depends(verify_jwt)):
    try:
        web_push.subscribe(str(user.get("sub")), payload.get("subscription") or payload, request.headers.get("user-agent"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(payload: Dict[str, Any] = Body(default={}), user=Depends(verify_jwt)):
    endpoint: Optional[str] = payload.get("endpoint")
    return {"removed": web_push.unsubscribe(str(user.get("sub")), endpoint)}


@router.get("/devices")
def devices(user=Depends(verify_jwt)):
    return {"devices": web_push.devices(str(user.get("sub")))}


@router.post("/test")
async def test(user=Depends(verify_jwt)):
    """Send a test notification to the signed-in person's own devices and say how it went."""
    res = await run_in_threadpool(web_push.send, [str(user.get("sub"))], "ACE notifications are on",
                                  "You'll be told here when something needs your approval.", "/workspace", "test", True)
    return res
