"""Capability Discovery HTTP Router.

Provides REST endpoints for managing capability proposals, signals, and
running manual discovery cycles.  All endpoints require ops-level access.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.db import audit_event
from src.middleware import verify_jwt
from src.services.capability_engine import (
    get_active_proposals,
    get_recent_signals,
    record_signal,
    run_discovery_cycle,
    update_proposal_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/capability", tags=["capability_discovery"])

_ALLOWED_ROLES = {"admin", "management", "ops", "operations", "finance"}
_REVIEW_ROLES = {"admin", "management"}


def _require_ops_access(request: Request, user=Depends(verify_jwt)):
    user_ctx = getattr(request.state, "user", {}) or {}
    roles = set(user_ctx.get("roles") or [])
    if not roles.intersection(_ALLOWED_ROLES):
        raise HTTPException(status_code=403, detail="Insufficient role for capability access.")
    return user_ctx


def _require_review_access(request: Request, user=Depends(verify_jwt)):
    user_ctx = getattr(request.state, "user", {}) or {}
    roles = set(user_ctx.get("roles") or [])
    if not roles.intersection(_REVIEW_ROLES):
        raise HTTPException(status_code=403, detail="Only admin or management may review proposals.")
    return user_ctx


# ── Request models ──────────────────────────────────────────────────────────

class SignalRequest(BaseModel):
    signal_type: str
    description: str
    component: Optional[str] = None
    metadata: Optional[dict] = None


class ProposalStatusUpdate(BaseModel):
    status: str  # approved | rejected | implemented | deferred
    notes: Optional[str] = None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/proposals")
def api_list_proposals(
    limit: int = Query(50, ge=1, le=200),
    user_ctx=Depends(_require_ops_access),
):
    """Return active (proposed / approved) capability proposals."""
    proposals = get_active_proposals(limit=limit)
    return {"proposals": proposals, "count": len(proposals)}


@router.get("/signals")
def api_list_signals(
    limit: int = Query(100, ge=1, le=500),
    user_ctx=Depends(_require_ops_access),
):
    """Return recent capability signals ordered by last_seen_at."""
    signals = get_recent_signals(limit=limit)
    return {"signals": signals, "count": len(signals)}


@router.post("/signals")
def api_record_signal(
    payload: SignalRequest,
    request: Request,
    user_ctx=Depends(_require_ops_access),
):
    """Manually record a capability signal (e.g. a user-reported gap)."""
    actor_id = user_ctx.get("sub")
    result = record_signal(
        signal_type=payload.signal_type,
        description=payload.description,
        component=payload.component,
        metadata={"recorded_by": actor_id, **(payload.metadata or {})},
    )
    return result


@router.post("/discover")
def api_run_discovery(
    request: Request,
    user_ctx=Depends(_require_ops_access),
):
    """Manually trigger a capability discovery cycle."""
    actor_id = user_ctx.get("sub")
    result = run_discovery_cycle()
    audit_event(
        "capability_discovery_triggered",
        {"triggered_by": actor_id, "result": result},
        event_class="reliability",
        action="manual_discovery",
        outcome="success",
        subject_type="capability",
        subject_id="system",
    )
    return result


@router.patch("/proposals/{proposal_id}/status")
def api_update_proposal_status(
    proposal_id: str,
    payload: ProposalStatusUpdate,
    request: Request,
    user_ctx=Depends(_require_review_access),
):
    """Approve, reject, defer, or mark a proposal as implemented."""
    allowed_statuses = {"approved", "rejected", "implemented", "deferred"}
    if payload.status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(allowed_statuses))}",
        )
    reviewer = user_ctx.get("sub") or user_ctx.get("email", "unknown")
    result = update_proposal_status(
        proposal_id=proposal_id,
        new_status=payload.status,
        reviewer=reviewer,
        notes=payload.notes,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result
