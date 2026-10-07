"""
Calendar and Tasks API Router
Implements Milestone 6: Calendar & Task Manager
Extended: Pharma Logistics Calendar (Migration 081)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.middleware import verify_jwt
from pydantic import BaseModel, Field

from src.db import db
from src.services.realtime import realtime_hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])
tasks_router = APIRouter(prefix="/tasks", tags=["Tasks"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CalendarEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    event_type: str = Field(default="meeting")
    start_time: str
    end_time: Optional[str] = None
    all_day: bool = False
    location: Optional[str] = None
    attendees: Optional[List[dict]] = None
    metadata: Optional[dict] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    all_day: Optional[bool] = None
    location: Optional[str] = None
    attendees: Optional[List[dict]] = None
    metadata: Optional[dict] = None


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    status: str = Field(default="pending")
    priority: str = Field(default="medium")
    due_date: Optional[str] = None
    reminder_at: Optional[str] = None
    assigned_to: Optional[str] = None
    source: str = Field(default="manual")
    source_ref: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[dict] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    reminder_at: Optional[str] = None
    assigned_to: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Calendar Endpoints
# ---------------------------------------------------------------------------

@router.get("/events")
async def list_calendar_events(
    month: Optional[str] = Query(None, description="YYYY-MM format to filter by month"),
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user=Depends(verify_jwt),
):
    """List calendar events, optionally filtered by month or type."""
    try:
        query = db.table("placeware_calendar_events").select("*")
        
        if month:
            # Filter by month (start_time starts with YYYY-MM)
            start_of_month = f"{month}-01T00:00:00"
            # Calculate end of month
            year, mon = int(month[:4]), int(month[5:7])
            if mon == 12:
                end_of_month = f"{year + 1}-01-01T00:00:00"
            else:
                end_of_month = f"{year}-{mon + 1:02d}-01T00:00:00"
            query = query.gte("start_time", start_of_month).lt("start_time", end_of_month)
        
        if event_type:
            query = query.eq("event_type", event_type)
        
        result = query.order("start_time", desc=False).limit(limit).execute()
        events = result.data if hasattr(result, 'data') else result
        
        return {"events": events or [], "count": len(events or [])}
    except Exception as e:
        logger.error(f"Failed to list calendar events: {e}")
        return {"events": [], "count": 0}


@router.post("/events")
async def create_calendar_event(payload: CalendarEventCreate, user=Depends(verify_jwt)):
    """Create a new calendar event."""
    try:
        data = {
            "title": payload.title,
            "description": payload.description,
            "event_type": payload.event_type,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
            "all_day": payload.all_day,
            "location": payload.location,
            "attendees": json.dumps(payload.attendees or []),
            "metadata": json.dumps(payload.metadata or {}),
        }
        if user.get("sub") and len(str(user["sub"])) == 36:
            data["created_by"] = user["sub"]
        result = db.table("placeware_calendar_events").insert(data).execute()
        inserted = result.data[0] if hasattr(result, 'data') and result.data else data

        await realtime_hub.broadcast("calendar_tasks", {
            "event": "calendar_event_created",
            "id": inserted.get("id") if isinstance(inserted, dict) else None,
            "event_type": payload.event_type,
        })
        
        return {"data": inserted, "status": "created"}
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/events/{event_id}")
async def update_calendar_event(event_id: str, payload: CalendarEventUpdate, user=Depends(verify_jwt)):
    """Update an existing calendar event."""
    try:
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        result = db.table("placeware_calendar_events").update(data).eq("id", event_id).execute()
        updated = result.data[0] if hasattr(result, 'data') and result.data else data

        await realtime_hub.broadcast("calendar_tasks", {
            "event": "calendar_event_updated",
            "id": event_id,
        })
        
        return {"data": updated, "status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update calendar event {event_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/events/{event_id}")
async def delete_calendar_event(event_id: str, user=Depends(verify_jwt)):
    """Delete a calendar event."""
    try:
        db.table("placeware_calendar_events").delete().eq("id", event_id).execute()
        await realtime_hub.broadcast("calendar_tasks", {
            "event": "calendar_event_deleted",
            "id": event_id,
        })
        return {"status": "deleted", "id": event_id}
    except Exception as e:
        logger.error(f"Failed to delete calendar event {event_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Pharma Logistics Alerts Endpoint
# ---------------------------------------------------------------------------

_LOGISTICS_TYPES = {"inbound_inventory", "regional_dispatch", "warehouse_audit", "qc_inspection"}

LOGISTICS_ALERT_WINDOW_DAYS = 30


@router.get("/logistics/alerts")
async def get_logistics_alerts(window_days: int = Query(30, ge=1, le=180), user=Depends(verify_jwt)):
    """
    Return batches/events with expiry dates within the alert window.
    Scans metadata.batch_expiry on all logistics calendar events that start
    within [now, now + window_days] and returns those whose batch expires soon.
    """
    try:
        now = datetime.utcnow()
        cutoff = now + timedelta(days=window_days)

        result = (
            db.table("placeware_calendar_events")
            .select("id, title, event_type, start_time, metadata")
            .gte("start_time", now.isoformat())
            .lte("start_time", cutoff.isoformat())
            .execute()
        )

        events = result.data or []
        alerts = []

        for ev in events:
            raw_meta = ev.get("metadata") or {}
            if isinstance(raw_meta, str):
                try:
                    raw_meta = json.loads(raw_meta)
                except Exception:
                    raw_meta = {}

            expiry_str = raw_meta.get("batch_expiry") or raw_meta.get("expiry_date")
            if not expiry_str:
                continue

            try:
                expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", ""))
                days_until = (expiry_dt.date() - now.date()).days
                if 0 <= days_until <= window_days:
                    alerts.append({
                        "event_id": ev.get("id"),
                        "title": ev.get("title"),
                        "event_type": ev.get("event_type"),
                        "batch_id": raw_meta.get("batch_id"),
                        "product_name": raw_meta.get("product_name"),
                        "expiry_date": expiry_str,
                        "days_until_expiry": days_until,
                        "is_cold_chain": raw_meta.get("is_cold_chain", False),
                        "is_nafdac_regulated": raw_meta.get("is_nafdac_regulated", False),
                    })
            except (ValueError, TypeError):
                continue

        alerts.sort(key=lambda x: x["days_until_expiry"])
        return {"alerts": alerts, "total": len(alerts), "window_days": window_days}
    except Exception as e:
        logger.error(f"Failed to get logistics alerts: {e}")
        return {"alerts": [], "total": 0, "window_days": window_days}


# ---------------------------------------------------------------------------
# Tasks Endpoints
# ---------------------------------------------------------------------------

@tasks_router.get("")
async def list_tasks(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user=Depends(verify_jwt),
):
    """List tasks, optionally filtered by status, priority, or assignee."""
    try:
        query = db.table("placeware_tasks").select("*")
        
        if status:
            query = query.eq("status", status)
        if priority:
            query = query.eq("priority", priority)
        if assigned_to:
            query = query.eq("assigned_to", assigned_to)
        
        result = query.order("created_at", desc=True).limit(limit).execute()
        tasks = result.data if hasattr(result, 'data') else result
        
        return {"tasks": tasks or [], "count": len(tasks or [])}
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        return {"tasks": [], "count": 0}


@tasks_router.post("")
async def create_task(payload: TaskCreate, user=Depends(verify_jwt)):
    """Create a new task."""
    try:
        data = {
            "title": payload.title,
            "description": payload.description,
            "status": payload.status,
            "priority": payload.priority,
            "due_date": payload.due_date,
            "reminder_at": payload.reminder_at,
            "assigned_to": payload.assigned_to,
            "source": payload.source,
            "source_ref": payload.source_ref,
            "tags": json.dumps(payload.tags or []),
            "metadata": json.dumps(payload.metadata or {}),
        }
        
        result = db.table("placeware_tasks").insert(data).execute()
        inserted = result.data[0] if hasattr(result, 'data') and result.data else data
        
        logger.info(f"Task created: {payload.title} (source: {payload.source})")
        await realtime_hub.broadcast("calendar_tasks", {
            "event": "task_created",
            "id": inserted.get("id") if isinstance(inserted, dict) else None,
            "status": payload.status,
            "priority": payload.priority,
        })
        # If a specific user is assigned, notify their personal staff channel
        if payload.assigned_to:
            await realtime_hub.broadcast("staff_updates", {
                "event": "task_assigned",
                "assigned_to": payload.assigned_to,
                "title": payload.title,
                "priority": payload.priority,
                "id": inserted.get("id") if isinstance(inserted, dict) else None,
            })
        await realtime_hub.broadcast("workflow_updates", {
            "event": "task_created",
            "source": payload.source,
        })
        return {"data": inserted, "status": "created"}
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@tasks_router.patch("/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate, user=Depends(verify_jwt)):
    """Update an existing task."""
    try:
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # If marking as completed, set completed_at
        if data.get("status") == "completed":
            data["completed_at"] = datetime.utcnow().isoformat()
        
        result = db.table("placeware_tasks").update(data).eq("id", task_id).execute()
        updated = result.data[0] if hasattr(result, 'data') and result.data else data

        await realtime_hub.broadcast("calendar_tasks", {
            "event": "task_updated",
            "id": task_id,
            "status": data.get("status"),
        })
        
        return {"data": updated, "status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@tasks_router.delete("/{task_id}")
async def delete_task(task_id: str, user=Depends(verify_jwt)):
    """Delete a task."""
    try:
        db.table("placeware_tasks").delete().eq("id", task_id).execute()
        await realtime_hub.broadcast("calendar_tasks", {
            "event": "task_deleted",
            "id": task_id,
        })
        return {"status": "deleted", "id": task_id}
    except Exception as e:
        logger.error(f"Failed to delete task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Task Creation from Chat (used by EOS)
# ---------------------------------------------------------------------------

def create_task_from_chat(
    title: str,
    description: Optional[str] = None,
    priority: str = "medium",
    due_date: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> dict:
    """
    Helper function to create a task from chat/EOS context.
    Called by the EOS service when user requests task creation.
    """
    try:
        data = {
            "title": title,
            "description": description,
            "status": "pending",
            "priority": priority,
            "due_date": due_date,
            "source": "chat",
            "source_ref": chat_id,
            "tags": json.dumps([]),
            "metadata": json.dumps({"created_via": "synbot_chat"}),
        }
        
        result = db.table("placeware_tasks").insert(data).execute()
        inserted = result.data[0] if hasattr(result, 'data') and result.data else data
        
        logger.info(f"Task created from chat: {title}")
        return {"success": True, "task": inserted}
    except Exception as e:
        logger.error(f"Failed to create task from chat: {e}")
        return {"success": False, "error": str(e)}
