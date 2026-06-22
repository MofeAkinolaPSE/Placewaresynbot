"""
report_session_service.py — Service layer for report generation sessions.
=========================================================================
Manages the lifecycle of a placeware_report_sessions row from wizard start
through scope collection, generation, and final approval.

All database calls are parameterised and validated before execution.
No raw SQL strings are constructed from user input.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# ── Allowed values ─────────────────────────────────────────────────────────────
_VALID_STATUSES = frozenset({"draft", "scoping", "generating", "complete", "approved", "failed"})
_VALID_REPORT_TYPES = frozenset({
    "deviation", "maintenance", "compliance", "audit",
    "financial", "inventory", "executive", "sales",
    "payroll", "pl", "ar_aging", "frontdesk", "invoice",
})

# Template version — bump when REPORT_TEMPLATE_REGISTRY changes
TEMPLATE_VERSION = "2025-05-09"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_db():
    """Lazy import of the Supabase client to avoid import cycles."""
    from src.db import db
    return db


def _validate_report_type(report_type: str) -> str:
    rt = str(report_type).strip().lower()
    if rt not in _VALID_REPORT_TYPES:
        raise ValueError(
            f"Unknown report_type {rt!r}. "
            f"Valid types: {', '.join(sorted(_VALID_REPORT_TYPES))}"
        )
    return rt


def _validate_uuid(value: str, field_name: str = "id") -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid {field_name}: {value!r} is not a valid UUID.")


def _sanitise_scope_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Whitelist scope parameter keys and value types.
    Rejects any key not in the allowed set to prevent injection via scope.
    """
    _ALLOWED_KEYS = {
        "date_from", "date_to", "department", "entity_filter", "sku_filter",
        "customer_filter", "currency", "custom_notes", "line_items",
        "low_stock_threshold", "sales_rep", "region", "location",
        "equipment_type", "standard", "audit_type", "severity_filter",
        "compare_period", "audience", "warehouse",
        # Invoice-specific
        "client_name", "client_address", "client_email",
        "invoice_date", "due_date", "vat_rate", "payment_terms",
        "bank_details", "staff_member",
    }
    sanitised: Dict[str, Any] = {}
    for key, value in params.items():
        if key not in _ALLOWED_KEYS:
            logger.warning("report_session: ignoring disallowed scope key %r", key)
            continue
        # Scalar values only (prevent nested injection payloads)
        # line_items is the only allowed list
        if key == "line_items":
            if isinstance(value, list):
                sanitised[key] = value
        elif isinstance(value, (str, int, float, bool)) or value is None:
            sanitised[key] = value
    return sanitised


# ── Public API ─────────────────────────────────────────────────────────────────

