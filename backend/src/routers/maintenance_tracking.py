from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.db import db
from src.middleware import verify_jwt
from src.services.maintenance_service import (
    create_incident,
    detect_finance_blank_dashboard,
    get_open_incidents,
    get_overdue_maintenance_tasks,
    record_remediation,
    resolve_incident,
    run_blank_dashboard_playbook,
)
from src.constants import TABLE_MAINTENANCE_TASKS


router = APIRouter(prefix="/maintenance", tags=["maintenance"])


def _require_ops_access(request: Request) -> Dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {"admin", "management", "ops", "finance"}
    if roles.intersection(allowed):
        return payload
    raise HTTPException(status_code=403, detail="Insufficient privileges for maintenance endpoints")


class CreateTaskPayload(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: Optional[str] = None
    task_type: str = "preventive_maintenance"
    severity: str = "medium"
    due_at: Optional[str] = None
    assigned_to: Optional[str] = None
    asset_id: Optional[str] = None


class CompleteTaskPayload(BaseModel):
    completion_notes: Optional[str] = None


class ResolveIncidentPayload(BaseModel):
    resolution_note: Optional[str] = None


@router.get("/incidents/open")
def list_open_incidents(
    limit: int = 50,
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    return {"data": get_open_incidents(limit=max(1, min(limit, 500)))}


@router.get("/tasks/overdue")
def list_overdue_tasks(
    limit: int = 100,
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    return {"data": get_overdue_maintenance_tasks(limit=max(1, min(limit, 500)))}


@router.get("/diagnostics/finance-dashboard")
def finance_dashboard_diagnostics(
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    diagnostics = detect_finance_blank_dashboard()
    return {"data": diagnostics}


@router.post("/incidents/finance-dashboard")
def open_finance_dashboard_incident(
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    diagnostics = detect_finance_blank_dashboard()
    incident = create_incident(
        component="finance_dashboard",
        severity=diagnostics.get("severity", "medium"),
        summary=diagnostics.get("summary", "Finance dashboard incident detected"),
        details={"diagnostics": diagnostics},
    )
    return {"data": incident}


@router.post("/incidents/{incident_id}/run-playbook")
def run_incident_playbook(
    incident_id: str,
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    result = run_blank_dashboard_playbook(incident_id=incident_id)
    return {"data": result}


@router.post("/incidents/{incident_id}/resolve")
def resolve_open_incident(
    incident_id: str,
    payload: ResolveIncidentPayload,
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    resolved = resolve_incident(
        incident_id=incident_id,
        resolution_note=payload.resolution_note or "resolved via maintenance endpoint",
    )
    return {"data": resolved}


@router.post("/tasks")
def create_maintenance_task(
    payload: CreateTaskPayload,
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    row = {
        "title": payload.title,
        "description": payload.description,
        "task_type": payload.task_type,
        "severity": payload.severity,
        "due_at": payload.due_at,
        "assigned_to": payload.assigned_to,
        "asset_id": payload.asset_id,
        "status": "scheduled",
    }
    data = db.table(TABLE_MAINTENANCE_TASKS).insert(row).execute().data or []
    return {"data": (data[0] if data else row)}


@router.post("/tasks/{task_id}/complete")
def complete_maintenance_task(
    task_id: str,
    payload: CompleteTaskPayload,
    user: Dict[str, Any] = Depends(_require_ops_access),
):
    updated_rows = (
        db.table(TABLE_MAINTENANCE_TASKS)
        .update(
            {
                "status": "completed",
                "completed_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                "completion_notes": payload.completion_notes,
            }
        )
        .eq("id", task_id)
        .execute()
        .data
        or []
    )

    if not updated_rows:
        raise HTTPException(status_code=404, detail="Maintenance task not found")

    record_remediation(
        incident_id=None,
        action_name="maintenance_task_completed",
        outcome="success",
        notes=f"Task {task_id} completed",
        payload={"task_id": task_id},
    )

    return {"data": updated_rows[0]}
