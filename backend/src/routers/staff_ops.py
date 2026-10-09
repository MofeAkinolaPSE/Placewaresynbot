from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field, EmailStr, validator
from typing import Dict, Any, List, Optional
from datetime import date
import logging
import csv
import io
import codecs

from src.middleware import verify_jwt, require_role
from src.services.staff_ops import (
    create_staff_member,
    get_staff_by_department,
    get_staff_by_id,
    record_timesheet_entry,
    get_timesheets,
    get_latest_staff_snapshot,
)
from src.services.realtime import realtime_hub
from src.cache import invalidate_cache_tags
from src.services.oeis import process_operational_event

router = APIRouter(tags=["staff_ops"])
audit_logger = logging.getLogger("audit")

# --- Models ---

class StaffCreateRequest(BaseModel):
    full_name: str
    email: EmailStr
    department: str = Field(..., description="Finance, Sales, Operations, HR, Management")
    role: Optional[str] = None

    @validator('department')
    def validate_dept(cls, v):
        from src.services.staff_workspace import DEPARTMENTS
        allowed = set(DEPARTMENTS)
        if v not in allowed:
            raise ValueError(f"Department must be one of {allowed}")
        return v

class TimesheetEntryRequest(BaseModel):
    staff_id: str
    date: date
    hours_worked: float = Field(..., gt=0, le=24)
    department: str # Confirmed at entry time
    activity_note: Optional[str] = None

# --- Dependencies ---

def require_hr_admin(request: Request) -> Dict[str, Any]:
    """Write access for Staff Registry: HR or Admin only."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    if not any(r in {"admin", "hr"} for r in roles):
        raise HTTPException(403, "Insufficient privileges (HR/Admin required)")
    return payload

def require_dept_read(request: Request) -> Dict[str, Any]:
    """Read access: Must be authenticated."""
    return verify_jwt(request)

def require_timesheet_write(request: Request) -> Dict[str, Any]:
    """Anyone may record their own hours; HR / admin / management may record anyone's."""
    return verify_jwt(request)


def _resolve_timesheet_person(staff_or_user_id: str, user: Dict[str, Any]) -> str:
    """The time tracker used to send the login id where a staff id was required, so every
    clock-out failed on the foreign key. Accept either and resolve to the HR profile."""
    from src.fin.db import q1, tx
    from src.services.staff_workspace import ensure_profile
    me = str(user.get("sub") or "")
    privileged = bool({"admin", "hr", "management"} & set(user.get("roles") or []))
    with tx() as conn:
        s = q1(conn, "SELECT staff_id::text AS staff_id, user_id::text AS user_id FROM placeware_staff WHERE staff_id::text=%s",
               (staff_or_user_id,))
        if s:
            if not privileged and s["user_id"] != me:
                raise HTTPException(403, "You can only record your own hours")
            return s["staff_id"]
        if staff_or_user_id != me and not privileged:
            raise HTTPException(403, "You can only record your own hours")
        if not q1(conn, "SELECT 1 FROM placeware_users WHERE id::text=%s", (staff_or_user_id,)):
            raise HTTPException(404, "Staff member not found")
        return ensure_profile(conn, staff_or_user_id)

# --- Staff Endpoints ---

@router.post("/staff")
async def register_staff(
    staff: StaffCreateRequest, 
    user: Dict[str, Any] = Depends(require_hr_admin)
):
    """Register a new staff member manually."""
    try:
        new_staff = create_staff_member(
            staff.full_name, staff.email, staff.department, staff.role
        )
        audit_logger.info({"event": "staff_created", "target": staff.email, "actor": user.get("sub")})
        await realtime_hub.broadcast("staff_updates", {
            "event": "staff_created",
            "staff_id": new_staff.get("staff_id"),
            "department": new_staff.get("department"),
            "actor": user.get("sub"),
        })
        invalidate_cache_tags("staff", "workforce_dashboard", "hr_summary", "executive")
        try:
            await process_operational_event(
                {
                    "department": "staff",
                    "event_type": "staff_created",
                    "payload": {
                        "staff_id": new_staff.get("staff_id"),
                        "department": new_staff.get("department"),
                        "email": new_staff.get("email"),
                    },
                    "created_by": user.get("sub"),
                    "status": "submitted",
                },
                actor_id=user.get("sub"),
            )
        except Exception:
            pass
        return {"success": True, "data": new_staff}
    except Exception as e:
        audit_logger.error(f"Staff creation failed: {e}")
        raise HTTPException(500, "Failed to create staff record")

