from __future__ import annotations
import hashlib
import hmac
from typing import Optional, Dict
from src.db import db


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_device_key(raw_key: str) -> Optional[Dict[str, str]]:
    """Validate a raw device key string.

    Returns a dict with `device_id` when valid, otherwise None.
    The stored table contains SHA256(key) in `key_hash` (avoids storing plain secrets).
    """
    if not raw_key:
        return None
    try:
        kh = _sha256_hex(raw_key)
        resp = db.table("device_keys").select("device_id,key_hash,active").eq("key_hash", kh).eq("active", True).limit(1).execute()
        rows = resp.data or []
        if not rows:
            return None
        r = rows[0]
        # defensive compare though we queried by hash
        if not hmac.compare_digest(str(r.get("key_hash") or ""), kh):
            return None
        return {"device_id": str(r.get("device_id") or "")}
    except Exception:
        return None
