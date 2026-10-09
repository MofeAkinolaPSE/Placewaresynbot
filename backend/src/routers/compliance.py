"""Compliance router — QMS endpoints for Placeware Nigeria.

Endpoints:
  GET  /compliance/status              — overall health summary
  GET  /compliance/activities          — list activities
  POST /compliance/activities          — log a new activity
  PUT  /compliance/activities/{id}     — update activity
  GET  /compliance/activities/overdue  — overdue list

  GET  /compliance/audits              — audit schedule
  GET  /compliance/audits/upcoming     — upcoming 30 days
  POST /compliance/audits/{id}/start   — mark in_progress
  POST /compliance/audits/{id}/complete — mark complete

  GET  /compliance/deviations          — list deviations
  POST /compliance/deviations          — create deviation
  GET  /compliance/deviations/{id}     — detail
  PUT  /compliance/deviations/{id}     — update
  POST /compliance/deviations/{id}/generate-report  — PDF report

  GET  /compliance/equipment           — list equipment
  POST /compliance/equipment           — register equipment
  GET  /compliance/equipment/{id}      — equipment detail

  GET  /compliance/maintenance         — maintenance list
  GET  /compliance/maintenance/overdue — overdue tasks
  GET  /compliance/maintenance/upcoming — upcoming ≤14 days
  POST /compliance/maintenance/{id}/complete — record completion

  GET  /compliance/recalls             — list recalls
  POST /compliance/recalls             — initiate recall
  GET  /compliance/recalls/{id}        — detail
  PUT  /compliance/recalls/{id}        — update
  POST /compliance/recalls/{id}/generate-documents — generate all docs

  GET  /compliance/sop                 — list SOPs
  POST /compliance/sop/ingest-docx     — ingest a DOCX file into sop_registry + QnA RAG
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.db import db, audit_event
from src.middleware import verify_jwt
from src.constants import (
    TABLE_SOP_REGISTRY,
    TABLE_AUDIT_SCHEDULE,
    TABLE_COMPLIANCE_ACTIVITY,
    TABLE_EQUIPMENT_REGISTRY,
    TABLE_MAINTENANCE_SCHEDULE,
    TABLE_DEVIATION_REPORTS,
    TABLE_RECALL_CASES,
    TABLE_DOCUMENT_ARCHIVE,
    DEVIATION_ID_PREFIX,
    RECALL_ID_PREFIX,
    COMPLIANCE_QA_ROLES,
    COMPLIANCE_OPS_ROLES,
)
from src.services.document_engine import DocumentEngine
from src.services.document_storage import save_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compliance", tags=["compliance"])
_engine = DocumentEngine()


# ── helpers ────────────────────────────────────────────────────────────────────

def _qas_safe(query, *filters):
    """Apply a list of filter tuples to a Supabase query."""
    for f in filters:
        query = f(query)
    return query


def _require_qa(user: Dict) -> None:
    roles = {str(r).lower() for r in (user.get("roles") or [])}
    if not roles & COMPLIANCE_QA_ROLES:
        raise HTTPException(403, "QA or Admin role required.")


def _generate_sequential_id(prefix: str, table: str, id_col: str) -> str:
    """Generate DEV-YYYY-NNN or RECALL-YYYY-NNN style IDs."""
    year = date.today().year
    try:
        res = (
            db.table(table)
            .select(id_col)
            .like(id_col, f"{prefix}-{year}-%")
            .order(id_col, desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            last_num = int((rows[0][id_col] or "").rsplit("-", 1)[-1] or "0")
        else:
            last_num = 0
        return f"{prefix}-{year}-{last_num + 1:03d}"
    except Exception:
        return f"{prefix}-{year}-{uuid.uuid4().hex[:4].upper()}"


def _enrich_maintenance_with_equipment(rows: List[Dict]) -> List[Dict]:
    """Attach each maintenance row's equipment_registry details under an
    `equipment_registry` key, matching the shape _generate_maintenance_cert_bg
    already expects. The Supabase-style embedded-relation select this file
    used to call (`.select("*, equipment_registry(...)")`) isn't supported by
    this app's local TableQuery wrapper -- it's a flat SELECT builder with no
    join/embed parsing, so that string was passed through literally into the
    SQL and always failed. Because TableQuery swallows SELECT exceptions and
    returns an empty result rather than re-raising, every one of these calls
    silently returned zero rows instead of erroring visibly. Mirrors the
    rider/staff/document-archive enrichment pattern used elsewhere in this
    session's retrofit."""
    equipment_ids = list({r["equipment_id"] for r in rows if r.get("equipment_id")})
    if not equipment_ids:
        return rows
    try:
        eq_resp = db.table(TABLE_EQUIPMENT_REGISTRY).select("*").in_("id", equipment_ids).execute()
        eq_map = {e["id"]: e for e in (eq_resp.data or [])}
    except Exception:
        eq_map = {}
    for r in rows:
        r["equipment_registry"] = eq_map.get(r.get("equipment_id"))
    return rows


