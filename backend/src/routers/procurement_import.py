from __future__ import annotations

import datetime as dt
import json
import logging
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.constants import WEBSOCKET_ENABLED
from src.db import (
    audit_event,
    create_procurement_shipment,
    create_procurement_shipment_event,
    get_procurement_shipment,
    list_procurement_events_feed,
    list_procurement_shipment_events,
    list_procurement_shipments,
    send_procurement_escalation_email,
    update_procurement_shipment,
)
from src.middleware import verify_jwt, require_role, decode_jwt_token
from src.services.intelligence import create_alert
from src.services.procurement_import import (
    run_clearance_analysis,
    transition_timestamp_patch,
    validate_state,
    validate_transition,
)
from src.services.realtime import realtime_hub

router = APIRouter(prefix="/procurement/import-agent", tags=["procurement", "import-agent"])
logger = logging.getLogger("procurement_import")


def require_procurement_read(request: Request) -> dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {"admin", "management", "ops", "procurement", "regulatory"}
    if not roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Insufficient privileges")
    return payload


def require_procurement_write(request: Request) -> dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {"admin", "management", "ops", "procurement"}
    if not roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Insufficient privileges")
    return payload


class ShipmentCreateRequest(BaseModel):
    shipment_ref: str = Field(..., min_length=3, max_length=120)
    supplier_name: str = Field(..., min_length=2, max_length=180)
    expected_arrival_date: str | None = None
    status: str = Field(default="in_transit")
    clearance_sla_days: int = Field(default=5, ge=1, le=90)
    currency: str = Field(default="NGN", min_length=3, max_length=4)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShipmentTransitionRequest(BaseModel):
    next_status: str
    reason: str = Field(default="manual_update", min_length=2, max_length=200)


class ClearanceAnalyzeRequest(BaseModel):
    threshold_days: int | None = Field(default=None, ge=1, le=90)
    daily_cost: float | None = Field(default=None, ge=0)


class EscalationRequest(BaseModel):
    reason: str = Field(default="clearance_delay_threshold_exceeded", min_length=3, max_length=300)
    notify_regulatory: bool = True
    notify_executive_dashboard: bool = True


def _sse_message(payload: dict[str, Any], event: str | None = None) -> str:
    chunks: list[str] = []
    if event:
        chunks.append(f"event: {event}")
    chunks.append(f"data: {json.dumps(payload)}")
    return "\n".join(chunks) + "\n\n"


