from fastapi import APIRouter, HTTPException, Request
from src.middleware import verify_jwt
from src.services.schema_registry_service import list_schemas as list_registry_schemas, to_json_schema

router = APIRouter()

# Minimal JSON Schema payloads for form generation on the client.
# Keep these schemas small and focused on commonly-used fields.

INVENTORY_ITEM_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Inventory Item",
    "type": "object",
    "required": ["sku", "name"],
    "properties": {
        "sku": {"type": "string", "title": "SKU"},
        "name": {"type": "string", "title": "Name"},
        "description": {"type": "string", "title": "Description"},
        "unit": {"type": "string", "title": "Unit", "default": "each"},
        "reorder_threshold": {"type": "number", "title": "Reorder Threshold", "minimum": 0},
    },
}

INVENTORY_MOVEMENT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Inventory Movement",
    "type": "object",
    "required": ["item_id", "change"],
    "properties": {
        "item_id": {"type": "string", "title": "Item ID"},
        "change": {"type": "number", "title": "Quantity Change"},
        "movement_type": {"type": "string", "title": "Movement Type", "enum": ["purchase", "sale", "adjustment", "transfer"]},
        "source": {"type": ["string", "null"], "title": "Source Location"},
        "destination": {"type": ["string", "null"], "title": "Destination Location"},
        "created_by": {"type": ["string", "null"], "title": "Recorded By"},
    },
}

DOCUMENT_CREATE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Document Metadata",
    "type": "object",
    "required": ["title", "document_type"],
    "properties": {
        "title": {"type": "string", "title": "Title"},
        "document_type": {"type": "string", "title": "Type", "enum": ["policy", "invoice", "report", "other"]},
        "description": {"type": "string", "title": "Description"},
        "tags": {"type": "array", "items": {"type": "string"}, "title": "Tags"},
        "created_by": {"type": ["string", "null"], "title": "Created By"},
    },
}


AVAILABLE = {
    "inventory_item": INVENTORY_ITEM_SCHEMA,
    "inventory_movement": INVENTORY_MOVEMENT_SCHEMA,
    "document_create": DOCUMENT_CREATE_SCHEMA,
}


def _registry_available() -> dict[str, dict]:
    dynamic: dict[str, dict] = {}
    try:
        for schema in list_registry_schemas():
            dept = str(schema.get("department") or "").strip().lower()
            ev = str(schema.get("event_type") or "").strip().lower()
            if not dept or not ev:
                continue
            key = f"{dept}_{ev}"
            dynamic[key] = to_json_schema(schema)
    except Exception:
        return {}
    return dynamic


@router.get('/schemas')
def list_schemas(request: Request):
    verify_jwt(request)
    merged = {**AVAILABLE, **_registry_available()}
    return {"available": list(merged.keys())}


@router.get('/schemas/{name}')
def get_schema(name: str, request: Request):
    verify_jwt(request)
    merged = {**AVAILABLE, **_registry_available()}
    schema = merged.get(name)
    if not schema:
        raise HTTPException(status_code=404, detail='Schema not found')
    return schema
