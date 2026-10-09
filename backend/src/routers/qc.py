"""
Quality Control Router — ACE
======================================
Exposes all QC & compliance endpoints derived from the April 2026
requirements survey (QA Officer + Receptionist respondents).

Endpoints:
  GET  /qc/dashboard                      – Unified KPI summary
  GET  /qc/expiry-alerts                  – Expiring stock in 30/60/90-day buckets
  POST /qc/temperature-logs               – Submit a cold-chain reading
  GET  /qc/temperature-logs               – List readings (filterable by date/location)
  GET  /qc/temperature-logs/deviations    – Active (unescalated) breaches
  POST /qc/temperature-logs/{id}/escalate – Mark a deviation escalated
  POST /qc/deviations                     – Create a CAPA deviation report
  GET  /qc/deviations                     – List deviation reports
  PATCH /qc/deviations/{id}               – Update report / add CAPA action
  POST /qc/deviations/{id}/close          – Close a report with resolution
  POST /qc/nafdac/batches                 – Register a batch in NAFDAC registry
  GET  /qc/nafdac/batches                 – List batches (filterable by status)
  PATCH /qc/nafdac/batches/{id}/approve   – Approve batch (clears dispatch block)
  PATCH /qc/nafdac/batches/{id}/reject    – Reject batch (enforces dispatch block)
  POST /qc/recalls                        – Initiate a product recall
  GET  /qc/recalls                        – List recall cases
  PATCH /qc/recalls/{id}/status           – Progress a recall case
"""

from __future__ import annotations

import logging
import datetime as dt
import uuid
from typing import Optional, List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.db import db, audit_event
from src.middleware import verify_jwt, require_role
from src.services.inventory import get_expiring_inventory
from src.services.qc import get_qc_summary
from src.constants import COMPLIANCE_QA_ROLES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qc", tags=["Quality Control"])


def _require_qc(request: Request) -> dict:
    """Accepts both 'quality_assurance' and 'qa' role strings (same alias
    set compliance.py already uses) -- the single-role require_role()
    factory this used to call did an exact 'quality_assurance' match only,
    silently locking out any account assigned literally 'qa' (a valid,
    free-text-assignable role string per AdminUsers.tsx) from its own QC
    endpoints."""
    payload = verify_jwt(request)
    roles = {str(r).lower() for r in payload.get("roles", [])}
    if not roles & COMPLIANCE_QA_ROLES:
        raise HTTPException(status_code=403, detail="Quality Assurance role required")
    return payload


def _hub(fn, *a, **k):
    """Run a quality_hub action (recalls / batch release go through ACE Books there)."""
    from src.services import quality_hub as qh
    from src.fin.errors import FinError
    try:
        return fn(*a, **k)
    except qh.QualityError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FinError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


def _sku_for(product_name: str) -> Optional[str]:
    """The ACE Books product code for a product name (the product itself, else its latest lot code)."""
    from src.fin.db import q1, tx
    from src.services.stock_orders import FAMILY_SQL
    with tx() as conn:
        r = q1(conn, f"""SELECT sku FROM fin_products
                         WHERE lower({FAMILY_SQL.format(name='name', sku='sku')}) = lower(%s)
                         ORDER BY (sku = {FAMILY_SQL.format(name='name', sku='sku')}) DESC, created_at DESC LIMIT 1""",
               (product_name.strip(),))
    return r["sku"] if r else None


# Role shortcuts
_require_admin   = require_role("admin")
_require_any     = verify_jwt   # any authenticated user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _actor(user) -> str:
    if isinstance(user, dict):
        return user.get("sub") or user.get("name") or "unknown"
    return str(user)


async def _audit(actor_id: str, action: str, subject_type: str, subject_id: str,
                 detail: dict | None = None):
    try:
        audit_event(
            event_type="qc_action",
            details=detail or {},
            event_class="quality_control",
            actor_id=actor_id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
        )
    except Exception as exc:
        logger.warning("Audit write failed: %s", exc)


