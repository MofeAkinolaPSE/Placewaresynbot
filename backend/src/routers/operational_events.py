from fastapi import APIRouter, Request, HTTPException
from src.schemas.event_schema import EventPayload
from typing import Dict, Any
import json
import hashlib
import datetime as dt
import os
from src.middleware import verify_jwt

router = APIRouter()

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")


def _ensure_ledger_file():
    parent = os.path.dirname(LEDGER_PATH)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    if not os.path.exists(LEDGER_PATH):
        open(LEDGER_PATH, "a", encoding="utf-8").close()


def _compute_version_hash(event: Dict[str, Any]) -> str:
    # compute stable sha256 over canonical JSON
    clone = dict(event)
    clone.pop("version_hash", None)
    serialized = json.dumps(clone, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _persist_event(event: Dict[str, Any]) -> None:
    _ensure_ledger_file()
    with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


@router.post("/events", status_code=201)
async def ingest_event(request: Request, payload: EventPayload):
    # Require authenticated staff/manager/admin to ingest events
    payload_auth = verify_jwt(request)
    roles = set(payload_auth.get("roles") or [])
    if not ("staff" in roles or "admin" in roles or "manager" in roles or "ops" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role to ingest events")
    try:
        event_dict = payload.dict()
        # set timestamp
        if not event_dict.get("timestamp"):
            event_dict["timestamp"] = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        # compute version hash
        vh = _compute_version_hash(event_dict)
        event_dict["version_hash"] = vh
        # increment version if provided
        event_dict.setdefault("version", 1)
        # Persist to local JSONL ledger for development; replace with DB in production.
        _persist_event(event_dict)
        # Audit event (best-effort)
        try:
            from src.db import audit_event

            actor = payload_auth.get("sub") or payload_auth.get("user_id")
            audit_event(
                "operational_event_ingested",
                {"department": event_dict.get("department"), "event_type": event_dict.get("event_type")},
                actor_id=actor,
                event_class="operational_event",
                action="ingest",
                outcome="accepted",
                subject_type="event",
                subject_id=event_dict.get("version_hash"),
            )
        except Exception:
            pass
        # TODO: publish to event bus, trigger workflow engine and agents (placeholders)
        return {"status": "accepted", "version_hash": vh}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
