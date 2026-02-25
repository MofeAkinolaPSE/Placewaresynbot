from __future__ import annotations
from typing import Any, Dict
from src.db import supabase
from src.constants import TABLE_BATCHES, TABLE_AUDIT_LOGS


def lock_batch(batch_id: str, reason: str, actor: str | None = None) -> Dict[str, Any]:
    # insert a row into batch_status_locks
    payload = {
        "batch_id": batch_id,
        "locked": True,
        "lock_reason": reason,
        "created_by": actor,
    }
    supabase.table("batch_status_locks").insert(payload).execute()
    # audit
    supabase.table(TABLE_AUDIT_LOGS).insert({"event": "batch_locked", "batch_id": batch_id, "reason": reason, "actor": actor}).execute()
    return {"ok": True}


def unlock_batch(batch_id: str, actor: str | None = None) -> Dict[str, Any]:
    supabase.table("batch_status_locks").update({"locked": False}).eq("batch_id", batch_id).execute()
    supabase.table(TABLE_AUDIT_LOGS).insert({"event": "batch_unlocked", "batch_id": batch_id, "actor": actor}).execute()
    return {"ok": True}


def is_batch_locked(batch_id: str) -> bool:
    resp = supabase.table("batch_status_locks").select("locked").eq("batch_id", batch_id).order("created_at", desc=True).limit(1).execute()
    rows = resp.data or []
    if not rows:
        return False
    return bool(rows[0].get("locked"))