@router.post("/shipments")
async def create_shipment(payload: ShipmentCreateRequest, user: dict[str, Any] = Depends(require_procurement_write)):
    try:
        status = validate_state(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    insert_payload = {
        "shipment_ref": payload.shipment_ref.strip(),
        "supplier_name": payload.supplier_name.strip(),
        "expected_arrival_date": payload.expected_arrival_date,
        "status": status,
        "clearance_sla_days": payload.clearance_sla_days,
        "currency": payload.currency.upper(),
        "metadata": payload.metadata,
        "updated_at": now_iso,
    }

    row = create_procurement_shipment(insert_payload)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create shipment")

    create_procurement_shipment_event(
        {
            "shipment_id": row.get("id"),
            "from_status": None,
            "to_status": status,
            "reason": "created",
            "actor_id": user.get("sub"),
            "details": payload.metadata,
        }
    )

    audit_event(
        "procurement_shipment_created",
        {
            "shipment_id": row.get("id"),
            "shipment_ref": row.get("shipment_ref"),
            "supplier_name": row.get("supplier_name"),
            "user_id": user.get("sub"),
            "status": row.get("status"),
        },
        event_class="workflow",
        subject_type="procurement_shipment",
        subject_id=str(row.get("id")),
        actor_id=user.get("sub"),
        actor_role=(user.get("roles") or [None])[0],
    )

    await realtime_hub.broadcast(
        "procurement_import",
        {
            "event": "shipment_created",
            "shipment": row,
            "at": now_iso,
        },
    )
    return {"data": row}


@router.patch("/shipments/{shipment_id}/status")
async def transition_shipment_status(
    shipment_id: str,
    payload: ShipmentTransitionRequest,
    user: dict[str, Any] = Depends(require_procurement_write),
):
    row = get_procurement_shipment(shipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shipment not found")

    current = str(row.get("status") or "").strip().lower()
    next_state = str(payload.next_status or "").strip().lower()
    try:
        validate_transition(current, next_state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    patch = transition_timestamp_patch(current, next_state)
    patch["last_risk_level"] = "warning" if next_state == "under_clearance" else "normal"
    patch["last_risk_reason"] = payload.reason

    updated = update_procurement_shipment(shipment_id, patch)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update shipment status")

    create_procurement_shipment_event(
        {
            "shipment_id": shipment_id,
            "from_status": current,
            "to_status": next_state,
            "reason": payload.reason,
            "actor_id": user.get("sub"),
            "details": {"transition_patch": patch},
        }
    )

    audit_event(
        "procurement_shipment_transitioned",
        {
            "shipment_id": shipment_id,
            "from_status": current,
            "to_status": next_state,
            "reason": payload.reason,
            "user_id": user.get("sub"),
        },
        event_class="workflow",
        subject_type="procurement_shipment",
        subject_id=shipment_id,
        actor_id=user.get("sub"),
        actor_role=(user.get("roles") or [None])[0],
    )

    await realtime_hub.broadcast(
        "procurement_import",
        {
            "event": "shipment_status_changed",
            "shipment": updated,
            "from_status": current,
            "to_status": next_state,
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )

    return {"data": updated}


@router.get("/shipments")
async def get_shipments(
    status: str | None = Query(default=None),
    supplier_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(require_procurement_read),
):
    rows = list_procurement_shipments(limit=limit, status=status, supplier_name=supplier_name)
    return {"data": rows, "count": len(rows), "viewer": user.get("sub")}


@router.get("/shipments/{shipment_id}/events")
async def get_shipment_events(
    shipment_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(require_procurement_read),
):
    events = list_procurement_shipment_events(shipment_id, limit=limit)
    return {"data": events, "count": len(events), "viewer": user.get("sub")}


@router.post("/analyze")
async def analyze_procurement_state(
    payload: ClearanceAnalyzeRequest,
    user: dict[str, Any] = Depends(require_procurement_read),
):
    rows = list_procurement_shipments(limit=500)
    analysis = run_clearance_analysis(
        rows,
        threshold_days=payload.threshold_days,
        daily_cost=payload.daily_cost,
    )

    if analysis.get("delayed_count", 0) > 0:
        audit_event(
            "procurement_clearance_delay_alert",
            {
                "delayed_count": analysis.get("delayed_count"),
                "threshold_days": analysis.get("threshold_days"),
                "estimated_total_impact": analysis.get("estimated_total_impact"),
                "user_id": user.get("sub"),
            },
            event_class="workflow",
            subject_type="procurement_port_clearance",
            subject_id="bulk",
            actor_id=user.get("sub"),
            actor_role=(user.get("roles") or [None])[0],
        )

    await realtime_hub.broadcast(
        "procurement_import",
        {
            "event": "clearance_analysis_completed",
            "analysis": analysis,
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )

    return {"data": analysis}


@router.post("/shipments/{shipment_id}/escalate")
async def escalate_shipment(
    shipment_id: str,
    payload: EscalationRequest,
    user: dict[str, Any] = Depends(require_procurement_write),
):
    shipment = get_procurement_shipment(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    current_status = str(shipment.get("status") or "").strip().lower()
    escalation_details = {
        "reason": payload.reason,
        "notify_regulatory": payload.notify_regulatory,
        "notify_executive_dashboard": payload.notify_executive_dashboard,
    }

    create_procurement_shipment_event(
        {
            "shipment_id": shipment_id,
            "from_status": current_status,
            "to_status": current_status,
            "reason": "escalated",
            "actor_id": user.get("sub"),
            "details": escalation_details,
        }
    )

    audit_event(
        "procurement_shipment_escalated",
        {
            "shipment_id": shipment_id,
            "shipment_ref": shipment.get("shipment_ref"),
            "supplier_name": shipment.get("supplier_name"),
            **escalation_details,
            "user_id": user.get("sub"),
        },
        event_class="workflow",
        subject_type="procurement_shipment",
        subject_id=shipment_id,
        actor_id=user.get("sub"),
        actor_role=(user.get("roles") or [None])[0],
    )

    alert_severity = "critical" if "breach" in payload.reason.lower() else "warning"
    alert_metadata = {
        "workflow": "procurement_import",
        "shipment_id": shipment_id,
        "shipment_ref": shipment.get("shipment_ref"),
        "supplier_name": shipment.get("supplier_name"),
        "reason": payload.reason,
        "notify_regulatory": payload.notify_regulatory,
        "notify_executive_dashboard": payload.notify_executive_dashboard,
        "actor_id": user.get("sub"),
    }
    create_alert(
        title=f"Procurement escalation: {shipment.get('shipment_ref')}",
        message=f"Shipment escalation raised for {shipment.get('supplier_name')} ({shipment.get('shipment_ref')}): {payload.reason}",
        severity=alert_severity,
        category="system",
        metadata=alert_metadata,
    )

    delivery = send_procurement_escalation_email(
        shipment=shipment,
        reason=payload.reason,
        actor_id=user.get("sub"),
        notify_regulatory=payload.notify_regulatory,
        notify_executive_dashboard=payload.notify_executive_dashboard,
    )

    await realtime_hub.broadcast(
        "procurement_import",
        {
            "event": "shipment_escalated",
            "shipment_id": shipment_id,
            "shipment_ref": shipment.get("shipment_ref"),
            "reason": payload.reason,
            "notify_regulatory": payload.notify_regulatory,
            "notify_executive_dashboard": payload.notify_executive_dashboard,
            "delivery": delivery,
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )

    return {
        "status": "escalated",
        "shipment_id": shipment_id,
        "reason": payload.reason,
        "delivery": delivery,
    }


@router.get("/events/poll")
async def poll_procurement_events(
    since_event_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(require_procurement_read),
):
    rows = list_procurement_events_feed(limit=limit, since_event_id=since_event_id)
    latest_event_id = rows[-1].get("id") if rows else since_event_id
    return {
        "data": rows,
        "count": len(rows),
        "latest_event_id": latest_event_id,
        "viewer": user.get("sub"),
    }


@router.get("/events/stream")
async def stream_procurement_events(
    request: Request,
    last_event_id: int | None = Query(default=None, ge=1),
    poll_interval_seconds: float = Query(default=3.0, ge=1.0, le=30.0),
    user: dict[str, Any] = Depends(require_procurement_read),
):
    async def generator():
        current_event_id = last_event_id
        while True:
            if await request.is_disconnected():
                break

            rows = list_procurement_events_feed(limit=100, since_event_id=current_event_id)
            if rows:
                for row in rows:
                    event_id = row.get("id")
                    if isinstance(event_id, int):
                        current_event_id = event_id
                    payload = {
                        "event": "shipment_event",
                        "data": row,
                        "viewer": user.get("sub"),
                    }
                    yield _sse_message(payload, event="shipment_event")
            else:
                yield _sse_message(
                    {
                        "event": "heartbeat",
                        "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                    },
                    event="heartbeat",
                )

            await asyncio.sleep(poll_interval_seconds)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(generator(), media_type="text/event-stream", headers=headers)


@router.get("/scorecard")
async def get_supplier_scorecard(user: dict[str, Any] = Depends(require_procurement_read)):
    rows = list_procurement_shipments(limit=500)
    analysis = run_clearance_analysis(rows)
    return {"data": analysis.get("supplier_scorecard", []), "viewer": user.get("sub")}


def _resolve_ws_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token.strip()
    auth = websocket.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _authorize_ws(websocket: WebSocket) -> dict[str, Any]:
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
    if not roles.intersection({"admin", "management", "ops", "procurement", "regulatory"}):
        await websocket.close(code=4403)
        raise RuntimeError("Insufficient privileges")
    return payload


@router.websocket("/ws")
async def procurement_ws(websocket: WebSocket):
    if not WEBSOCKET_ENABLED:
        await websocket.close(code=4403)
        return

    try:
        payload = await _authorize_ws(websocket)
    except RuntimeError:
        return

    channel = "procurement_import"
    await realtime_hub.connect(channel, websocket)
    await realtime_hub.broadcast(
        channel,
        {
            "event": "subscriber_joined",
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
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        await realtime_hub.disconnect(channel, websocket)
    except Exception as exc:
        logger.warning(f"procurement websocket error: {exc}")
        await realtime_hub.disconnect(channel, websocket)
