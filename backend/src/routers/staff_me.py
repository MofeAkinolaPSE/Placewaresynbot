"""The signed-in person's own onboarding state (welcome tour) - docs/ACE-Guided-Onboarding-Engineering-Guide.md.

GET  /staff/me/tour   -> {"tour_state": {...} | null}
PATCH /staff/me/tour  -> merges completed / skipped / current_step into the caller's own tour_state

The user comes from the token, never from the request body, so nobody can read or change someone else's tour.
(A path under /staff/me/... - not /staff/me - so it cannot be taken for GET /staff/{staff_id}.)
"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from src.fin.db import q1, tx
from src.middleware import verify_jwt

router = APIRouter(prefix="/staff/me", tags=["staff"])

_FIELDS = {"completed": bool, "skipped": bool, "current_step": int}


def _uid(request: Request) -> str:
    sub = str(verify_jwt(request).get("sub") or "")
    if not sub:
        raise HTTPException(401, "Sign in again")
    return sub


@router.get("/tour")
def get_tour(uid: str = Depends(_uid)) -> Dict[str, Any]:
    with tx() as conn:
        row = q1(conn, "SELECT tour_state FROM placeware_users WHERE id::text=%s", (uid,))
    if row is None:
        raise HTTPException(404, "Account not found")
    return {"tour_state": row["tour_state"]}


@router.patch("/tour")
def update_tour(data: Dict[str, Any] = Body(...), uid: str = Depends(_uid)) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    for k, kind in _FIELDS.items():
        if k in data and data[k] is not None:
            try:
                patch[k] = kind(data[k])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} must be {kind.__name__}")
    if not patch:
        raise HTTPException(400, "Nothing to update")
    with tx() as conn:
        row = q1(conn, """UPDATE placeware_users SET tour_state = COALESCE(tour_state, '{}'::jsonb) || %s::jsonb
                          WHERE id::text=%s RETURNING tour_state""", (json.dumps(patch), uid))
    if row is None:
        raise HTTPException(404, "Account not found")
    return {"tour_state": row["tour_state"]}