def _fetch_maintenance_with_equipment(schedule_id: str) -> Dict:
    """Single-row equivalent of _enrich_maintenance_with_equipment, for the
    complete/generate-certificate handlers that previously relied on the same
    broken embedded-relation select with .single()."""
    res = db.table(TABLE_MAINTENANCE_SCHEDULE).select("*").eq("id", schedule_id).single().execute()
    sched: Dict = res.data or {}
    if sched and sched.get("equipment_id"):
        try:
            eq_res = db.table(TABLE_EQUIPMENT_REGISTRY).select("*").eq("id", sched["equipment_id"]).single().execute()
            sched["equipment_registry"] = eq_res.data or None
        except Exception:
            sched["equipment_registry"] = None
    return sched


async def _archive_document(
    doc_type: str,
    title: str,
    file_bytes: bytes,
    filename: str,
    related_id: str,
    related_type: str,
    generated_by: str,
    fmt: str = "pdf",
) -> str:
    """Save generated document bytes, insert a document_archive row, and
    auto-ingest into the knowledge base.  Returns UUID."""
    doc_id = str(uuid.uuid4())
    storage = save_document(file_bytes, filename, doc_id)
    db.table(TABLE_DOCUMENT_ARCHIVE).insert({
        "id":              doc_id,
        "doc_type":        doc_type,
        "title":           title,
        "format":          fmt,
        "file_path":       storage.file_path,
        "cloud_key":       storage.cloud_key,
        "storage_backend": storage.storage_backend,
        "download_url":    storage.download_url,
        "generated_by":    generated_by,
        "related_id":      related_id,
        "related_type":    related_type,
    }).execute()

    # ── Auto-ingest into knowledge base ──────────────────────────────────────
    # Run in a fire-and-forget background thread so it never blocks the response.
    try:
        from src.services.knowledge_ingestor import ingest_bytes as _ingest_bytes
        import threading

        ingest_meta = {
            "document_type": doc_type,
            "department":    "quality",
            "source":        "generated",
            "title":         title,
            "related_id":    related_id,
            "related_type":  related_type,
            "archive_id":    doc_id,
        }
        # A thread rather than the event loop's executor: this also runs from sync handlers,
        # which have no running loop.
        threading.Thread(
            target=lambda: _ingest_bytes(file_bytes, filename, ingest_meta, source="generated"),
            daemon=True,
        ).start()
    except Exception as _exc:
        logger.warning("Knowledge base auto-ingest failed for %s: %s", filename, _exc)

    return doc_id


# ═══════════════════════════════════════════════════════════════════════════════
# Overall compliance status
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
def compliance_status(user=Depends(verify_jwt)):
    """Return aggregated compliance health metrics for the dashboard."""
    try:
        today = date.today().isoformat()

        overdue_audits = (
            db.table(TABLE_AUDIT_SCHEDULE)
            .select("id", count="exact")
            .eq("status", "overdue")
            .execute()
        ).count or 0

        open_deviations = (
            db.table(TABLE_DEVIATION_REPORTS)
            .select("id", count="exact")
            .neq("status", "closed")
            .execute()
        ).count or 0

        overdue_maint = (
            db.table(TABLE_MAINTENANCE_SCHEDULE)
            .select("id", count="exact")
            .eq("status", "overdue")
            .execute()
        ).count or 0

        active_recalls = (
            db.table(TABLE_RECALL_CASES)
            .select("id", count="exact")
            .not_in("status", ["closed"])
            .execute()
        ).count or 0

        missed_activities = (
            db.table(TABLE_COMPLIANCE_ACTIVITY)
            .select("id", count="exact")
            .eq("status", "missed")
            .execute()
        ).count or 0

        deductions = (
            overdue_audits * 8
            + open_deviations * 3
            + overdue_maint * 4
            + missed_activities * 5
        )
        score = max(0, 100 - deductions)

        return {
            "overall_compliance_score": score,
            "overdue_audits":           overdue_audits,
            "open_deviations":          open_deviations,
            "overdue_maintenance":      overdue_maint,
            "active_recalls":           active_recalls,
            "missed_activities":        missed_activities,
            "as_of":                    today,
        }
    except Exception as exc:
        logger.exception("compliance_status failed")
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Compliance Activities
# ═══════════════════════════════════════════════════════════════════════════════

class ActivityCreate(BaseModel):
    activity_name:     str
    scheduled_date:    date
    sop_reference:     Optional[str] = None
    department:        Optional[str] = None
    responsible_staff: Optional[str] = None
    notes:             Optional[str] = None


class ActivityUpdate(BaseModel):
    status:           Optional[str] = None
    completion_date:  Optional[date] = None
    completed_by:     Optional[str] = None
    notes:            Optional[str] = None


@router.get("/activities")
def list_activities(
    status: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = 50,
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_COMPLIANCE_ACTIVITY).select("*")
        if status:
            q = q.eq("status", status)
        if department:
            q = q.eq("department", department)
        res = q.order("scheduled_date", desc=True).limit(limit).execute()
        return {"activities": res.data or []}
    except Exception as exc:
        logger.exception("list_activities failed")
        raise HTTPException(500, str(exc))


@router.get("/activities/overdue")
def list_overdue_activities(user=Depends(verify_jwt)):
    try:
        today = date.today().isoformat()
        res = (
            db.table(TABLE_COMPLIANCE_ACTIVITY)
            .select("*")
            .in_("status", ["overdue", "missed"])
            .order("scheduled_date")
            .execute()
        )
        return {"overdue_activities": res.data or []}
    except Exception as exc:
        logger.exception("list_overdue_activities failed")
        raise HTTPException(500, str(exc))


