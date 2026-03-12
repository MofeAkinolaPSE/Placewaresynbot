from __future__ import annotations
from typing import Dict, Any
from fastapi import HTTPException
from src.db import db


_EVENT_ORDER = {
    "dispatched": 1,
    "in_transit": 2,
    "delivered": 3,
    "signed": 4,
}


def _normalize_event(raw: str | None) -> str:
    token = str(raw or "").strip().lower().replace(" ", "_")
    aliases = {
        "dispatch": "dispatched",
        "picked_up": "dispatched",
        "en_route": "in_transit",
        "transit": "in_transit",
        "delivery": "delivered",
        "signed_off": "signed",
    }
    return aliases.get(token, token)


def _latest_event_type(shipment_id: str) -> str | None:
    resp = db.table("chain_of_custody_events").select("event_type,location,event_time").eq("shipment_id", shipment_id).order("event_time", desc=True).limit(1).execute()
    rows = resp.data or []
    if not rows:
        return None
    row = rows[0]
    return _normalize_event(row.get("event_type") or row.get("location"))


def _validate_transition(shipment_id: str, event_type: str) -> None:
    if event_type not in _EVENT_ORDER:
        return
    prev = _latest_event_type(shipment_id)
    if prev is None and event_type != "dispatched":
        raise HTTPException(status_code=400, detail="First custody event must be 'dispatched'")
    if prev is None:
        return
    prev_rank = _EVENT_ORDER.get(prev)
    next_rank = _EVENT_ORDER.get(event_type)
    if prev_rank is None or next_rank is None:
        return
    if next_rank < prev_rank:
        raise HTTPException(status_code=400, detail=f"Invalid custody transition: {prev} -> {event_type}")
    if next_rank - prev_rank > 1:
        raise HTTPException(status_code=400, detail=f"Missing intermediate custody state before '{event_type}'")


def record_custody_event(
    shipment_id: str,
    location: str,
    temperature_c: float | None = None,
    recorded_by: str | None = None,
    notes: str | None = None,
    event_type: str | None = None,
) -> Dict[str, Any]:
    normalized_event = _normalize_event(event_type or location)
    _validate_transition(shipment_id, normalized_event)

    payload = {
        "shipment_id": shipment_id,
        "location": location,
        "event_type": normalized_event,
        "temperature_c": temperature_c,
        "recorded_by": recorded_by,
        "notes": notes,
    }
    try:
        db.table("chain_of_custody_events").insert(payload).execute()
    except Exception:
        # Backward compatibility before 044 migration: retry without new columns.
        fallback_payload = {
            "shipment_id": shipment_id,
            "location": location,
            "temperature_c": temperature_c,
            "recorded_by": recorded_by,
            "notes": notes,
        }
        db.table("chain_of_custody_events").insert(fallback_payload).execute()
    return {"ok": True}


def sign_delivery(shipment_id: str, signer_name: str, actor: str | None = None, notes: str | None = None) -> Dict[str, Any]:
    signature_note = f"Signed by {signer_name}" if signer_name else "Signed"
    if notes:
        signature_note = f"{signature_note}. {notes}"
    return record_custody_event(
        shipment_id=shipment_id,
        location="signed",
        temperature_c=None,
        recorded_by=actor,
        notes=signature_note,
        event_type="signed",
    )


def list_custody_events(shipment_id: str):
    resp = db.table("chain_of_custody_events").select("*").eq("shipment_id", shipment_id).order("event_time", desc=False).execute()
    return resp.data or []
