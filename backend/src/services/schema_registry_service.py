from __future__ import annotations

import json
import os
from typing import Any

from src.db import db

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "department_schemas.json")
SCHEMA_TABLE = "department_schemas"


def _ensure_schema_dir() -> None:
    parent = os.path.dirname(SCHEMA_FILE)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _load_file_schemas() -> list[dict[str, Any]]:
    if not os.path.exists(SCHEMA_FILE):
        return []
    try:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
            return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _save_file_schemas(rows: list[dict[str, Any]]) -> None:
    _ensure_schema_dir()
    with open(SCHEMA_FILE, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)


def list_schemas() -> list[dict[str, Any]]:
    try:
        resp = (
            db.table(SCHEMA_TABLE)
            .select("*")
            .eq("active", True)
            .order("updated_at", desc=True)
            .limit(500)
            .execute()
        )
        rows = resp.data or []
        if rows:
            return rows
    except Exception:
        pass
    return _load_file_schemas()


def get_schema(department: str, event_type: str) -> dict[str, Any] | None:
    dept = (department or "").strip().lower()
    et = (event_type or "").strip().lower()
    if not dept or not et:
        return None

    try:
        resp = (
            db.table(SCHEMA_TABLE)
            .select("*")
            .eq("department", dept)
            .eq("event_type", et)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if rows:
            return rows[0]
    except Exception:
        pass

    for row in _load_file_schemas():
        if str(row.get("department", "")).lower() == dept and str(row.get("event_type", "")).lower() == et:
            return row
    return None


def upsert_schema(schema: dict[str, Any]) -> dict[str, Any]:
    payload = dict(schema)
    payload["department"] = str(payload.get("department", "")).strip().lower()
    payload["event_type"] = str(payload.get("event_type", "")).strip().lower()

    existing = get_schema(payload["department"], payload["event_type"])
    next_version = int(existing.get("version", 1)) + 1 if existing else int(payload.get("version", 1) or 1)
    payload["version"] = next_version

    # DB-first write
    try:
        if existing and existing.get("id"):
            resp = (
                db.table(SCHEMA_TABLE)
                .update(payload)
                .eq("id", existing["id"])
                .execute()
            )
            rows = resp.data or []
            if rows:
                return rows[0]
        else:
            resp = db.table(SCHEMA_TABLE).insert(payload).execute()
            rows = resp.data or []
            if rows:
                return rows[0]
    except Exception:
        pass

    # Fallback file write
    rows = _load_file_schemas()
    replaced = False
    for idx, row in enumerate(rows):
        if str(row.get("department", "")).lower() == payload["department"] and str(row.get("event_type", "")).lower() == payload["event_type"]:
            rows[idx] = payload
            replaced = True
            break
    if not replaced:
        rows.append(payload)
    _save_file_schemas(rows)
    return payload


def validate_event_payload(schema: dict[str, Any], payload_data: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    fields = schema.get("fields") or []

    for field in fields:
        name = field.get("field_name")
        dtype = field.get("data_type")
        required = bool(field.get("required"))
        rules = field.get("validation_rules") or {}

        if not name:
            continue

        depends_on = rules.get("depends_on")
        required_if = rules.get("required_if")

        if depends_on and payload_data.get(depends_on) in (None, "", []):
            # Skip dependent field checks until parent exists
            continue

        if required_if and isinstance(required_if, dict):
            req_field = required_if.get("field")
            req_equals = required_if.get("equals")
            if payload_data.get(req_field) == req_equals:
                required = True

        if required and name not in payload_data:
            errors.append({"field": name, "error": "missing"})
            continue

        if name not in payload_data:
            continue

        value = payload_data.get(name)
        if dtype == "string" and not isinstance(value, str):
            errors.append({"field": name, "error": "expected string"})
        elif dtype == "number" and not isinstance(value, (int, float)):
            errors.append({"field": name, "error": "expected number"})
        elif dtype == "boolean" and not isinstance(value, bool):
            errors.append({"field": name, "error": "expected boolean"})
        elif dtype == "object" and not isinstance(value, dict):
            errors.append({"field": name, "error": "expected object"})
        elif dtype == "array" and not isinstance(value, list):
            errors.append({"field": name, "error": "expected array"})

        enum_values = rules.get("enum")
        if enum_values and value not in enum_values:
            errors.append({"field": name, "error": "value not in enum"})

        options_map = rules.get("options_map")
        if depends_on and isinstance(options_map, dict):
            parent_value = payload_data.get(depends_on)
            allowed = options_map.get(parent_value)
            if isinstance(allowed, list) and value not in allowed:
                errors.append({"field": name, "error": "invalid dependent option"})

    return errors


def to_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []

    for field in schema.get("fields") or []:
        name = field.get("field_name")
        dtype = field.get("data_type") or "string"
        rules = field.get("validation_rules") or {}
        if not name:
            continue

        prop: dict[str, Any] = {
            "type": dtype,
            "title": name.replace("_", " ").title(),
        }

        if "enum" in rules and isinstance(rules["enum"], list):
            prop["enum"] = rules["enum"]

        if "min" in rules:
            prop["minimum"] = rules["min"]
        if "max" in rules:
            prop["maximum"] = rules["max"]

        depends_on = rules.get("depends_on")
        if depends_on:
            prop["x-dependsOn"] = depends_on
        if "options_map" in rules:
            prop["x-optionsMap"] = rules["options_map"]

        props[name] = prop

        if field.get("required"):
            required.append(name)

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{schema.get('department', '').title()} - {schema.get('event_type', '').title()}",
        "type": "object",
        "properties": props,
        "required": required,
    }
