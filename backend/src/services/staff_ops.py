from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import date
from supabase import Client
from ..db import supabase
from ..constants import TABLE_STAFF, TABLE_TIMESHEETS
from .sage_adapter.service import get_sage_kpi_batch_id

logger = logging.getLogger("ops")

# --- Staff Registry Logic ---

def create_staff_member(
    full_name: str,
    email: str,
    department: str,
    role: str,
    client: Client = supabase
) -> Dict[str, Any]:
    """Create a new staff record (Identity only, no authentication/user creation)."""
    payload = {
        "full_name": full_name,
        "email": email,
        "department": department,
        "role": role,
        "status": "active"
    }
    resp = client.table(TABLE_STAFF).insert(payload).execute()
    return resp.data[0] if resp.data else {}

def get_staff_by_department(department: Optional[str] = None, client: Client = supabase) -> List[Dict[str, Any]]:
    """List staff, optionally filtered by department."""
    query = client.table(TABLE_STAFF).select("*")
    if department:
        query = query.eq("department", department)
    resp = query.execute()
    return resp.data or []

def get_staff_by_id(staff_id: str, client: Client = supabase) -> Optional[Dict[str, Any]]:
    resp = client.table(TABLE_STAFF).select("*").eq("staff_id", staff_id).execute()
    return resp.data[0] if resp.data else None

# --- Timesheet Logic ---

def record_timesheet_entry(
    staff_id: str,
    work_date: date,
    hours: float,
    department: str,
    note: Optional[str],
    recorded_by: str,
    client: Client = supabase
) -> Dict[str, Any]:
    """Record a single timesheet entry."""
    payload = {
        "staff_id": staff_id,
        "date": work_date.isoformat(),
        "hours_worked": hours,
        "department": department,
        "activity_note": note,
        "recorded_by": recorded_by
    }
    resp = client.table(TABLE_TIMESHEETS).insert(payload).execute()
    return resp.data[0] if resp.data else {}

def get_timesheets(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    department: Optional[str] = None,
    staff_id: Optional[str] = None,
    limit: int = 100,
    client: Client = supabase
) -> List[Dict[str, Any]]:
    """Query timesheets with flexible filters."""
    # join with staff name for visibility
    query = client.table(TABLE_TIMESHEETS).select("*, staff:placeware_staff(full_name)")
    
    if start_date:
        query = query.gte("date", start_date.isoformat())
    if end_date:
        query = query.lte("date", end_date.isoformat())
    if department:
        query = query.eq("department", department)
    if staff_id:
        query = query.eq("staff_id", staff_id)
        
    resp = query.order("date", desc=True).limit(limit).execute()
    return resp.data or []


def sync_staff_batch(staff_rows: List[Dict[str, Any]], client: Client = supabase) -> int:
    """
    Syncs a batch of staff rows from Sage import to the live placeware_staff table.
    Matches strictly on 'email' to avoid duplicates.
    Updates full_name, department, role if found.
    Inserts if new (and has email).
    Returns count of processed records.
    """
    to_upsert = []
    for row in staff_rows:
        email = (row.get("email") or "").strip()
        # Synthesize a stable placeholder email if missing to satisfy NOT NULL/UNIQUE
        # Uses staff_id if available, else a slug from full_name.
        if not email or "@" not in email:
            sid = (row.get("staff_id") or "").strip()
            if sid:
                email = f"staff-{sid.lower()}@placeholder.local"
            else:
                name = (row.get("full_name") or "unknown").strip().lower().replace(" ", "-")
                email = f"staff-{name}@placeholder.local"

        # Map Sage fields to placeware_staff fields
        # Note: 'staff_id' from Sage is ignored in favor of UUID, 
        # unless we add an external_id column later.
        record = {
            "email": email.lower().strip(),
            "full_name": row.get("full_name"),
            "department": row.get("department") or "Operations", # Default if missing
            "role": row.get("role"),
            "status": "active" # Reactivate if previously inactive? Or trust source?
        }
        
        # simple validation for department as per constraint
        if record["department"] not in ('Finance', 'Sales', 'Operations', 'HR', 'Management'):
            record["department"] = "Operations" # Fallback
            
        to_upsert.append(record)
        
    if not to_upsert:
        return 0
        
    # Batch upsert
    # on_conflict="email" handles the update vs insert
    try:
        resp = client.table(TABLE_STAFF).upsert(to_upsert, on_conflict="email").execute()
        return len(resp.data) if resp.data else 0
    except Exception as e:
        logger.error(f"Failed to sync staff batch: {e}")
        return 0


def get_latest_staff_snapshot(limit: int = 1000, client: Client = supabase) -> List[Dict[str, Any]]:
    """Return latest staff snapshot rows (append-only) for visibility/fallback.

    Orders by imported_at desc then id desc; limits results. Deduplicates by email if present.
    """
    sage_batch_id = get_sage_kpi_batch_id()
    q = client.table("sage_staff_snapshot").select(
        "staff_id,full_name,email,department,role,status,imported_at"
    )
    if sage_batch_id:
        q = q.eq("batch_id", sage_batch_id)
    resp = q.order("imported_at", desc=True).order("id", desc=True).limit(limit).execute()
    rows = resp.data or []
    latest_by_email: Dict[str, Dict[str, Any]] = {}
    result: List[Dict[str, Any]] = []
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        if email:
            if email in latest_by_email:
                continue
            latest_by_email[email] = r
            result.append(r)
        else:
            result.append(r)
    return result