def create_session(report_type: str, created_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new report session in 'draft' status.

    Returns the full session row from Supabase.
    Raises ValueError for invalid report_type.
    """
    rt = _validate_report_type(report_type)
    db = _get_db()

    row = {
        "report_type": rt,
        "session_status": "draft",
        "scope_params": {},
        "created_by": created_by,
    }
    try:
        res = db.table("placeware_report_sessions").insert(row).execute()
        if not res.data:
            raise RuntimeError("Database insert returned no data")
        session = res.data[0]
        logger.info("report_session: created session %s for type=%s", session["id"], rt)
        return session
    except Exception as exc:
        logger.error("report_session: create_session failed: %s", exc)
        raise


def update_scope(
    session_id: str,
    scope_params: Dict[str, Any],
    evidence_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update the scope parameters for a session and advance status to 'scoping'.

    scope_params keys are whitelisted to prevent injection.
    Returns the updated session row.
    """
    sid = _validate_uuid(session_id, "session_id")
    sanitised = _sanitise_scope_params(scope_params)

    db = _get_db()
    update_payload: Dict[str, Any] = {
        "scope_params": sanitised,
        "session_status": "scoping",
    }
    if evidence_notes is not None:
        # Truncate to prevent oversized payloads
        update_payload["evidence_notes"] = str(evidence_notes)[:4000]

    try:
        res = (
            db.table("placeware_report_sessions")
            .update(update_payload)
            .eq("id", sid)
            .execute()
        )
        if not res.data:
            raise ValueError(f"Session {sid} not found or no rows updated")
        session = res.data[0]
        logger.info("report_session: updated scope for session %s", sid)
        return session
    except Exception as exc:
        logger.error("report_session: update_scope failed: %s", exc)
        raise


def get_session(session_id: str) -> Dict[str, Any]:
    """
    Fetch a single session by ID.

    Raises ValueError if not found.
    """
    sid = _validate_uuid(session_id, "session_id")
    db = _get_db()

    try:
        res = (
            db.table("placeware_report_sessions")
            .select("*")
            .eq("id", sid)
            .single()
            .execute()
        )
        if not res.data:
            raise ValueError(f"Session {sid} not found")
        return res.data
    except Exception as exc:
        logger.error("report_session: get_session failed: %s", exc)
        raise


def mark_generating(session_id: str) -> None:
    """Set session status to 'generating'. Called before the agent runs."""
    sid = _validate_uuid(session_id, "session_id")
    db = _get_db()
    try:
        db.table("placeware_report_sessions").update(
            {"session_status": "generating"}
        ).eq("id", sid).execute()
    except Exception as exc:
        logger.warning("report_session: mark_generating failed: %s", exc)


def complete_session(session_id: str, report_memory_id: str) -> None:
    """
    Advance session to 'complete' and link the generated report_memory row.
    Called after the agent writes to placeware_report_memory.
    """
    sid = _validate_uuid(session_id, "session_id")
    rid = _validate_uuid(report_memory_id, "report_memory_id")
    db = _get_db()
    try:
        db.table("placeware_report_sessions").update({
            "session_status": "complete",
            "report_id": rid,
        }).eq("id", sid).execute()
    except Exception as exc:
        logger.warning("report_session: complete_session failed: %s", exc)


def fail_session(session_id: str) -> None:
    """Mark session as 'failed' on generation error."""
    sid = _validate_uuid(session_id, "session_id")
    db = _get_db()
    try:
        db.table("placeware_report_sessions").update(
            {"session_status": "failed"}
        ).eq("id", sid).execute()
    except Exception as exc:
        logger.warning("report_session: fail_session failed: %s", exc)


def approve_report(
    session_id: str,
    approver_id: str,
    report_memory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Approve a completed report.

    Updates both placeware_report_sessions and, if report_memory_id is supplied,
    placeware_report_memory to reflect the approval.
    Returns the updated session row.
    """
    sid = _validate_uuid(session_id, "session_id")
    approver = str(approver_id)[:200]  # bounded string
    now = datetime.now(timezone.utc).isoformat()
    db = _get_db()

    try:
        res = (
            db.table("placeware_report_sessions")
            .update({
                "session_status": "approved",
                "approved_by": approver,
                "approved_at": now,
            })
            .eq("id", sid)
            .execute()
        )
        if not res.data:
            raise ValueError(f"Session {sid} not found")

        # Mirror approval onto the report memory row
        if report_memory_id:
            rid = _validate_uuid(report_memory_id, "report_memory_id")
            db.table("placeware_report_memory").update({
                "approval_status": "approved",
                "approved_by": approver,
                "approved_at": now,
            }).eq("id", rid).execute()

        logger.info("report_session: session %s approved by %s", sid, approver)
        return res.data[0]
    except Exception as exc:
        logger.error("report_session: approve_report failed: %s", exc)
        raise


def list_sessions(
    created_by: Optional[str] = None,
    report_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List report sessions with optional filters.

    Returns rows ordered by created_at DESC.
    """
    db = _get_db()
    try:
        q = (
            db.table("placeware_report_sessions")
            .select(
                "id, report_type, session_status, scope_params, created_by, "
                "report_id, approved_by, approved_at, created_at, updated_at"
            )
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if created_by:
            q = q.eq("created_by", str(created_by)[:200])
        if report_type and report_type in _VALID_REPORT_TYPES:
            q = q.eq("report_type", report_type)
        if status and status in _VALID_STATUSES:
            q = q.eq("session_status", status)

        res = q.execute()
        return res.data or []
    except Exception as exc:
        logger.error("report_session: list_sessions failed: %s", exc)
        return []