def _row_or_404(table: str, id_: str, label: str = "Record") -> dict:
    try:
        resp = db.table(table).select("*").eq("id", id_).limit(1).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("%s fetch error: %s", label, exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch {label.lower()}")
    if not rows:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return rows[0]


# ===========================================================================
# 1. DASHBOARD
# ===========================================================================

@router.get("/dashboard")
def qc_dashboard(user=Depends(_require_any)):
    """Returns a single payload with all QC KPIs for the dashboard overview tab.
    Delegates to services/qc.py::get_qc_summary() -- also reused directly by
    the ACE Workstation aggregator (services/intelligence.py)."""
    return get_qc_summary()


# ===========================================================================
# 2. EXPIRY ALERTS
# ===========================================================================

@router.get("/expiry-alerts")
def expiry_alerts(
    days: int = Query(default=90, ge=1, le=365,
                      description="Look-ahead window in days. Returns items expiring within this window."),
    user=Depends(_require_any),
):
    """
    Returns expiring stock items bucketed into 30/60/90-day tiers plus 'expired'.
    Delegates to the existing inventory service — no duplicate query logic.
    """
    try:
        result = get_expiring_inventory(thresholds=[min(days, 90), 60, 30])
    except Exception as exc:
        logger.error("Expiry alerts error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to compute expiry alerts")

    items = result.get("items") or []

    # Group into buckets for the UI
    buckets: dict[str, list[dict]] = {
        "expired":  [],
        "critical": [],   # ≤ 30 days
        "high":     [],   # 31–60 days
        "medium":   [],   # 61–90 days
    }
    for item in items:
        tier = item.get("tier", "medium")
        if tier in buckets:
            buckets[tier].append(item)

    return {
        "window_days":  days,
        "total_flagged": len(items),
        "buckets":       buckets,
        "summary":       result.get("summary", {}),
    }


# ===========================================================================
# 3. TEMPERATURE LOGS
# ===========================================================================

class TemperatureLogIn(BaseModel):
    equipment_id:    Optional[str] = None
    location:        str = Field(..., min_length=2, max_length=200)
    reading_celsius: float = Field(..., ge=-40, le=60)
    min_threshold:   float = Field(default=2.0)
    max_threshold:   float = Field(default=8.0)
    log_session:     str   = Field(default="morning",
                                   description="morning | midday | evening | ad_hoc")
    logged_by:       str   = Field(..., min_length=2)
    logged_at:       Optional[str] = None   # ISO datetime; defaults to now
    notes:           Optional[str] = None


@router.post("/temperature-logs", status_code=201)
async def log_temperature(
    payload: TemperatureLogIn,
    user=Depends(verify_jwt),
):
    """Submit a cold-chain temperature reading. Flags deviation automatically."""
    actor = _actor(user)

    if payload.log_session not in ("morning", "midday", "evening", "ad_hoc"):
        raise HTTPException(status_code=400, detail="log_session must be: morning | midday | evening | ad_hoc")

    is_deviation = (
        payload.reading_celsius < payload.min_threshold
        or payload.reading_celsius > payload.max_threshold
    )

    row: dict = {
        "id":               str(uuid.uuid4()),
        "location":         payload.location,
        "reading_celsius":  payload.reading_celsius,
        "min_threshold":    payload.min_threshold,
        "max_threshold":    payload.max_threshold,
        "is_deviation":     is_deviation,
        "log_session":      payload.log_session,
        "logged_by":        payload.logged_by,
        "logged_at":        payload.logged_at or _now(),
        "notes":            payload.notes,
        "deviation_escalated": False,
    }
    if payload.equipment_id:
        row["equipment_id"] = payload.equipment_id

    try:
        db.table("temperature_logs").insert(row).execute()
    except Exception as exc:
        logger.error("Temperature log insert error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save temperature log")

    await _audit(actor, "log_temperature", "temperature_log", row["id"],
                 {"location": payload.location, "is_deviation": is_deviation,
                  "reading": payload.reading_celsius})

    return {
        "id":           row["id"],
        "is_deviation": is_deviation,
        "logged_at":    row["logged_at"],
    }


@router.get("/temperature-logs")
def list_temperature_logs(
    location:     Optional[str] = Query(default=None),
    date_from:    Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to:      Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    deviations_only: bool = Query(default=False),
    limit:        int = Query(default=100, le=500),
    user=Depends(_require_any),
):
    """List temperature log entries with optional filters."""
    try:
        q = db.table("temperature_logs").select(
            "id,equipment_id,location,reading_celsius,min_threshold,max_threshold,"
            "is_deviation,log_session,logged_by,logged_at,deviation_escalated,"
            "escalated_to,escalated_at,deviation_report_id,notes"
        )
        if location:
            q = q.ilike("location", f"%{location}%")
        if date_from:
            q = q.gte("logged_at", date_from)
        if date_to:
            d = dt.date.fromisoformat(date_to)
            q = q.lte("logged_at", (d + dt.timedelta(days=1)).isoformat())
        if deviations_only:
            q = q.eq("is_deviation", True)

        resp = q.order("logged_at", desc=True).limit(limit).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Temperature log list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list temperature logs")

    return {"count": len(rows), "logs": rows}


@router.get("/temperature-logs/deviations")
def active_deviations(user=Depends(_require_any)):
    """Return active (unescalated) temperature deviations using the helper view."""
    try:
        resp = db.table("v_temp_deviations_pending").select("*").execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Active deviations error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch deviations")

    return {"count": len(rows), "deviations": rows}


class EscalateIn(BaseModel):
    escalated_to:     str = Field(..., min_length=2)
    escalation_notes: Optional[str] = None


@router.post("/temperature-logs/{log_id}/escalate")
async def escalate_deviation(
    log_id: str,
    payload: EscalateIn,
    user=Depends(_require_any),
):
    """Mark a temperature deviation as escalated to a named person."""
    actor = _actor(user)
    log = _row_or_404("temperature_logs", log_id, "Temperature log")

    if not log.get("is_deviation"):
        raise HTTPException(status_code=409, detail="This log entry is not a deviation")
    if log.get("deviation_escalated"):
        raise HTTPException(status_code=409, detail="Already escalated")

    now = _now()
    try:
        db.table("temperature_logs").update({
            "deviation_escalated": True,
            "escalated_to":        payload.escalated_to,
            "escalated_at":        now,
            "escalation_notes":    payload.escalation_notes,
        }).eq("id", log_id).execute()
    except Exception as exc:
        logger.error("Escalation update error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to escalate deviation")

    await _audit(actor, "escalate_deviation", "temperature_log", log_id,
                 {"escalated_to": payload.escalated_to})

    return {"log_id": log_id, "escalated_to": payload.escalated_to, "escalated_at": now}


# ===========================================================================
# 4. DEVIATION REPORTS (CAPA)
# ===========================================================================

def _next_deviation_id() -> str:
    year = dt.date.today().year
    try:
        resp = (db.table("deviation_reports")
                .select("deviation_id")
                .ilike("deviation_id", f"DEV-{year}-%")
                .order("deviation_id", desc=True)
                .limit(1)
                .execute())
        rows = resp.data or []
        if rows:
            last_seq = int(rows[0]["deviation_id"].split("-")[-1])
            return f"DEV-{year}-{last_seq + 1:03d}"
    except Exception:
        pass
    return f"DEV-{year}-001"


class DeviationCreateIn(BaseModel):
    classification:          str  = Field(default="minor",
                                          description="minor | major | critical")
    trigger_type:            str  = Field(...,
                                          description="temperature_breach | audit_failure | "
                                                      "inspection_failed | missed_maintenance | "
                                                      "missed_activity | nafdac_violation | manual")
    trigger_ref:             Optional[str] = None
    observation:             str  = Field(..., min_length=10)
    impact_assessment:       Optional[str] = None
    recommendations:         Optional[str] = None
    responsible_department:  str  = Field(..., min_length=2)
    responsible_person:      Optional[str] = None
    capa_actions:            Optional[List[dict]] = None  # [{action,owner,due_date,status}]


VALID_CLASSIFICATION = {"minor", "major", "critical"}
VALID_TRIGGER        = {
    "temperature_breach", "audit_failure", "inspection_failed",
    "missed_maintenance", "missed_activity", "nafdac_violation", "manual",
}


@router.post("/deviations", status_code=201)
async def create_deviation(
    payload: DeviationCreateIn,
    user=Depends(_require_any),
):
    """Raise a CAPA deviation report."""
    actor = _actor(user)

    if payload.classification not in VALID_CLASSIFICATION:
        raise HTTPException(status_code=400,
                            detail=f"classification must be one of: {sorted(VALID_CLASSIFICATION)}")
    if payload.trigger_type not in VALID_TRIGGER:
        raise HTTPException(status_code=400,
                            detail=f"trigger_type must be one of: {sorted(VALID_TRIGGER)}")

    deviation_id = _next_deviation_id()
    row_id       = str(uuid.uuid4())
    now          = _now()

    row = {
        "id":                     row_id,
        "deviation_id":           deviation_id,
        "classification":         payload.classification,
        "trigger_type":           payload.trigger_type,
        "trigger_ref":            payload.trigger_ref,
        "investigation_start_date": dt.date.today().isoformat(),
        "observation":            payload.observation,
        "impact_assessment":      payload.impact_assessment,
        "recommendations":        payload.recommendations,
        "responsible_department": payload.responsible_department,
        "responsible_person":     payload.responsible_person,
        "status":                 "open",
        "capa_actions":           payload.capa_actions or [],
    }

    try:
        db.table("deviation_reports").insert(row).execute()
    except Exception as exc:
        logger.error("Deviation insert error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create deviation report")

    await _audit(actor, "create_deviation", "deviation_report", row_id,
                 {"deviation_id": deviation_id, "classification": payload.classification,
                  "trigger_type": payload.trigger_type})

    return {"id": row_id, "deviation_id": deviation_id, "status": "open"}


@router.get("/deviations")
def list_deviations(
    status:         Optional[str] = Query(default=None,
                                          description="open | under_investigation | closed | escalated"),
    classification: Optional[str] = Query(default=None),
    department:     Optional[str] = Query(default=None),
    limit:          int = Query(default=100, le=500),
    user=Depends(_require_any),
):
    """List CAPA deviation reports with optional filters."""
    try:
        q = db.table("deviation_reports").select(
            "id,deviation_id,classification,trigger_type,trigger_ref,"
            "observation,impact_assessment,responsible_department,"
            "responsible_person,status,capa_actions,created_at,updated_at"
        )
        if status:
            q = q.eq("status", status)
        if classification:
            q = q.eq("classification", classification)
        if department:
            q = q.ilike("responsible_department", f"%{department}%")

        resp = q.order("created_at", desc=True).limit(limit).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Deviation list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list deviation reports")

    return {"count": len(rows), "deviations": rows}


class DeviationUpdateIn(BaseModel):
    status:              Optional[str]       = None  # open|under_investigation|escalated
    impact_assessment:   Optional[str]       = None
    recommendations:     Optional[str]       = None
    responsible_person:  Optional[str]       = None
    capa_actions:        Optional[List[dict]] = None  # full replacement


@router.patch("/deviations/{deviation_id}")
async def update_deviation(
    deviation_id: str,
    payload: DeviationUpdateIn,
    user=Depends(_require_any),
):
    """Update a deviation report or replace its CAPA action list."""
    actor = _actor(user)
    existing = _row_or_404("deviation_reports", deviation_id, "Deviation report")

    MUTABLE_STATUSES = {"open", "under_investigation", "escalated"}
    if existing["status"] == "closed":
        raise HTTPException(status_code=409, detail="Cannot update a closed deviation report")

    VALID_UPDATE_STATUS = {"open", "under_investigation", "escalated"}
    if payload.status and payload.status not in VALID_UPDATE_STATUS:
        raise HTTPException(status_code=400,
                            detail=f"status must be one of: {sorted(VALID_UPDATE_STATUS)}")

    updates: dict = {"updated_at": _now()}
    if payload.status:
        updates["status"]             = payload.status
    if payload.impact_assessment is not None:
        updates["impact_assessment"]  = payload.impact_assessment
    if payload.recommendations is not None:
        updates["recommendations"]    = payload.recommendations
    if payload.responsible_person is not None:
        updates["responsible_person"] = payload.responsible_person
    if payload.capa_actions is not None:
        updates["capa_actions"]       = payload.capa_actions

    try:
        db.table("deviation_reports").update(updates).eq("id", deviation_id).execute()
    except Exception as exc:
        logger.error("Deviation update error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update deviation report")

    await _audit(actor, "update_deviation", "deviation_report", deviation_id,
                 {"changes": list(updates.keys())})

    return {"id": deviation_id, "updated": list(updates.keys())}


class DeviationCloseIn(BaseModel):
    resolution:        str = Field(..., min_length=10,
                                   description="Summary of how the deviation was resolved")
    capa_actions:      Optional[List[dict]] = None   # final CAPA actions if updating


@router.post("/deviations/{deviation_id}/close")
async def close_deviation(
    deviation_id: str,
    payload: DeviationCloseIn,
    user=Depends(_require_any),
):
    """Close a deviation report with a documented resolution."""
    actor = _actor(user)
    existing = _row_or_404("deviation_reports", deviation_id, "Deviation report")

    if existing["status"] == "closed":
        raise HTTPException(status_code=409, detail="Already closed")

    updates: dict = {
        "status":          "closed",
        "recommendations": payload.resolution,
        "closed_at":       _now(),
        "updated_at":      _now(),
    }
    if payload.capa_actions is not None:
        updates["capa_actions"] = payload.capa_actions

    try:
        db.table("deviation_reports").update(updates).eq("id", deviation_id).execute()
    except Exception as exc:
        logger.error("Deviation close error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to close deviation report")

    await _audit(actor, "close_deviation", "deviation_report", deviation_id,
                 {"deviation_id": existing.get("deviation_id"), "resolution": payload.resolution})

    return {"id": deviation_id, "status": "closed"}


# ===========================================================================
# 5. NAFDAC BATCH REGISTRY
# ===========================================================================

class NafdacBatchIn(BaseModel):
    batch_number:      str  = Field(..., min_length=2)
    product_name:      str  = Field(..., min_length=2)
    nafdac_reg_number: Optional[str] = None
    supplier:          Optional[str] = None
    valid_from:        Optional[str] = None   # date ISO
    valid_to:          Optional[str] = None   # date ISO
    certificate_ref:   Optional[str] = None
    notes:             Optional[str] = None


@router.post("/nafdac/batches", status_code=201)
def register_nafdac_batch(
    payload: NafdacBatchIn,
    user=Depends(verify_jwt),
):
    """Register a batch for QC release. Bound to the ACE Books product/batch: while pending it is
    quarantined there (cannot be sold); see services/quality_hub.register_batch."""
    from src.services import quality_hub as qh
    sku = _sku_for(payload.product_name)
    if not sku:
        raise HTTPException(status_code=409, detail=f"{payload.product_name!r} is not a product in ACE Books")
    return _hub(qh.register_batch, user, {**payload.model_dump(), "sku": sku})


@router.get("/nafdac/batches")
def list_nafdac_batches(
    status:    Optional[str] = Query(default=None,
                                     description="pending | approved | rejected | suspended"),
    product:   Optional[str] = Query(default=None),
    blocked:   Optional[bool] = Query(default=None,
                                      description="Filter by dispatch_blocked flag"),
    limit:     int = Query(default=100, le=500),
    user=Depends(_require_any),
):
    """List NAFDAC batch registry entries."""
    try:
        q = db.table("nafdac_batch_registry").select(
            "id,batch_number,product_name,nafdac_reg_number,supplier,status,"
            "dispatch_blocked,valid_from,valid_to,certificate_ref,"
            "registered_by,approved_by,approved_at,rejection_reason,notes,created_at,updated_at"
        )
        if status:
            q = q.eq("status", status)
        if product:
            q = q.ilike("product_name", f"%{product}%")
        if blocked is not None:
            q = q.eq("dispatch_blocked", blocked)

        resp = q.order("created_at", desc=True).limit(limit).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("NAFDAC batch list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list NAFDAC batches")

    return {"count": len(rows), "batches": rows}


class NafdacApproveIn(BaseModel):
    valid_from:        Optional[str] = None
    valid_to:          Optional[str] = None
    certificate_ref:   Optional[str] = None
    nafdac_reg_number: Optional[str] = None
    notes:             Optional[str] = None


@router.patch("/nafdac/batches/{batch_id}/approve")
def approve_nafdac_batch(
    batch_id: str,
    payload:  NafdacApproveIn,
    user=Depends(_require_qc),
):
    """Release a batch: sellable again in ACE Books. Requires quality_assurance role."""
    from src.services import quality_hub as qh
    return _hub(qh.release_batch, user, batch_id, payload.model_dump(exclude_none=True))


class NafdacRejectIn(BaseModel):
    rejection_reason: str = Field(..., min_length=5)
    notes:            Optional[str] = None


@router.patch("/nafdac/batches/{batch_id}/reject")
def reject_nafdac_batch(
    batch_id: str,
    payload:  NafdacRejectIn,
    user=Depends(_require_qc),
):
    """Reject a batch: stays quarantined in ACE Books and a deviation is raised."""
    from src.services import quality_hub as qh
    return _hub(qh.reject_batch, user, batch_id, payload.rejection_reason, payload.notes)


# ===========================================================================
# 6. PRODUCT RECALLS
# ===========================================================================

def _next_recall_id() -> str:
    year = dt.date.today().year
    try:
        resp = (db.table("recall_cases")
                .select("recall_id")
                .ilike("recall_id", f"RECALL-{year}-%")
                .order("recall_id", desc=True)
                .limit(1)
                .execute())
        rows = resp.data or []
        if rows:
            last_seq = int(rows[0]["recall_id"].split("-")[-1])
            return f"RECALL-{year}-{last_seq + 1:03d}"
    except Exception:
        pass
    return f"RECALL-{year}-001"


class RecallCreateIn(BaseModel):
    batch_number:         str  = Field(..., min_length=2)
    product_name:         str  = Field(..., min_length=2)
    recall_reason:        str  = Field(..., min_length=10)
    scope:                str  = Field(default="voluntary",
                                       description="voluntary | mandatory")
    regulatory_authority: str  = Field(default="NAFDAC")
    distribution_data:    Optional[List[dict]] = None
    # [{customer_id?, name, qty, location, delivered_at?}]


VALID_RECALL_SCOPE = {"voluntary", "mandatory"}


@router.post("/recalls", status_code=201)
def initiate_recall(
    payload: RecallCreateIn,
    user=Depends(_require_qc),
):
    """Initiate a recall: the ACE Books recall is opened with it (batch frozen, buyers traced)."""
    from src.services import quality_hub as qh
    if payload.scope not in VALID_RECALL_SCOPE:
        raise HTTPException(status_code=400, detail=f"scope must be one of: {sorted(VALID_RECALL_SCOPE)}")
    return _hub(qh.initiate_recall, user, payload.model_dump())


@router.get("/recalls")
def list_recalls(
    status:  Optional[str] = Query(default=None,
                                   description="initiated | in_progress | completed | closed"),
    product: Optional[str] = Query(default=None),
    limit:   int = Query(default=100, le=200),
    user=Depends(_require_any),
):
    """List product recall cases."""
    try:
        q = db.table("recall_cases").select(
            "id,recall_id,batch_number,product_name,recall_reason,"
            "initiation_date,scope,status,regulatory_authority,"
            "distribution_data,created_by,resolved_at,created_at,updated_at"
        )
        if status:
            q = q.eq("status", status)
        if product:
            q = q.ilike("product_name", f"%{product}%")

        resp = q.order("created_at", desc=True).limit(limit).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Recall list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list recalls")

    return {"count": len(rows), "recalls": rows}


VALID_RECALL_STATUS = {"initiated", "in_progress", "completed", "closed"}


class RecallStatusIn(BaseModel):
    status:           str = Field(..., description="initiated | in_progress | completed | closed")
    distribution_data: Optional[List[dict]] = None   # append/replace affected clients
    notes:            Optional[str] = None


@router.patch("/recalls/{recall_id}/status")
def update_recall_status(
    recall_id: str,
    payload:   RecallStatusIn,
    user=Depends(_require_qc),
):
    """Progress a recall; completing/closing it closes the ACE Books recall too."""
    from src.services import quality_hub as qh
    if payload.status not in VALID_RECALL_STATUS:
        raise HTTPException(status_code=400, detail=f"status must be one of: {sorted(VALID_RECALL_STATUS)}")
    return _hub(qh.update_recall, user, recall_id, {"status": payload.status, "notes": payload.notes})
