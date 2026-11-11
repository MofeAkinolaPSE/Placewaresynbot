"""Branches (Lagos / Abuja): what the branch switcher shows, and which branches each login may work in.

    GET /branches/me              the branch this request runs in, the person's home branch and their choices
    GET /branches                 every branch (names for labels)
    PUT /users/{id}/branches      admin: set a login's home branch and any extra branches (reason required)

See src/branch.py for how a request's branch is chosen and enforced.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import branch
from src.middleware import verify_jwt

logger = logging.getLogger(__name__)
router = APIRouter(tags=["branches"])


@router.get("/branches/me")
def my_branches(request: Request):
    payload = verify_jwt(request)
    return branch.describe(str(payload.get("sub") or ""), list(payload.get("roles") or []))


@router.get("/branches")
def list_branches(request: Request):
    verify_jwt(request)
    return {"branches": branch.all_branches(fresh=True)}


class UserBranchesUpdate(BaseModel):
    home_entity_id: str
    extra_entity_ids: List[str] = []
    approval_reason: Optional[str] = None


@router.put("/users/{user_id}/branches")
def set_user_branches(request: Request, user_id: str, body: UserBranchesUpdate):
    payload = verify_jwt(request)
    if "admin" not in [str(r).lower() for r in (payload.get("roles") or [])]:
        raise HTTPException(status_code=403, detail="Only an admin can change where someone works")
    if not (body.approval_reason or "").strip():
        raise HTTPException(status_code=400, detail="Give a reason for the change")
    ids = {b["id"] for b in branch.all_branches(fresh=True)}
    if body.home_entity_id not in ids:
        raise HTTPException(status_code=400, detail="Unknown home branch")
    extra = sorted({e for e in body.extra_entity_ids if e != body.home_entity_id})
    if any(e not in ids for e in extra):
        raise HTTPException(status_code=400, detail="Unknown branch")
    from src.fin.db import q1, tx
    with branch.unscoped(), tx() as conn:
        before = q1(conn, """SELECT home_entity_id::text AS home, extra_entity_ids::text[] AS extra
                             FROM placeware_users WHERE id::text=%s""", (user_id,))
        if not before:
            raise HTTPException(status_code=404, detail="User not found")
        q1(conn, """UPDATE placeware_users SET home_entity_id=%s::uuid, extra_entity_ids=%s::uuid[], updated_at=now()
                    WHERE id::text=%s RETURNING id""", (body.home_entity_id, extra, user_id))
    branch.forget_user(user_id)
    try:
        from src.db import audit_event
        audit_event("user_branches_changed",
                    {"admin": payload.get("sub"), "target_user_id": user_id, "from": before,
                     "to": {"home": body.home_entity_id, "extra": extra}, "approval_reason": body.approval_reason},
                    actor_id=payload.get("sub"), action="admin_change_user_branches", outcome="success",
                    reason_code="access_change", subject_type="user", subject_id=user_id,
                    approval_reason=body.approval_reason,
                    attestation_text="I attest this access change is authorized.")
    except Exception as exc:  # the change stands; the audit trail is best-effort here as elsewhere
        logger.warning("audit of branch change failed: %s", exc)
    return {"id": user_id, "home_entity_id": body.home_entity_id, "extra_entity_ids": extra,
            "previous": before}
