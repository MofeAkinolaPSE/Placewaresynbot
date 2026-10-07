from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.constants import WEBSOCKET_ENABLED
from src.middleware import decode_jwt_token
from src.services.realtime import realtime_hub

logger = logging.getLogger("realtime_ws")
router = APIRouter(prefix="/realtime", tags=["realtime"])

_ALLOWED_CHANNELS: dict[str, set[str]] = {
    "workflow_updates": {"admin", "management", "compliance", "finance", "ops", "procurement"},
    "calendar_tasks": {"admin", "management", "hr", "ops", "finance", "sales", "crm"},
    "alerts_updates": {"admin", "management", "ops", "finance", "hr", "compliance", "procurement", "sales"},
    "inventory_updates": {"admin", "management", "ops", "inventory", "procurement", "finance"},
    "finance_updates": {"admin", "management", "finance", "ops"},
    "logistics_updates": {"admin", "management", "ops", "procurement", "inventory"},
    "staff_updates": {"admin", "management", "hr", "ops"},
    "crm_updates": {"admin", "management", "crm", "sales"},
    "chat_updates": {"admin", "management", "hr", "ops", "crm", "sales", "staff"},
    # Was missing entirely -- every connection attempt from Frontdesk.tsx/
    # CustomerWorkspace.tsx hit the "unknown channel" branch below and got
    # closed (4404), so the QC/Finance/Dispatch queue silently never
    # auto-refreshed live; it just retried the same failing connection
    # forever. Role set covers everyone who touches the invoice pipeline
    # (frontdesk/QC/finance/dispatch) plus CustomerWorkspace's own
    # audience (crm/sales), matching frontdesk.py's actual role gates.
    "frontdesk_updates": {"admin", "management", "finance", "ops", "quality_assurance", "qa", "crm", "sales", "frontdesk"},
    # Staff Workspace: every signed-in team member has one. Messages only say
    # "refresh" (with the user ids concerned), never the content itself.
    "workspace_updates": {"admin", "management", "manager", "finance", "ops", "operations", "procurement", "hr",
                          "sales", "crm", "quality_assurance", "qa", "logistics", "rider", "compliance", "viewer", "staff", "frontdesk"},
}


def _resolve_ws_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token.strip()
    auth = websocket.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _authorize_channel(websocket: WebSocket, channel: str) -> dict[str, Any]:
    if channel not in _ALLOWED_CHANNELS:
        await websocket.close(code=4404)
        raise RuntimeError("Unknown channel")

    token = _resolve_ws_token(websocket)
    if not token:
        await websocket.close(code=4401)
        raise RuntimeError("Missing token")

    try:
        payload = decode_jwt_token(token)
    except Exception as exc:
        await websocket.close(code=4401)
        raise RuntimeError("Invalid token") from exc

    roles = set(payload.get("roles") or [])
    allowed = _ALLOWED_CHANNELS[channel]
    if not roles.intersection(allowed):
        await websocket.close(code=4403)
        raise RuntimeError("Insufficient role")

    return payload


@router.websocket("/ws/{channel}")
async def realtime_channel_ws(websocket: WebSocket, channel: str):
    if not WEBSOCKET_ENABLED:
        await websocket.close(code=4403)
        return

    try:
        payload = await _authorize_channel(websocket, channel)
    except RuntimeError:
        return

    await realtime_hub.connect(channel, websocket)
    await realtime_hub.broadcast(
        channel,
        {
            "event": "subscriber_joined",
            "channel": channel,
            "user": payload.get("sub"),
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )

    try:
        while True:
            raw = await websocket.receive_text()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except Exception:
                message = {"type": "ping"}
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"event": "pong", "channel": channel}))
    except WebSocketDisconnect:
        await realtime_hub.disconnect(channel, websocket)
    except Exception as exc:
        logger.warning(f"realtime websocket error channel={channel}: {exc}")
        await realtime_hub.disconnect(channel, websocket)