@router.get("/staff")
def list_staff(
    department: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    """List staff members (directory view)."""
    return {"data": get_staff_by_department(department)}

@router.get("/staff/snapshot")
def list_staff_snapshot(
    limit: int = 1000,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    """List latest rows from sage_staff_snapshot for diagnostics/fallback UI."""
    rows = get_latest_staff_snapshot(limit=limit)
    return {"data": rows}


@router.get("/staff/{staff_id}")
def get_single_staff(
    staff_id: str,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    staff = get_staff_by_id(staff_id)
    if not staff:
        raise HTTPException(404, "Staff not found")
    return {"data": staff}

@router.post("/staff/import")
def import_staff_csv(
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(require_hr_admin)
):
    """Bulk import staff from CSV. Columns: full_name, email, department, role"""
    try:
        reader = csv.DictReader(codecs.iterdecode(file.file, 'utf-8'))
        results = []
        for row in reader:
            # Basic map, skip errors for MVP
            try:
                res = create_staff_member(
                    full_name=row['full_name'],
                    email=row['email'],
                    department=row['department'],
                    role=row.get('role', '')
                )
                results.append(res)
            except Exception as e:
                logging.warning(f"Skipping row {row}: {e}")
        
        audit_logger.info({"event": "staff_bulk_import", "count": len(results), "actor": user.get("sub")})
        return {"success": True, "imported_count": len(results)}
    except Exception as e:
        raise HTTPException(400, f"CSV parsing failed: {str(e)}")

# --- Timesheet Endpoints ---

@router.post("/timesheets")
async def submit_timesheet(
    entry: TimesheetEntryRequest,
    user: Dict[str, Any] = Depends(require_timesheet_write)
):
    """Record a single timesheet entry."""
    staff_id = _resolve_timesheet_person(entry.staff_id, user)
    try:
        data = record_timesheet_entry(
            staff_id, entry.date, entry.hours_worked,
            entry.department, entry.activity_note, 
            recorded_by=user.get("sub", "api")
        )
        await realtime_hub.broadcast("staff_updates", {
            "event": "timesheet_recorded",
            "staff_id": entry.staff_id,
            "department": entry.department,
            "hours_worked": entry.hours_worked,
            "recorded_by": user.get("sub", "api"),
        })
        invalidate_cache_tags("staff", "workforce_dashboard", "hr_summary", "executive")
        try:
            await process_operational_event(
                {
                    "department": "staff",
                    "event_type": "timesheet_recorded",
                    "payload": {
                        "staff_id": entry.staff_id,
                        "department": entry.department,
                        "hours_worked": entry.hours_worked,
                        "date": str(entry.date),
                    },
                    "created_by": user.get("sub", "api"),
                    "status": "submitted",
                },
                actor_id=user.get("sub", "api"),
            )
        except Exception:
            pass
        return {"success": True, "data": data}
    except Exception as e:
        logging.error(f"Timesheet error: {e}")
        raise HTTPException(500, "Failed to record timesheet")

@router.get("/timesheets")
def view_timesheets(
    department: Optional[str] = None,
    limit: int = 50,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    """View recent timesheets."""
    return {"data": get_timesheets(department=department, limit=limit)}

@router.get("/timesheets/staff/{staff_id}")
def view_staff_timesheets(
    staff_id: str,
    limit: int = 50,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    return {"data": get_timesheets(staff_id=staff_id, limit=limit)}
