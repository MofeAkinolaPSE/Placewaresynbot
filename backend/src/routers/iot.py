from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from src.middleware import verify_jwt
from src.db import supabase
from src.auth.device_keys import validate_device_key

router = APIRouter(prefix="/iot", tags=["iot"])


class SensorEvent(BaseModel):
    sensor_id: str
    timestamp: str
    temperature_c: float | None = None
    shipment_id: str | None = None
    location: str | None = None


@router.post("/ingest")
async def api_ingest_event(evt: SensorEvent, request: Request):
    """Accept sensor events authenticated by either a user JWT or an X-Device-Key header.

    Priority: JWT (user context) if present and valid. Otherwise validate `X-Device-Key` header.
    """
    actor = None
    # Try JWT first
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        try:
            _ = verify_jwt(request)
            actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
        except Exception:
            actor = None

    # If no valid JWT, try device key
    if not actor:
        dev_key = request.headers.get("X-Device-Key") or request.headers.get("x-device-key")
        if not dev_key:
            raise HTTPException(status_code=401, detail="Missing authentication (Authorization or X-Device-Key)")
        dv = validate_device_key(dev_key)
        if not dv:
            raise HTTPException(status_code=401, detail="Invalid device key")
        # attach device identity
        actor = dv.get("device_id")
    payload = {
        "sensor_id": evt.sensor_id,
        "timestamp": evt.timestamp,
        "temperature_c": evt.temperature_c,
        "shipment_id": evt.shipment_id,
        "location": evt.location,
        "recorded_by": actor,
    }
    supabase.table("sensor_events").insert(payload).execute()
    # If shipment_id present, also record in chain_of_custody for traceability
    if evt.shipment_id:
        supabase.table("chain_of_custody_events").insert({"shipment_id": evt.shipment_id, "event_time": evt.timestamp, "temperature_c": evt.temperature_c, "location": evt.location, "recorded_by": actor}).execute()
    return {"ok": True}
