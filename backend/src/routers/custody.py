from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from src.workflow.chain_of_custody import record_custody_event, list_custody_events, sign_delivery
from src.middleware import verify_jwt, require_role

router = APIRouter(prefix="/custody", tags=["custody"])


class CustodyEvent(BaseModel):
    shipment_id: str
    location: str
    event_type: str | None = None
    temperature_c: float | None = None
    notes: str | None = None


@router.post("/record")
async def api_record_event(evt: CustodyEvent, request: Request, _u=Depends(verify_jwt)):
    roles = set(getattr(request.state, "user", {}).get("roles") or [])
    if not roles.intersection({"ops", "qc", "logistics", "procurement"}):
        raise HTTPException(status_code=403, detail="Insufficient role to record custody event")
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return record_custody_event(evt.shipment_id, evt.location, evt.temperature_c, actor, evt.notes, evt.event_type)


class CustodySign(BaseModel):
    signer_name: str
    notes: str | None = None


@router.post("/sign/{shipment_id}")
async def api_sign_delivery(shipment_id: str, payload: CustodySign, request: Request, _u=Depends(verify_jwt)):
    roles = set(getattr(request.state, "user", {}).get("roles") or [])
    if not roles.intersection({"ops", "logistics", "sales", "admin"}):
        raise HTTPException(status_code=403, detail="Insufficient role to sign custody delivery")
    actor = getattr(request.state, "user", {}).get("sub") if hasattr(request.state, "user") else None
    return sign_delivery(shipment_id, payload.signer_name, actor, payload.notes)


@router.get("/events/{shipment_id}")
async def api_list_events(shipment_id: str, _u=Depends(verify_jwt)):
    return list_custody_events(shipment_id)
