from __future__ import annotations
from typing import Dict, Any
from src.db import supabase


def record_custody_event(shipment_id: str, location: str, temperature_c: float | None = None, recorded_by: str | None = None, notes: str | None = None) -> Dict[str, Any]:
    payload = {
        "shipment_id": shipment_id,
        "location": location,
        "temperature_c": temperature_c,
        "recorded_by": recorded_by,
        "notes": notes,
    }
    supabase.table("chain_of_custody_events").insert(payload).execute()
    return {"ok": True}


def list_custody_events(shipment_id: str):
    resp = supabase.table("chain_of_custody_events").select("*").eq("shipment_id", shipment_id).order("event_time", desc=False).execute()
    return resp.data or []
