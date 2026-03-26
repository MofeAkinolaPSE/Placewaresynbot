"""Digital Twin HTTP Router.

Provides REST endpoints for the Digital Twin state map, anomaly events, and
manual sync triggers.  All endpoints require at minimum ops-level access.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.db import audit_event
from src.middleware import verify_jwt
from src.services.digital_twin_service import (
    get_current_state_map,
    get_dependency_graph,
    get_open_anomalies,
    resolve_anomaly,
    run_twin_sync,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/twin", tags=["digital_twin"])

_ALLOWED_ROLES = {"admin", "management", "ops", "operations", "finance"}


def _require_ops_access(request: Request, user=Depends(verify_jwt)):
    user_ctx = getattr(request.state, "user", {}) or {}
    roles = set(user_ctx.get("roles") or [])
    if not roles.intersection(_ALLOWED_ROLES):
        raise HTTPException(status_code=403, detail="Insufficient role for twin access.")
    return user_ctx


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/state-map")
async def api_twin_state_map(user_ctx=Depends(_require_ops_access)):
    """Return the current health state of every system node."""
    nodes = get_current_state_map()
    return {"nodes": nodes, "count": len(nodes)}


@router.get("/anomalies")
async def api_twin_anomalies(
    limit: int = Query(50, ge=1, le=200),
    user_ctx=Depends(_require_ops_access),
):
    """Return open (unresolved) anomaly events ordered by detection time."""
    events = get_open_anomalies(limit=limit)
    return {"anomalies": events, "count": len(events)}


@router.get("/dependency-graph")
async def api_twin_dependency_graph(user_ctx=Depends(_require_ops_access)):
    """Return nodes and edges for the system dependency graph."""
    return get_dependency_graph()


@router.post("/sync")
async def api_twin_sync(request: Request, user_ctx=Depends(_require_ops_access)):
    """Manually trigger a full twin sync cycle."""
    actor_id = user_ctx.get("sub")
    result = run_twin_sync()
    audit_event(
        "twin_manual_sync",
        {"triggered_by": actor_id, "result": result},
        event_class="reliability",
        action="manual_sync",
        outcome="success",
        subject_type="twin",
        subject_id="system",
    )
    return result


@router.post("/anomalies/{anomaly_id}/resolve")
async def api_twin_resolve_anomaly(
    anomaly_id: str,
    request: Request,
    user_ctx=Depends(_require_ops_access),
):
    """Mark an anomaly event as resolved."""
    actor_id = user_ctx.get("sub")
    result = resolve_anomaly(anomaly_id)
    audit_event(
        "twin_anomaly_resolved",
        {"anomaly_id": anomaly_id, "resolved_by": actor_id},
        event_class="reliability",
        action="resolve_anomaly",
        outcome="success",
        subject_type="twin_anomaly",
        subject_id=anomaly_id,
    )
    return result
