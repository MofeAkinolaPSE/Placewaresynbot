from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from src.workflow.chain_of_custody import record_custody_event, list_custody_events
from src.middleware import verify_jwt

router = APIRouter(prefix="/custody", tags=["custody"])


class CustodyEvent(BaseModel):
    shipment_id: str
    location: str
    temperature_c: float | None = None
    notes: str | None = None


@router.post("/record")
async def api_record_event(evt: CustodyEvent, request: Request, _u=Depends(lambda r: verify_jwt(r))):
    roles = set(getattr(request.state, "user", {}).get("roles") or [])
    if not roles.intersection({"ops", "qc", "logistics", "procurement"}):
        raise HTTPException(status_code=403, detail="Insufficient role to record custody event")
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return record_custody_event(evt.shipment_id, evt.location, evt.temperature_c, actor, evt.notes)


@router.get("/events/{shipment_id}")
async def api_list_events(shipment_id: str, _u=Depends(lambda r: verify_jwt(r))):
    return list_custody_events(shipment_id)
