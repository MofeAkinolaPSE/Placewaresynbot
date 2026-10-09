from fastapi import APIRouter, Request, HTTPException
from src.schemas.event_schema import EventPayload
from src.middleware import verify_jwt, require_role
from src.services.oeis import process_operational_event, build_event_trace

router = APIRouter()


@router.post("/events", status_code=201)
async def ingest_event(request: Request, payload: EventPayload):
    # Require authenticated staff/manager/admin to ingest events
    payload_auth = verify_jwt(request)
    roles = set(payload_auth.get("roles") or [])
    if not ("staff" in roles or "admin" in roles or "manager" in roles or "ops" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role to ingest events")
    try:
        actor = payload_auth.get("sub") or payload_auth.get("user_id")
        result = await process_operational_event(payload.dict(), actor_id=actor)
        return {
            "status": "accepted",
            "event_id": result.event_id,
            "version_hash": result.version_hash,
            "schema_valid": result.schema_valid,
            "schema_errors": result.schema_errors,
            "workflow_jobs": result.workflow_job_ids,
            "agent_runs": result.agent_runs,
            "kg_updates": result.kg_updates,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/events/{event_id}/trace")
def event_trace(request: Request, event_id: str):
    payload_auth = verify_jwt(request)
    roles = set(payload_auth.get("roles") or [])
    if not roles.intersection({"admin", "management", "ops", "finance", "crm", "compliance", "staff"}):
        raise HTTPException(status_code=403, detail="Insufficient role to view event trace")
    try:
        trace = build_event_trace(event_id)
        if not trace.get("event"):
            raise HTTPException(status_code=404, detail="Event trace not found")
        return trace
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