@router.post("/activities", status_code=201)
def create_activity(body: ActivityCreate, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        row = db.table(TABLE_COMPLIANCE_ACTIVITY).insert({
            **body.model_dump(),
            "scheduled_date": body.scheduled_date.isoformat(),
            "status": "scheduled",
        }).execute()
        audit_event("compliance.activity.create", {"activity": body.activity_name}, actor_id=user.get("sub"), event_class="compliance")
        return {"activity": (row.data or [{}])[0]}
    except Exception as exc:
        logger.exception("create_activity failed")
        raise HTTPException(500, str(exc))


@router.put("/activities/{activity_id}")
def update_activity(activity_id: str, body: ActivityUpdate, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        if "completion_date" in update_data and isinstance(update_data["completion_date"], date):
            update_data["completion_date"] = update_data["completion_date"].isoformat()
        row = (
            db.table(TABLE_COMPLIANCE_ACTIVITY)
            .update(update_data)
            .eq("id", activity_id)
            .execute()
        )
        audit_event("compliance.activity.update", {"id": activity_id, "changes": update_data}, actor_id=user.get("sub"), event_class="compliance")
        return {"activity": (row.data or [{}])[0]}
    except Exception as exc:
        logger.exception("update_activity failed")
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Audit Schedule
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/audits")
def list_audits(
    year: Optional[int] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_AUDIT_SCHEDULE).select("*")
        q = q.eq("year", year or date.today().year)
        if department:
            q = q.eq("department", department)
        if status:
            q = q.eq("status", status)
        res = q.order("month_due").execute()
        audits = res.data or []

        # Resolve each completed audit's report_document_id to a real
        # download URL — the frontend has always expected a report_url that
        # was never provided, so the "download" action on a completed audit
        # could never appear. Mirrors the rider-enrichment pattern in
        # logistics.py's list_deliveries().
        doc_ids = list({a["report_document_id"] for a in audits if a.get("report_document_id")})
        if doc_ids:
            try:
                doc_resp = db.table(TABLE_DOCUMENT_ARCHIVE).select("id,download_url").in_("id", doc_ids).execute()
                doc_map = {d["id"]: d.get("download_url") for d in (doc_resp.data or [])}
            except Exception:
                doc_map = {}
            for a in audits:
                a["report_url"] = doc_map.get(a.get("report_document_id"))

        return {"audits": audits}
    except Exception as exc:
        logger.exception("list_audits failed")
        raise HTTPException(500, str(exc))


@router.get("/audits/upcoming")
def upcoming_audits(user=Depends(verify_jwt)):
    """Return audits with month_due within the next 30 days."""
    try:
        today = date.today()
        horizon = today + timedelta(days=30)
        current_year = today.year

        res = (
            db.table(TABLE_AUDIT_SCHEDULE)
            .select("*")
            .eq("year", current_year)
            .in_("status", ["scheduled"])
            .lte("month_due", horizon.month)
            .gte("month_due", today.month)
            .execute()
        )
        return {"upcoming_audits": res.data or []}
    except Exception as exc:
        logger.exception("upcoming_audits failed")
        raise HTTPException(500, str(exc))


@router.post("/audits/{audit_id}/start")
def start_audit(audit_id: str, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        row = (
            db.table(TABLE_AUDIT_SCHEDULE)
            .update({"status": "in_progress"})
            .eq("id", audit_id)
            .execute()
        )
        audit_event("compliance.audit.start", {"id": audit_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"audit": (row.data or [{}])[0]}
    except Exception as exc:
        raise HTTPException(500, str(exc))


class AuditComplete(BaseModel):
    auditor_name:    Optional[str] = None
    summary:         Optional[str] = None
    findings:        Optional[List[str]] = None
    observations:    Optional[List[str]] = None
    recommendations: Optional[List[str]] = None


@router.post("/audits/{audit_id}/complete")
def complete_audit(
    audit_id: str,
    body: AuditComplete,
    background_tasks: BackgroundTasks,
    user=Depends(verify_jwt),
):
    _require_qa(user)
    try:
        # Fetch audit row
        audit_res = (
            db.table(TABLE_AUDIT_SCHEDULE)
            .select("*")
            .eq("id", audit_id)
            .single()
            .execute()
        )
        audit_row: Dict = audit_res.data or {}
        if not audit_row:
            raise HTTPException(404, "Audit not found")

        # Update status
        db.table(TABLE_AUDIT_SCHEDULE).update({
            "status":       "completed",
            "completed_at": date.today().isoformat(),
        }).eq("id", audit_id).execute()

        # Generate report in background
        background_tasks.add_task(
            _generate_audit_report_bg,
            audit_id=audit_id,
            audit_row=audit_row,
            body_data=body.model_dump(),
            generated_by=user.get("username") or "system",
        )

        audit_event("compliance.audit.complete", {"id": audit_id}, actor_id=user.get("sub"), event_class="compliance")
        # A recurring audit puts its next occurrence on the calendar.
        next_id = None
        try:
            from src.services.quality_hub import schedule_next_audit
            next_id = schedule_next_audit(audit_id)
        except Exception:
            logger.exception("scheduling the next audit failed")
        return {"message": "Audit marked complete. Report is being generated.", "audit_id": audit_id, "next_audit_id": next_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("complete_audit failed")
        raise HTTPException(500, str(exc))


async def _generate_audit_report_bg(
    audit_id: str, audit_row: Dict, body_data: Dict, generated_by: str
):
    try:
        data = {**audit_row, **body_data}

        # Enrich report with relevant content from compliance knowledge base
        try:
            from src.services.knowledge_service import KnowledgeService
            _audit_type = data.get("audit_type", "audit")
            _dept       = data.get("department", "quality")
            _kb_result  = KnowledgeService().search(
                f"{_audit_type} audit procedure requirements {_dept}",
                department=_dept,
                document_type="audit_report",
                agent="audit_report_generator",
            )
            if _kb_result.context:
                data["kb_context"] = _kb_result.context
        except Exception as _exc:
            logger.warning("KB enrichment for audit report failed: %s", _exc)

        pdf_bytes = _engine.render_audit_report(data)
        filename = f"audit_report_{audit_id}.pdf"
        doc_id = await _archive_document(
            doc_type="audit_report",
            title=f"Audit Report — {audit_row.get('audit_type','Audit')} {audit_row.get('year','')}",
            file_bytes=pdf_bytes,
            filename=filename,
            related_id=audit_id,
            related_type="audit_schedule",
            generated_by=generated_by,
        )
        # Update audit with report reference
        db.table(TABLE_AUDIT_SCHEDULE).update({"report_document_id": doc_id}).eq("id", audit_id).execute()
        logger.info("Audit report generated: doc_id=%s", doc_id)
    except Exception as exc:
        logger.exception("_generate_audit_report_bg failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Standalone audit report generation — does NOT change audit status
# ─────────────────────────────────────────────────────────────────────────────

class AuditReportRequest(BaseModel):
    auditor_name:    Optional[str]       = None
    summary:         Optional[str]       = None
    findings:        Optional[List[str]] = None
    observations:    Optional[List[str]] = None
    recommendations: Optional[List[str]] = None
    score:           Optional[int]       = None


@router.post("/audits/{audit_id}/generate-report")
def generate_audit_report(
    audit_id: str,
    body: AuditReportRequest,
    background_tasks: BackgroundTasks,
    user=Depends(verify_jwt),
):
    """Generate an audit report PDF without changing the audit\u2019s status.

    Separate from /audits/{id}/complete so users can trigger or re-trigger
    a report at any point. Required roles: admin, quality, qa.
    """
    _require_qa(user)
    try:
        audit_res = (
            db.table(TABLE_AUDIT_SCHEDULE)
            .select("*")
            .eq("id", audit_id)
            .single()
            .execute()
        )
        audit_row: Dict = audit_res.data or {}
        if not audit_row:
            raise HTTPException(404, "Audit not found")

        background_tasks.add_task(
            _generate_audit_report_bg,
            audit_id=audit_id,
            audit_row=audit_row,
            body_data=body.model_dump(exclude_none=True),
            generated_by=user.get("username") or "system",
        )
        audit_event("compliance.audit.report.generate", {"id": audit_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"message": "Audit report generation queued.", "audit_id": audit_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_audit_report failed")
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Deviations
# ═══════════════════════════════════════════════════════════════════════════════

class DeviationCreate(BaseModel):
    classification:          str = "minor"
    trigger_type:            str
    trigger_ref:             Optional[str] = None
    observation:             str
    impact_assessment:       Optional[str] = None
    recommendations:         Optional[str] = None
    responsible_department:  str
    responsible_person:      Optional[str] = None
    capa_actions:            Optional[List[Dict]] = None


class DeviationUpdate(BaseModel):
    status:                  Optional[str] = None
    impact_assessment:       Optional[str] = None
    recommendations:         Optional[str] = None
    capa_actions:            Optional[List[Dict]] = None
    responsible_person:      Optional[str] = None


@router.get("/deviations")
def list_deviations(
    status: Optional[str] = None,
    classification: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = 50,
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_DEVIATION_REPORTS).select("*")
        if status:
            q = q.eq("status", status)
        if classification:
            q = q.eq("classification", classification)
        if department:
            q = q.eq("responsible_department", department)
        res = q.order("created_at", desc=True).limit(limit).execute()
        return {"deviations": res.data or []}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/deviations/{deviation_id}")
def get_deviation(deviation_id: str, user=Depends(verify_jwt)):
    try:
        res = (
            db.table(TABLE_DEVIATION_REPORTS)
            .select("*")
            .eq("id", deviation_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "Deviation not found")
        return {"deviation": res.data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/deviations", status_code=201)
def create_deviation(body: DeviationCreate, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        dev_id = _generate_sequential_id(DEVIATION_ID_PREFIX, TABLE_DEVIATION_REPORTS, "deviation_id")
        row_data = {
            **body.model_dump(),
            "deviation_id":             dev_id,
            "investigation_start_date": date.today().isoformat(),
            "status":                   "open",
            "capa_actions":             body.capa_actions or [],
        }
        row = db.table(TABLE_DEVIATION_REPORTS).insert(row_data).execute()
        audit_event("compliance.deviation.create", {"deviation_id": dev_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"deviation": (row.data or [{}])[0]}
    except Exception as exc:
        logger.exception("create_deviation failed")
        raise HTTPException(500, str(exc))


@router.put("/deviations/{deviation_id}")
def update_deviation(deviation_id: str, body: DeviationUpdate, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        if update_data.get("status") == "closed":
            update_data["closed_at"] = date.today().isoformat()
        row = (
            db.table(TABLE_DEVIATION_REPORTS)
            .update(update_data)
            .eq("id", deviation_id)
            .execute()
        )
        audit_event("compliance.deviation.update", {"id": deviation_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"deviation": (row.data or [{}])[0]}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/deviations/{deviation_id}/generate-report")
async def generate_deviation_report(deviation_id: str, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        res = (
            db.table(TABLE_DEVIATION_REPORTS)
            .select("*")
            .eq("id", deviation_id)
            .single()
            .execute()
        )
        deviation: Dict = res.data
        if not deviation:
            raise HTTPException(404, "Deviation not found")

        # Enrich report with relevant content from compliance knowledge base
        try:
            from src.services.knowledge_service import KnowledgeService
            _dept      = deviation.get("responsible_department", "quality")
            _kb_result = KnowledgeService().search(
                f"deviation CAPA corrective action {_dept}",
                department=_dept,
                document_type="deviation_report",
                agent="deviation_report_generator",
            )
            if _kb_result.context:
                deviation = dict(deviation)  # unfreeze if needed
                deviation["kb_context"] = _kb_result.context
        except Exception as _exc:
            logger.warning("KB enrichment for deviation report failed: %s", _exc)

        pdf_bytes = _engine.render_deviation_report(deviation)
        filename = f"deviation_report_{deviation.get('deviation_id', deviation_id)}.pdf"
        doc_id = await _archive_document(
            doc_type="deviation_report",
            title=f"Deviation Report — {deviation.get('deviation_id')}",
            file_bytes=pdf_bytes,
            filename=filename,
            related_id=deviation_id,
            related_type="deviation_reports",
            generated_by=user.get("username") or "system",
        )
        db.table(TABLE_DEVIATION_REPORTS).update({"report_document_id": doc_id}).eq("id", deviation_id).execute()
        audit_event("compliance.deviation.report.generate", {"id": deviation_id, "doc_id": doc_id}, actor_id=user.get("sub"), event_class="compliance")

        return {"doc_id": doc_id, "message": "Deviation report generated successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_deviation_report failed")
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Equipment Registry
# ═══════════════════════════════════════════════════════════════════════════════

class EquipmentCreate(BaseModel):
    equipment_name:            str
    equipment_type:            str
    location:                  str
    serial_number:             Optional[str] = None
    model:                     Optional[str] = None
    calibration_interval_days: Optional[int] = None
    maintenance_interval_days: Optional[int] = None
    notes:                     Optional[str] = None


@router.get("/equipment")
def list_equipment(
    equipment_type: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_EQUIPMENT_REGISTRY).select("*")
        if equipment_type:
            q = q.eq("equipment_type", equipment_type)
        if status:
            q = q.eq("status", status)
        else:
            q = q.neq("status", "decommissioned")
        res = q.order("equipment_name").execute()
        return {"equipment": res.data or []}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/equipment/{equipment_id}")
def get_equipment(equipment_id: str, user=Depends(verify_jwt)):
    try:
        equip_res = (
            db.table(TABLE_EQUIPMENT_REGISTRY)
            .select("*")
            .eq("id", equipment_id)
            .single()
            .execute()
        )
        maint_res = (
            db.table(TABLE_MAINTENANCE_SCHEDULE)
            .select("*")
            .eq("equipment_id", equipment_id)
            .order("next_maintenance_date")
            .limit(5)
            .execute()
        )
        return {
            "equipment":    equip_res.data,
            "maintenance":  maint_res.data or [],
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/equipment", status_code=201)
def register_equipment(body: EquipmentCreate, user=Depends(verify_jwt)):
    _require_qa(user)
    try:
        row = db.table(TABLE_EQUIPMENT_REGISTRY).insert({
            **body.model_dump(),
            "status": "active",
        }).execute()
        audit_event("compliance.equipment.register", {"name": body.equipment_name}, actor_id=user.get("sub"), event_class="compliance")
        return {"equipment": (row.data or [{}])[0]}
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Maintenance Schedule
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/maintenance")
def list_maintenance(
    status: Optional[str] = None,
    maintenance_type: Optional[str] = None,
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_MAINTENANCE_SCHEDULE).select("*")
        if status:
            q = q.eq("status", status)
        if maintenance_type:
            q = q.eq("maintenance_type", maintenance_type)
        res = q.order("next_maintenance_date").execute()
        return {"maintenance": _enrich_maintenance_with_equipment(res.data or [])}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/maintenance/overdue")
def overdue_maintenance(user=Depends(verify_jwt)):
    try:
        res = (
            db.table(TABLE_MAINTENANCE_SCHEDULE)
            .select("*")
            .eq("status", "overdue")
            .order("next_maintenance_date")
            .execute()
        )
        return {"overdue_maintenance": _enrich_maintenance_with_equipment(res.data or [])}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/maintenance/upcoming")
def upcoming_maintenance(window_days: int = 14, user=Depends(verify_jwt)):
    try:
        today = date.today()
        horizon = (today + timedelta(days=window_days)).isoformat()
        res = (
            db.table(TABLE_MAINTENANCE_SCHEDULE)
            .select("*")
            .eq("status", "scheduled")
            .lte("next_maintenance_date", horizon)
            .gte("next_maintenance_date", today.isoformat())
            .order("next_maintenance_date")
            .execute()
        )
        return {"upcoming_maintenance": _enrich_maintenance_with_equipment(res.data or [])}
    except Exception as exc:
        raise HTTPException(500, str(exc))


class MaintenanceComplete(BaseModel):
    performed_by:      str
    completion_notes:  Optional[str] = None
    next_maintenance_date: Optional[date] = None


@router.post("/maintenance/{schedule_id}/complete")
def complete_maintenance(
    schedule_id: str,
    body: MaintenanceComplete,
    background_tasks: BackgroundTasks,
    user=Depends(verify_jwt),
):
    _require_qa(user)
    try:
        sched = _fetch_maintenance_with_equipment(schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")

        today = date.today()
        interval = int(sched.get("interval_days") or 90)
        next_date = body.next_maintenance_date or (today + timedelta(days=interval))

        db.table(TABLE_MAINTENANCE_SCHEDULE).update({
            "status":                 "completed",
            "last_maintenance_date":  today.isoformat(),
            "next_maintenance_date":  next_date.isoformat(),
            "performed_by":           body.performed_by,
            "completion_notes":       body.completion_notes,
            "completed_at":           today.isoformat(),
        }).eq("id", schedule_id).execute()

        # Update equipment last_maintenance_date
        if sched.get("equipment_id"):
            db.table(TABLE_EQUIPMENT_REGISTRY).update({
                "last_maintenance_date": today.isoformat(),
            }).eq("id", sched["equipment_id"]).execute()

        # Generate certificate in background
        background_tasks.add_task(
            _generate_maintenance_cert_bg,
            schedule_id=schedule_id,
            sched=sched,
            body_data=body.model_dump(),
            generated_by=user.get("username") or "system",
        )

        audit_event("compliance.maintenance.complete", {"schedule_id": schedule_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"message": "Maintenance recorded. Certificate being generated.", "schedule_id": schedule_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("complete_maintenance failed")
        raise HTTPException(500, str(exc))


async def _generate_maintenance_cert_bg(
    schedule_id: str, sched: Dict, body_data: Dict, generated_by: str
):
    try:
        equip = sched.get("equipment_registry") or {}
        data = {
            **equip,
            **body_data,
            "certificate_id": f"CERT-{schedule_id[:8].upper()}",
            "maintenance_type": sched.get("maintenance_type"),
            "last_maintenance_date": date.today().isoformat(),
            "next_maintenance_date": body_data.get("next_maintenance_date") or "",
        }
        pdf_bytes = _engine.render_maintenance_certificate(data)
        filename = f"maintenance_cert_{schedule_id}.pdf"
        doc_id = await _archive_document(
            doc_type="maintenance_report",
            title=f"Maintenance Certificate — {equip.get('equipment_name', 'Equipment')}",
            file_bytes=pdf_bytes,
            filename=filename,
            related_id=schedule_id,
            related_type="maintenance_schedule",
            generated_by=generated_by,
        )
        db.table(TABLE_MAINTENANCE_SCHEDULE).update(
            {"certificate_document_id": doc_id}
        ).eq("id", schedule_id).execute()
        logger.info("Maintenance certificate generated: doc_id=%s", doc_id)
    except Exception as exc:
        logger.exception("_generate_maintenance_cert_bg failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Standalone maintenance certificate generation — does NOT change task status
# ─────────────────────────────────────────────────────────────────────────────

class MaintenanceCertRequest(BaseModel):
    performed_by:          str
    maintenance_type:      Optional[str]  = None
    completion_notes:      Optional[str]  = None
    next_maintenance_date: Optional[date] = None


@router.post("/maintenance/{schedule_id}/generate-certificate")
def generate_maintenance_certificate(
    schedule_id: str,
    body: MaintenanceCertRequest,
    background_tasks: BackgroundTasks,
    user=Depends(verify_jwt),
):
    """Generate a maintenance completion certificate PDF without altering task status.

    Users can trigger this from the Maintenance tab at any time.
    Required roles: admin, quality, qa.
    """
    _require_qa(user)
    try:
        sched = _fetch_maintenance_with_equipment(schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")

        background_tasks.add_task(
            _generate_maintenance_cert_bg,
            schedule_id=schedule_id,
            sched=sched,
            body_data=body.model_dump(exclude_none=True),
            generated_by=user.get("username") or "system",
        )
        audit_event("compliance.maintenance.certificate.generate", {"schedule_id": schedule_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"message": "Certificate generation queued.", "schedule_id": schedule_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_maintenance_certificate failed")
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Recalls
# ═══════════════════════════════════════════════════════════════════════════════

class RecallCreate(BaseModel):
    batch_number:         str
    product_name:         str
    recall_reason:        str
    scope:                str = "voluntary"
    severity:             str = "major"
    nafdac_notified:      bool = False
    regulatory_authority: Optional[str] = "NAFDAC"
    distribution_data:    Optional[List[Dict]] = None


class RecallUpdate(BaseModel):
    status:            Optional[str] = None
    distribution_data: Optional[List[Dict]] = None


@router.get("/recalls")
def list_recalls(
    status: Optional[str] = None,
    limit: int = 50,
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_RECALL_CASES).select("*")
        if status:
            q = q.eq("status", status)
        res = q.order("initiation_date", desc=True).limit(limit).execute()
        return {"recalls": res.data or []}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/recalls/{recall_id}")
def get_recall(recall_id: str, user=Depends(verify_jwt)):
    try:
        res = (
            db.table(TABLE_RECALL_CASES)
            .select("*")
            .eq("id", recall_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "Recall not found")
        return {"recall": res.data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/recalls", status_code=201)
def initiate_recall(
    body: RecallCreate,
    background_tasks: BackgroundTasks,
    user=Depends(verify_jwt),
):
    """Initiate a recall through the shared quality service: the ACE Books recall opens with it
    (batch frozen, buyers traced), then the recall notice PDF is generated."""
    _require_qa(user)
    from src.services import quality_hub as qh
    from src.fin.errors import FinError
    try:
        rec = qh.initiate_recall(user, body.model_dump())
    except qh.QualityError as exc:
        raise HTTPException(409, str(exc))
    except FinError as exc:
        raise HTTPException(exc.status, exc.message)
    row = (db.table(TABLE_RECALL_CASES).select("*").eq("id", rec["id"]).limit(1).execute().data or [{}])[0]
    background_tasks.add_task(
        _generate_recall_notice_bg,
        db_id=rec["id"],
        recall_data=row,
        generated_by=user.get("username") or "system",
    )
    return {"recall": rec}


@router.put("/recalls/{recall_id}")
def update_recall(recall_id: str, body: RecallUpdate, user=Depends(verify_jwt)):
    _require_qa(user)
    from src.services import quality_hub as qh
    try:
        return {"recall": qh.update_recall(user, recall_id, body.model_dump(exclude_none=True))}
    except qh.QualityError as exc:
        raise HTTPException(409, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.post("/recalls/{recall_id}/generate-documents")
def generate_recall_documents(
    recall_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(verify_jwt),
):
    """Generate all three recall document types: Notice, Investigation, Distribution Trace."""
    _require_qa(user)
    try:
        res = (
            db.table(TABLE_RECALL_CASES)
            .select("*")
            .eq("id", recall_id)
            .single()
            .execute()
        )
        recall: Dict = res.data
        if not recall:
            raise HTTPException(404, "Recall not found")

        background_tasks.add_task(
            _generate_all_recall_docs_bg,
            recall_id=recall_id,
            recall=recall,
            generated_by=user.get("username") or "system",
        )
        audit_event("compliance.recall.docs.generate", {"id": recall_id}, actor_id=user.get("sub"), event_class="compliance")
        return {"message": "Recall documents are being generated.", "recall_id": recall_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


async def _generate_recall_notice_bg(db_id: str, recall_data: Dict, generated_by: str):
    try:
        pdf_bytes = _engine.render_recall_notice(recall_data)
        filename = f"recall_notice_{recall_data.get('recall_id', db_id)}.pdf"
        doc_id = await _archive_document(
            doc_type="recall_notice",
            title=f"Recall Notice — {recall_data.get('recall_id')} — {recall_data.get('product_name')}",
            file_bytes=pdf_bytes,
            filename=filename,
            related_id=db_id,
            related_type="recall_cases",
            generated_by=generated_by,
        )
        db.table(TABLE_RECALL_CASES).update({"notice_document_id": doc_id}).eq("id", db_id).execute()
        logger.info("Recall notice generated: doc_id=%s", doc_id)
    except Exception as exc:
        logger.exception("_generate_recall_notice_bg failed: %s", exc)


async def _generate_all_recall_docs_bg(recall_id: str, recall: Dict, generated_by: str):
    """Generate Notice, Investigation, and Distribution Trace documents."""
    try:
        recall_code = recall.get("recall_id", recall_id)
        product     = recall.get("product_name", "Product")

        # 1. Notice
        notice_bytes = _engine.render_recall_notice(recall)
        notice_doc = await _archive_document(
            "recall_notice", f"Recall Notice — {recall_code} — {product}",
            notice_bytes, f"recall_notice_{recall_code}.pdf",
            recall_id, "recall_cases", generated_by,
        )

        # 2. Investigation
        invest_bytes = _engine.render_recall_investigation(recall)
        invest_doc = await _archive_document(
            "recall_investigation", f"Recall Investigation — {recall_code}",
            invest_bytes, f"recall_investigation_{recall_code}.pdf",
            recall_id, "recall_cases", generated_by,
        )

        # 3. Distribution Trace (XLSX)
        trace_bytes = _engine.render_recall_distribution_trace(recall)
        trace_doc = await _archive_document(
            "recall_distribution_trace", f"Distribution Trace — {recall_code}",
            trace_bytes, f"distribution_trace_{recall_code}.xlsx",
            recall_id, "recall_cases", generated_by, fmt="xlsx",
        )

        db.table(TABLE_RECALL_CASES).update({
            "notice_document_id":        notice_doc,
            "investigation_document_id": invest_doc,
            "trace_document_id":         trace_doc,
        }).eq("id", recall_id).execute()
        logger.info("All recall documents generated for recall_id=%s", recall_id)
    except Exception as exc:
        logger.exception("_generate_all_recall_docs_bg failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# SOP Registry + DOCX Ingest (Option B)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/sop")
def list_sops(
    category: Optional[str] = None,
    status: Optional[str] = "active",
    user=Depends(verify_jwt),
):
    try:
        q = db.table(TABLE_SOP_REGISTRY).select("*")
        if category:
            q = q.eq("category", category)
        if status:
            q = q.eq("status", status)
        res = q.order("sop_id").execute()
        return {"data": res.data or []}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/sop/ingest-docx", status_code=202)
async def ingest_docx(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    sop_id: Optional[str] = None,
    title: Optional[str] = None,
    category: Optional[str] = "general",
    owner_department: Optional[str] = None,
    version: Optional[str] = "1.0",
    user=Depends(verify_jwt),
):
    """Upload and parse a DOCX file to extract SOP content and index it into the RAG QnA table.

    Processing steps:
      1. Extract full text from docx using python-docx
      2. Chunk text into paragraph-level segments (skip blanks)
      3. For each chunk: generate embedding + insert into qna_pairs with doc_type='sop'
      4. Create or update sop_registry entry

    Returns immediately; actual processing runs as a background task.
    """
    _require_qa(user)

    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Only .docx files are accepted.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB max
        raise HTTPException(413, "File too large (max 10 MB).")

    resolved_sop_id   = sop_id or f"SOP-UPLOAD-{uuid.uuid4().hex[:6].upper()}"
    resolved_title    = title or file.filename.replace(".docx", "").replace("_", " ").title()
    resolved_dept     = owner_department or "Quality Assurance"

    background_tasks.add_task(
        _ingest_docx_bg,
        file_bytes=content,
        filename=file.filename,
        sop_id=resolved_sop_id,
        title=resolved_title,
        category=category,
        owner_department=resolved_dept,
        version=version,
        uploaded_by=user.get("username") or "system",
    )

    audit_event("compliance.sop.ingest", {
        "filename": file.filename,
        "sop_id":   resolved_sop_id,
    }, actor_id=user.get("sub"), event_class="compliance")
    return {
        "message":  "SOP document accepted for processing.",
        "sop_id":   resolved_sop_id,
        "filename": file.filename,
    }


async def _ingest_docx_bg(
    file_bytes: bytes,
    filename: str,
    sop_id: str,
    title: str,
    category: str,
    owner_department: str,
    version: str,
    uploaded_by: str,
) -> None:
    """Background task: parse DOCX, embed chunks, store in qna_pairs, update sop_registry."""
    try:
        from docx import Document as DocxDocument  # python-docx
        from src.embed_proxy import get_embedding  # existing embedding proxy

        # ── Step 1: extract text chunks ──────────────────────────────────────
        doc = DocxDocument(io.BytesIO(file_bytes))
        chunks: List[str] = []
        current_chunk: List[str] = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
            else:
                current_chunk.append(text)
                # Split at natural boundaries (heading styles or length)
                if para.style.name.startswith("Heading") or len(" ".join(current_chunk)) > 600:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # Remove empty / very short chunks
        chunks = [c for c in chunks if len(c) > 30]

        if not chunks:
            logger.warning("DOCX ingest: no text chunks extracted from %s", filename)
            return

        # ── Step 2: save original docx ──────────────────────────────────────
        doc_id = str(uuid.uuid4())
        storage = save_document(file_bytes, filename, doc_id)

        # ── Step 3: upsert sop_registry ──────────────────────────────────────
        existing = (
            db.table(TABLE_SOP_REGISTRY)
            .select("id")
            .eq("sop_id", sop_id)
            .execute()
        )
        sop_row = {
            "sop_id":           sop_id,
            "title":            title,
            "category":         category,
            "version":          version,
            "owner_department": owner_department,
            "status":           "active",
            "document_path":    storage.file_path or storage.cloud_key,
        }
        if existing.data:
            db.table(TABLE_SOP_REGISTRY).update(sop_row).eq("sop_id", sop_id).execute()
        else:
            db.table(TABLE_SOP_REGISTRY).insert({**sop_row, "effective_from": date.today().isoformat()}).execute()

        # ── Step 4: embed chunks and upsert into qna_pairs ────────────────────
        for i, chunk in enumerate(chunks):
            try:
                embedding = get_embedding(chunk)
                if not embedding or len(embedding) != 384:
                    logger.warning("Skipping chunk %d in %s — invalid embedding length", i, sop_id)
                    continue

                qna_row = {
                    "question":       f"[{sop_id}] {title} (chunk {i + 1})",
                    "answer":         chunk,
                    "embedding":      embedding,
                    "doc_type":       "sop",
                    "sop_reference":  sop_id,
                    "document_title": title,
                    "chunk_index":    i,
                }
                db.table("qna_pairs").insert(qna_row).execute()
            except Exception as chunk_exc:
                logger.warning("Failed to embed chunk %d of %s: %s", i, sop_id, chunk_exc)

        logger.info(
            "DOCX ingest complete: sop_id=%s, chunks_indexed=%d/%d",
            sop_id, len(chunks), len(chunks),
        )
    except Exception as exc:
        logger.exception("_ingest_docx_bg failed for %s: %s", filename, exc)
