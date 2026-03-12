from __future__ import annotations
from typing import Any, Dict, Iterable
from fastapi import HTTPException
from src.db import db
from src.constants import TABLE_AUDIT_LOGS


def lock_batch(batch_id: str, reason: str, actor: str | None = None) -> Dict[str, Any]:
    # insert a row into batch_status_locks
    payload = {
        "batch_id": batch_id,
        "locked": True,
        "lock_reason": reason,
        "created_by": actor,
    }
    db.table("batch_status_locks").insert(payload).execute()
    # audit
    db.table(TABLE_AUDIT_LOGS).insert({"event": "batch_locked", "batch_id": batch_id, "reason": reason, "actor": actor}).execute()
    return {"ok": True}


def unlock_batch(batch_id: str, actor: str | None = None) -> Dict[str, Any]:
    db.table("batch_status_locks").update({"locked": False}).eq("batch_id", batch_id).execute()
    db.table(TABLE_AUDIT_LOGS).insert({"event": "batch_unlocked", "batch_id": batch_id, "actor": actor}).execute()
    return {"ok": True}


def is_batch_locked(batch_id: str) -> bool:
    resp = db.table("batch_status_locks").select("locked").eq("batch_id", batch_id).order("created_at", desc=True).limit(1).execute()
    rows = resp.data or []
    if not rows:
        return False
    return bool(rows[0].get("locked"))


def auto_release_batch(batch_id: str, actor: str | None = None) -> Dict[str, Any]:
    """Auto-unlock batch if it was locked for compliance/NAFDAC hold reasons."""
    resp = db.table("batch_status_locks").select("locked,lock_reason").eq("batch_id", batch_id).order("created_at", desc=True).limit(1).execute()
    rows = resp.data or []
    if not rows:
        return {"ok": False, "error": "lock_record_not_found", "batch_id": batch_id}

    latest = rows[0]
    if not bool(latest.get("locked")):
        return {"ok": True, "batch_id": batch_id, "already_unlocked": True}

    reason = str(latest.get("lock_reason") or "").lower()
    releasable = any(token in reason for token in ("nafdac", "compliance", "pending"))
    if not releasable:
        return {"ok": False, "batch_id": batch_id, "error": "not_releasable_reason", "lock_reason": latest.get("lock_reason")}

    return unlock_batch(batch_id, actor)


def enforce_no_locked_batches(batch_ids: Iterable[str]) -> None:
    """Raise 403 if any given batch id is currently locked."""
    for batch_id in batch_ids:
        if batch_id and is_batch_locked(str(batch_id)):
            raise HTTPException(status_code=403, detail=f"Batch '{batch_id}' is locked for compliance review")
