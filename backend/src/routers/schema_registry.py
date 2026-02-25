from fastapi import APIRouter, HTTPException, Request
from src.schemas.schema_registry import DepartmentSchema
from src.middleware import verify_jwt
from typing import List, Dict, Any
import os, json

router = APIRouter()

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "department_schemas.json")


def _load_schemas() -> List[Dict[str, Any]]:
    if not os.path.exists(SCHEMA_FILE):
        return []
    try:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _write_schemas(schemas: List[Dict[str, Any]]):
    parent = os.path.dirname(SCHEMA_FILE)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(SCHEMA_FILE, "w", encoding="utf-8") as fh:
        json.dump(schemas, fh, indent=2)


@router.get("/schemas", response_model=List[Dict[str, Any]])
async def list_schemas():
    return _load_schemas()


@router.get("/schemas/{department}/{event_type}")
async def get_schema(department: str, event_type: str):
    schemas = _load_schemas()
    for s in schemas:
        if s.get("department") == department and s.get("event_type") == event_type:
            return s
    raise HTTPException(status_code=404, detail="Schema not found")


@router.post("/schemas", status_code=201)
async def create_schema(request: Request, payload: dict):
    # Require admin/manager to create schemas
    verify_jwt(request, required_role="admin")
    # Validate payload against Pydantic
    try:
        ds = DepartmentSchema(**payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid schema: {e}")
    schemas = _load_schemas()
    # upsert by department+event_type
    updated = False
    for i, s in enumerate(schemas):
        if s.get("department") == ds.department and s.get("event_type") == ds.event_type:
            ds.version = int(s.get("version", 1)) + 1
            schemas[i] = ds.dict()
            updated = True
            break
    if not updated:
        schemas.append(ds.dict())
    _write_schemas(schemas)
    return {"status": "ok", "schema": ds.dict()}


@router.post("/schemas/validate")
async def validate_event(payload: dict):
    # payload must include department and event_type to choose schema
    department = payload.get("department")
    event_type = payload.get("event_type")
    if not department or not event_type:
        raise HTTPException(status_code=400, detail="Missing department or event_type")
    schemas = _load_schemas()
    schema = None
    for s in schemas:
        if s.get("department") == department and s.get("event_type") == event_type:
            schema = s
            break
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    # perform simple validation: required fields present and basic type matching
    errors = []
    payload_data = payload.get("payload") or {}
    for f in schema.get("fields", []):
        name = f.get("field_name")
        dtype = f.get("data_type")
        required = f.get("required")
        if required and name not in payload_data:
            errors.append({"field": name, "error": "missing"})
            continue
        if name in payload_data and dtype:
            val = payload_data.get(name)
            if dtype == "string" and not isinstance(val, str):
                errors.append({"field": name, "error": "expected string"})
            if dtype == "number" and not isinstance(val, (int, float)):
                errors.append({"field": name, "error": "expected number"})
            if dtype == "boolean" and not isinstance(val, bool):
                errors.append({"field": name, "error": "expected boolean"})
            if dtype == "object" and not isinstance(val, dict):
                errors.append({"field": name, "error": "expected object"})
            if dtype == "array" and not isinstance(val, list):
                errors.append({"field": name, "error": "expected array"})
    return {"valid": len(errors) == 0, "errors": errors}
