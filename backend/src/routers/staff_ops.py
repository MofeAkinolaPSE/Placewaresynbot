from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field, EmailStr, validator
from typing import Dict, Any, List, Optional
from datetime import date
import logging
import csv
import io
import codecs

from src.middleware import verify_jwt
from src.services.staff_ops import (
    create_staff_member,
    get_staff_by_department,
    get_staff_by_id,
    record_timesheet_entry,
    get_timesheets,
    get_latest_staff_snapshot,
)

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
        allowed = {'Finance', 'Sales', 'Operations', 'HR', 'Management'}
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
    """Write access for Timesheets: Admin, HR, Ops, Management."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "hr", "ops", "management"}
    if not any(r in allowed for r in roles):
        raise HTTPException(403, "Insufficient privileges to record timesheets")
    return payload

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
        return {"success": True, "data": new_staff}
    except Exception as e:
        audit_logger.error(f"Staff creation failed: {e}")
        raise HTTPException(500, "Failed to create staff record")

@router.get("/staff")
async def list_staff(
    department: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    """List staff members (directory view)."""
    return {"data": get_staff_by_department(department)}

@router.get("/staff/snapshot")
async def list_staff_snapshot(
    limit: int = 1000,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    """List latest rows from sage_staff_snapshot for diagnostics/fallback UI."""
    rows = get_latest_staff_snapshot(limit=limit)
    return {"data": rows}


@router.get("/staff/{staff_id}")
async def get_single_staff(
    staff_id: str,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    staff = get_staff_by_id(staff_id)
    if not staff:
        raise HTTPException(404, "Staff not found")
    return {"data": staff}

@router.post("/staff/import")
async def import_staff_csv(
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
    try:
        data = record_timesheet_entry(
            entry.staff_id, entry.date, entry.hours_worked, 
            entry.department, entry.activity_note, 
            recorded_by=user.get("sub", "api")
        )
        return {"success": True, "data": data}
    except Exception as e:
        logging.error(f"Timesheet error: {e}")
        raise HTTPException(500, "Failed to record timesheet")

@router.get("/timesheets")
async def view_timesheets(
    department: Optional[str] = None,
    limit: int = 50,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    """View recent timesheets."""
    return {"data": get_timesheets(department=department, limit=limit)}

@router.get("/timesheets/staff/{staff_id}")
async def view_staff_timesheets(
    staff_id: str,
    limit: int = 50,
    user: Dict[str, Any] = Depends(require_dept_read)
):
    return {"data": get_timesheets(staff_id=staff_id, limit=limit)}
