from fastapi import APIRouter, HTTPException, Request
from src.schemas.schema_registry import DepartmentSchema
from src.middleware import verify_jwt, require_role
from typing import List, Dict, Any
from src.services.schema_registry_service import (
    list_schemas as service_list_schemas,
    get_schema as service_get_schema,
    upsert_schema as service_upsert_schema,
    validate_event_payload,
)

router = APIRouter()


@router.get("/schemas", response_model=List[Dict[str, Any]])
def list_schemas():
    return service_list_schemas()


@router.get("/schemas/{department}/{event_type}")
def get_schema(department: str, event_type: str):
    schema = service_get_schema(department, event_type)
    if schema:
        return schema
    raise HTTPException(status_code=404, detail="Schema not found")


@router.post("/schemas", status_code=201)
def create_schema(request: Request, payload: dict):
    # Require admin/manager to create schemas
    auth = verify_jwt(request)
    roles = set(auth.get("roles") or [])
    if not ("admin" in roles or "management" in roles or "manager" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role")
    # Validate payload against Pydantic
    try:
        ds = DepartmentSchema(**payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid schema: {e}")
    persisted = service_upsert_schema(ds.dict())
    return {"status": "ok", "schema": persisted}


@router.post("/schemas/validate")
def validate_event(payload: dict):
    # payload must include department and event_type to choose schema
    department = payload.get("department")
    event_type = payload.get("event_type")
    if not department or not event_type:
        raise HTTPException(status_code=400, detail="Missing department or event_type")
    schema = service_get_schema(department, event_type)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    errors = validate_event_payload(schema, payload.get("payload") or {})
    return {"valid": len(errors) == 0, "errors": errors}
