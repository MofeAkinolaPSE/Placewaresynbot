"""Reports router â€” template-driven, session-based enterprise report generation.

Endpoints:
  POST /reports/session                    â€” Create a new report session (step 1 of wizard)
  PUT  /reports/session/{id}/scope         â€” Update scope params (step 2-3 of wizard)
  GET  /reports/session/{id}               â€” Get session state
  POST /reports/session/{id}/generate      â€” Trigger generation from a session
  POST /reports/{report_id}/approve        â€” Approve a completed report

  POST /reports/generate                   â€” [legacy] Direct generate (no session)
  POST /reports/generate/docx              â€” [legacy] Direct generate â†’ .docx download
  GET  /reports/history                    â€” List past stored reports
  GET  /reports/history/{id}               â€” Full report detail
  GET  /reports/history/{id}/docx          â€” Download stored report as .docx

  GET  /reports/types                      â€” List all supported report types
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.db import db
from src.middleware import verify_jwt
from src.report_templates import (
    REPORT_TEMPLATE_REGISTRY,
    get_all_report_types,
    get_template,
    TEMPLATE_VERSION,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


# â”€â”€ Request / Response models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ReportRequest(BaseModel):
    report_type: Optional[str] = Field(
        None,
        description=(
            "Optional report type override. One of: deviation, maintenance, compliance, "
            "audit, financial, inventory, executive, sales, payroll, pl, ar_aging, "
            "frontdesk, invoice"
        ),
    )
    intent_text: Optional[str] = Field(
        None,
        description="Natural-language description of what report is needed. Used when report_type is absent.",
    )


class ScopeParams(BaseModel):
    date_from: Optional[str]       = Field(None, description="ISO date string YYYY-MM-DD")
    date_to: Optional[str]         = Field(None, description="ISO date string YYYY-MM-DD")
    department: Optional[str]      = None
    entity_filter: Optional[str]   = None
    sku_filter: Optional[str]      = None
    customer_filter: Optional[str] = None
    currency: Optional[str]        = None
    custom_notes: Optional[str]    = Field(None, max_length=4000)
    # Invoice-specific
    client_name: Optional[str]     = None
    client_address: Optional[str]  = None
    client_email: Optional[str]    = None
    invoice_date: Optional[str]    = None
    due_date: Optional[str]        = None
    vat_rate: Optional[float]      = None
    payment_terms: Optional[str]   = None
    bank_details: Optional[str]    = None
    line_items: Optional[List[Dict[str, Any]]] = None
    # Other filters
    low_stock_threshold: Optional[float] = None
    sales_rep: Optional[str]       = None
    region: Optional[str]          = None
    location: Optional[str]        = None
    equipment_type: Optional[str]  = None
    standard: Optional[str]        = None
    audit_type: Optional[str]      = None
    severity_filter: Optional[str] = None
    compare_period: Optional[str]  = None
    audience: Optional[str]        = None
    warehouse: Optional[str]       = None
    staff_member: Optional[str]    = None


class SessionUpdateRequest(BaseModel):
    scope: ScopeParams
    evidence_notes: Optional[str] = Field(None, max_length=4000)


class ReportSectionResult(BaseModel):
    section_id: str
    title: str
    content: str
    confidence_score: float
    status: str
    order: int


class TraceabilityMeta(BaseModel):
    template_version: str
    rag_hits: int
    data_rows: int
    past_reports_used: int
    section_count: int


class ReportResponse(BaseModel):
    report_type: str
    section_title: str
    full_report: str
    findings: List[str]
    recommendations: List[str]
    quality_score: float
    rag_hits: int
    data_rows: int
    status: str
    # Extended fields (present when session-based or template-driven)
    session_id: Optional[str]          = None
    report_memory_id: Optional[str]    = None
    sections: Optional[List[ReportSectionResult]] = None
    traceability: Optional[TraceabilityMeta]       = None
    template_version: Optional[str]    = None


# -- DOCX builders -----------------------------------------------------------
# Both delegate to src.services.docx_engine, the single branded Word renderer
# for the whole app (companion to document_engine.py for PDFs). These used to
# be two independent hand-rolled python-docx builders with duplicated brand
# constants and an ad-hoc markdown parser that leaked backticks, pipe tables
# and '####' into the page, and numbered every list from one shared sequence.

def _build_report_docx(
    full_report: str,
    section_title: str,
    report_type: str,
    section_results: Optional[List[Dict[str, Any]]] = None,
    scope_params: Optional[Dict[str, Any]] = None,
    approved: bool = False,
) -> bytes:
    """Branded narrative report: cover, contents, sections, sign-off."""
    from src.services import docx_engine as E

    scope = scope_params or {}
    doc = E.new_document()
    E.add_logo_header(doc)
    E.add_footer(doc)

    E.add_cover(
        doc,
        title=section_title or report_type.replace("_", " ").title(),
        subtitle="Enterprise AI Intelligence Report",
        badge="FINAL" if approved else "DRAFT",
        badge_ok=approved,
        meta=[
            ("Report Type", report_type.replace("_", " ").title()),
            ("About", scope["subject"]) if scope.get("subject") else
            ("Report Period", f"{scope.get('date_from', 'N/A')} to {scope.get('date_to', 'N/A')}"),
            ("Entity / Scope", scope.get("client_name") or scope.get("entity_filter") or "Placeware Nigeria"),
            ("Generated", datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")),
            ("Prepared By", "ACE - Placeware Nigeria AI Executive Intelligence"),
            ("Classification", "CONFIDENTIAL - For Authorised Recipients Only"),
        ],
    )
    doc.add_page_break()

    ordered = sorted(section_results or [], key=lambda s: s.get("order", 0))

    if ordered:
        E.add_contents(doc, [s.get("title", "") for s in ordered if s.get("title")])
        for sec in ordered:
            title = (sec.get("title") or "").strip()
            if title:
                head = doc.add_paragraph(style="ACE H1")
                head.add_run(title)
            E.render_markdown(doc, sec.get("content") or "")
            score = sec.get("confidence_score")
            if score is not None:
                cap = doc.add_paragraph(style="ACE Caption")
                cap.add_run(f"Section confidence: {round(float(score) * 100)}%")
    else:
        # No structured sections (legacy/single-pass path) -- render the
        # assembled markdown directly rather than dropping it.
        titles = [
            ln.lstrip("# ").strip()
            for ln in (full_report or "").split("\n")
            if ln.startswith("## ")
        ]
        E.add_contents(doc, titles)
        E.render_markdown(doc, full_report or "")

    E.add_signoff(doc)
    return E.serialize(doc)


def _build_invoice_docx(scope_params: Dict[str, Any], service_description: str = "") -> bytes:
    """Branded tax invoice. Monetary values are computed from line_items."""
    from src.services import docx_engine as E

    scope = scope_params or {}
    currency = scope.get("currency", "NGN")

    doc = E.new_document()
    E.add_logo_header(doc)
    E.add_footer(doc, "Placeware Nigeria Limited  |  Thank you for your business.")

    E.add_cover(
        doc,
        title="Tax Invoice",
        subtitle="Placeware Nigeria Limited",
        meta=[
            ("Invoice No", scope.get("invoice_number") or f"INVOICE-{datetime.utcnow().strftime('%Y%m%d%H%M')}"),
            ("Invoice Date", scope.get("invoice_date", "")),
            ("Due Date", scope.get("due_date", "")),
            ("Currency", currency),
        ],
    )

    E.add_table(doc, [
        ["Bill To", "Details"],
        [scope.get("client_name", ""), scope.get("client_address", "")],
        [scope.get("client_email", ""), scope.get("client_phone", "")],
    ])

    if service_description:
        head = doc.add_paragraph(style="ACE H2")
        head.add_run("Description of Services")
        E.render_markdown(doc, service_description)

    line_items: List[Dict] = scope.get("line_items") or []
    head = doc.add_paragraph(style="ACE H2")
    head.add_run("Invoice Items")

    rows = [["Description", "Qty", "Unit Price", "Total"]]
    subtotal = 0.0
    for item in line_items:
        qty = float(item.get("qty", item.get("quantity", 1)) or 0)
        price = float(item.get("unit_price", item.get("price", 0)) or 0)
        total = qty * price
        subtotal += total
        rows.append([
            str(item.get("description", item.get("name", ""))),
            f"{qty:g}",
            f"{price:,.2f}",
            f"{total:,.2f}",
        ])
    if not line_items:
        rows.append(["", "", "", ""])
    E.add_table(doc, rows)

    vat_rate = float(scope.get("vat_rate") or 0.0)
    vat_amt = subtotal * vat_rate / 100
    E.add_table(doc, [
        ["Summary", "Amount"],
        ["Subtotal", f"{currency} {subtotal:,.2f}"],
        [f"VAT ({scope.get('vat_rate', 0)}%)", f"{currency} {vat_amt:,.2f}"],
        ["TOTAL DUE", f"{currency} {subtotal + vat_amt:,.2f}"],
    ])

    for label, value in (
        ("Payment Terms", scope.get("payment_terms")),
        ("Bank Details", scope.get("bank_details")),
        ("Additional Notes", scope.get("custom_notes")),
    ):
        if value:
            h = doc.add_paragraph(style="ACE H2")
            h.add_run(label)
            E.render_markdown(doc, str(value))

    return E.serialize(doc)


# â”€â”€ Shared agent runner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run_agent(
    body: ReportRequest,
    session_id: Optional[str] = None,
    scope_params: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Run the ReportGenerationAgent. Returns (insight, full_report, section_title, report_type)."""
    intent_text = body.intent_text or (
        f"generate {body.report_type} report" if body.report_type else "generate executive report"
    )
    try:
        from src.agent_registry import get_agent
        agent = get_agent("report_generation_agent", context={
            "intent_text":   intent_text,
            "report_type":   body.report_type,
            "session_id":    session_id,
            "scope_params":  scope_params or {},
            "actor_id":      "api_reports",
            "simulation":    False,
            "enable_memory": True,
        })
        if agent is None:
            raise HTTPException(status_code=503, detail="ReportGenerationAgent not available")
        insight = agent.run()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("report agent failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    metrics     = insight.metrics or {}
    full_report = metrics.get("full_report", "") or "\n".join(insight.findings or [])
    section_title = metrics.get("section_title", "Intelligence Report")
    resolved_type = metrics.get("report_type", body.report_type or "executive")
    return insight, full_report, section_title, resolved_type


def _insight_to_response(
    insight: Any,
    full_report: str,
    section_title: str,
    report_type: str,
    session_id: Optional[str] = None,
) -> ReportResponse:
    """Convert an Insight object into a ReportResponse."""
    metrics = insight.metrics or {}
    raw_sections = metrics.get("section_results", [])
    sections = [ReportSectionResult(**s) for s in raw_sections] if raw_sections else None

    traceability = TraceabilityMeta(
        template_version=metrics.get("template_version", TEMPLATE_VERSION),
        rag_hits=int(metrics.get("rag_hits", 0)),
        data_rows=int(metrics.get("data_rows", 0)),
        past_reports_used=int(metrics.get("past_reports_used", 0)),
        section_count=len(raw_sections),
    )

    return ReportResponse(
        report_type=report_type,
        section_title=section_title,
        full_report=full_report,
        findings=insight.findings or [],
        recommendations=insight.recommendations or [],
        quality_score=float(metrics.get("quality_score", 0.0)),
        rag_hits=int(metrics.get("rag_hits", 0)),
        data_rows=int(metrics.get("data_rows", 0)),
        status="success",
        session_id=session_id or metrics.get("session_id"),
        report_memory_id=metrics.get("report_memory_id"),
        sections=sections,
        traceability=traceability,
        template_version=metrics.get("template_version", TEMPLATE_VERSION),
    )


# â”€â”€ Session endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/types")
async def list_report_types(_user: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    """Return all supported report types with their client-facing names and required scope fields."""
    from src.report_templates import get_required_scope_fields
    result = []
    for rt_info in get_all_report_types():
        rtype = rt_info["type"]
        result.append({
            "type": rtype,
            "name": rt_info["name"],
            "required_scope_fields": get_required_scope_fields(rtype),
            "is_invoice": REPORT_TEMPLATE_REGISTRY[rtype].get("is_invoice", False),
        })
    return {"report_types": result}


@router.post("/session")
async def create_report_session(
    body: ReportRequest,
    user: Dict[str, Any] = Depends(verify_jwt),
) -> Dict[str, Any]:
    """
    Step 1 of the Report Wizard: create a new report session.
    Returns session_id, report_type, status, and the scope fields the user must supply.
    """
    from src.report_templates import get_required_scope_fields
    from src.services.report_session_service import create_session

    report_type = body.report_type or "executive"
    try:
        session = create_session(
            report_type=report_type,
            created_by=user.get("sub") or user.get("user_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("create_report_session failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create report session")

    template = get_template(report_type)
    return {
        "session_id":            session["id"],
        "report_type":           report_type,
        "status":                session["session_status"],
        "client_facing_name":    template.get("client_facing_name", ""),
        "sections":              [s["title"] for s in sorted(
                                     template.get("sections", []), key=lambda s: s["order"])],
        "scope_fields_required": get_required_scope_fields(report_type),
        "all_scope_fields":      template.get("scope_fields", []),
    }


@router.put("/session/{session_id}/scope")
async def update_session_scope(
    session_id: str,
    body: SessionUpdateRequest,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> Dict[str, Any]:
    """
    Step 2-3 of the Report Wizard: set scope parameters and evidence notes.
    Advances session status to 'scoping'.
    """
    from src.services.report_session_service import update_scope
    scope_dict = body.scope.model_dump(exclude_none=True)
    try:
        session = update_scope(
            session_id=session_id,
            scope_params=scope_dict,
            evidence_notes=body.evidence_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("update_session_scope failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update session scope")

    return {
        "session_id": session["id"],
        "status":     session["session_status"],
        "scope":      session.get("scope_params", {}),
    }


@router.get("/session/{session_id}")
async def get_report_session(
    session_id: str,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> Dict[str, Any]:
    """Return the current state of a report session."""
    from src.services.report_session_service import get_session
    try:
        return get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch session: {exc}")


@router.post("/session/{session_id}/generate", response_model=ReportResponse)
async def generate_from_session(
    session_id: str,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> ReportResponse:
    """
    Step 4 of the Report Wizard: trigger generation from a scoped session.
    Loads scope_params from the session row and runs the ReportGenerationAgent.
    """
    from src.services.report_session_service import get_session, mark_generating, fail_session

    try:
        session = get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    report_type  = session.get("report_type", "executive")
    scope_params = session.get("scope_params") or {}

    mark_generating(session_id)

    body = ReportRequest(report_type=report_type, intent_text=None)
    try:
        insight, full_report, section_title, resolved_type = _run_agent(
            body, session_id=session_id, scope_params=scope_params
        )
    except HTTPException:
        fail_session(session_id)
        raise

    return _insight_to_response(insight, full_report, section_title, resolved_type, session_id)


@router.post("/session/{session_id}/generate/invoice")
async def generate_invoice_from_session(
    session_id: str,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> StreamingResponse:
    """
    Generate a branded invoice .docx from a session with report_type='invoice'.
    Uses LLM only for the service description paragraph; all structured fields
    come from scope_params.
    """
    from src.services.report_session_service import get_session, mark_generating, fail_session

    try:
        session = get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if session.get("report_type") != "invoice":
        raise HTTPException(status_code=400, detail="Session report_type must be 'invoice'")

    scope_params = session.get("scope_params") or {}
    mark_generating(session_id)

    # Generate service description via LLM
    service_desc = ""
    try:
        from src.agents.report_generation_agent import ReportGenerationAgent
        from src.agent_registry import get_agent
        agent = get_agent("report_generation_agent", context={
            "intent_text":  "generate invoice service description",
            "report_type":  "invoice",
            "scope_params": scope_params,
            "simulation":   True,  # No memory write for invoice narrative
        })
        if agent:
            insight = agent.run()
            metrics = insight.metrics or {}
            sr = metrics.get("section_results", [])
            if sr:
                service_desc = sr[0].get("content", "")
    except Exception as exc:
        logger.warning("invoice: service description generation failed: %s", exc)

    try:
        docx_bytes = _build_invoice_docx(scope_params, service_desc)
    except RuntimeError as exc:
        fail_session(session_id)
        raise HTTPException(status_code=501, detail=str(exc))

    client = scope_params.get("client_name", "client").replace(" ", "_")
    filename = f"placeware_invoice_{client}_{datetime.utcnow().strftime('%Y%m%d')}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{report_id}/approve")
async def approve_report(
    report_id: str,
    user: Dict[str, Any] = Depends(verify_jwt),
) -> Dict[str, Any]:
    """
    Approve a completed report. Requires admin or management role.
    Updates both placeware_report_memory and the linked session (if any).
    """
    user_roles = user.get("roles", [])
    if not any(r in user_roles for r in ("admin", "management", "manager")):
        raise HTTPException(status_code=403, detail="Insufficient role to approve reports")

    approver_id = user.get("sub") or user.get("user_id", "unknown")

    # Find the session linked to this report_memory row (if any)
    session_id = None
    try:
        res = (
            db.table("placeware_report_memory")
            .select("session_id, approval_status")
            .eq("id", report_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Report not found")
        session_id = res.data.get("session_id")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {exc}")

    from src.services.report_session_service import approve_report as svc_approve
    try:
        if session_id:
            svc_approve(
                session_id=session_id,
                approver_id=approver_id,
                report_memory_id=report_id,
            )
        else:
            # No session â€” update memory directly
            from datetime import timezone
            db.table("placeware_report_memory").update({
                "approval_status": "approved",
                "approved_by":     approver_id,
                "approved_at":     datetime.now(timezone.utc).isoformat(),
            }).eq("id", report_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Approval failed: {exc}")

    return {"report_id": report_id, "status": "approved", "approved_by": approver_id}


# â”€â”€ Legacy direct-generate endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    body: ReportRequest,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> ReportResponse:
    """
    [Legacy] Run the ReportGenerationAgent and return JSON.
    Use POST /reports/session â†’ PUT /scope â†’ POST /session/{id}/generate for
    the full wizard workflow with scope control.
    """
    insight, full_report, section_title, report_type = _run_agent(body)
    return _insight_to_response(insight, full_report, section_title, report_type)


@router.post("/generate/docx")
async def generate_report_docx(
    body: ReportRequest,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> StreamingResponse:
    """
    [Legacy] Run the ReportGenerationAgent and return a branded .docx download.
    """
    insight, full_report, section_title, report_type = _run_agent(body)
    metrics         = insight.metrics or {}
    section_results = metrics.get("section_results") or []
    scope_params    = metrics.get("scope_params") or {}

    try:
        docx_bytes = _build_report_docx(
            full_report=full_report,
            section_title=section_title,
            report_type=report_type,
            section_results=section_results,
            scope_params=scope_params,
            approved=False,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    filename = f"placeware_{report_type}_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Reports about a chosen record (the standard way to generate) ────────────────
# 1. choose the report type   2. choose the exact record   3. review what the system
# gathered (add notes)         4. generate - written from that record only, with the
# record attached as the appendix.

class FromRecordRequest(BaseModel):
    report_type: str
    kind: str
    id: str
    notes: Optional[str] = None


def _subjects_call(fn, *a):
    try:
        return fn(*a)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/catalog")
async def report_catalog(_user: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    from src.services.report_subjects import KIND_LABEL, REPORT_TYPES
    return {"types": REPORT_TYPES, "kind_labels": KIND_LABEL}


@router.get("/subjects/{kind}")
async def report_subjects(kind: str, search: str = Query(""), _user: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    import asyncio
    from src.services.report_subjects import list_subjects
    return {"items": await asyncio.to_thread(_subjects_call, list_subjects, kind, search)}


@router.get("/dossier")
async def report_dossier(report_type: str, kind: str, id: str, _user: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    import asyncio
    from src.services.report_subjects import dossier, sections_for
    d = await asyncio.to_thread(_subjects_call, dossier, report_type, kind, id)
    return {**d, "sections": [s["title"] for s in sections_for(report_type, kind)]}


@router.post("/from-record", response_model=ReportResponse)
async def report_from_record(body: FromRecordRequest, user: Dict[str, Any] = Depends(verify_jwt)) -> ReportResponse:
    import asyncio
    import json as _json
    from src.services.report_subjects import TYPE_BY_KEY, dossier, dossier_markdown, sections_for

    d = await asyncio.to_thread(_subjects_call, dossier, body.report_type, body.kind, body.id)
    if (body.notes or "").strip():
        d["texts"].append({"label": "Notes from the person requesting the report", "value": body.notes.strip()})
    tname = TYPE_BY_KEY[body.report_type]["name"]
    title = d["title"] if body.kind in ("period", "current") else f"{tname}: {d['title']}"

    def run():
        from src.agent_registry import get_agent
        agent = get_agent("report_generation_agent", context={
            "intent_text": f"{title}. Write it only from the record provided.",
            "report_type": body.report_type, "dossier": d, "title": title,
            "sections": sections_for(body.report_type, body.kind),
            "subject": {"kind": body.kind, "id": body.id, "label": title, "notes": body.notes, "created_by": user.get("sub")},
            "actor_id": user.get("sub") or "api_reports", "simulation": False, "enable_memory": False,
        })
        if agent is None:
            raise HTTPException(status_code=503, detail="Report writer not available")
        return agent.run()

    try:
        insight = await asyncio.to_thread(run)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("record report failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    metrics = insight.metrics or {}
    appendix = dossier_markdown(d)
    sections = list(metrics.get("section_results") or [])
    sections.append({"section_id": "appendix", "title": "Appendix: Record Details",
                     "content": appendix.split("\n", 2)[2], "confidence_score": 1.0, "status": "complete", "order": 99})
    full_report = (metrics.get("full_report") or "") + "\n\n" + appendix
    metrics["full_report"], metrics["section_results"] = full_report, sections
    rid = metrics.get("report_memory_id")
    if rid:
        try:
            from src.fin.db import ex as _ex, tx as _tx
            with _tx() as conn:
                _ex(conn, "UPDATE placeware_report_memory SET full_report=%s, section_data=%s::jsonb WHERE id=%s::uuid",
                    (full_report, _json.dumps(sections, default=str), rid))
        except Exception as exc:
            logger.warning("could not attach record appendix: %s", exc)
    return _insight_to_response(insight, full_report, title, body.report_type)


@router.get("/for-record")
async def reports_for_record(kind: str, id: str, _user: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    """Reports already written about this record."""
    from src.fin.db import q as _q, tx as _tx
    with _tx() as conn:
        rows = _q(conn, """SELECT id::text AS id, report_type, subject_label, approval_status, created_at, quality_score
                           FROM placeware_report_memory WHERE subject_kind=%s AND subject_id=%s ORDER BY created_at DESC""", (kind, id))
    return {"reports": rows}


# â”€â”€ History endpointsâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/history")
async def report_history(
    report_type: Optional[str] = Query(None, description="Filter by report type"),
    status: Optional[str]      = Query(None, description="Filter by approval_status"),
    limit: int                 = Query(20, ge=1, le=100),
    offset: int                = Query(0, ge=0),
    _user: Dict[str, Any]      = Depends(verify_jwt),
) -> Dict[str, Any]:
    """
    List stored reports from placeware_report_memory, newest first.
    Filterable by report_type and approval_status (draft | complete | approved).
    """
    try:
        q = (
            db.table("placeware_report_memory")
            .select("id, report_type, summary, quality_score, approval_status, "
                    "approved_by, approved_at, template_version, session_id, created_at, "
                    "subject_kind, subject_id, subject_label, created_by")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if report_type:
            q = q.eq("report_type", report_type)
        if status:
            q = q.eq("approval_status", status)
        res = q.execute()
        return {"reports": res.data or [], "limit": limit, "offset": offset}
    except Exception as exc:
        logger.error("report history fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch report history: {exc}")


@router.get("/history/{report_id}/docx")
async def report_detail_docx(
    report_id: str,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> StreamingResponse:
    """Download a previously stored report as a branded .docx file."""
    try:
        res = (
            db.table("placeware_report_memory")
            .select("report_type, full_report, summary, section_data, "
                    "approval_status, approved_by, approved_at, session_id, subject_label")
            .eq("id", report_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Report not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {exc}")

    row          = res.data
    full_report  = row.get("full_report") or row.get("summary", "No content available.")
    report_type  = row.get("report_type", "report")
    section_title = row.get("subject_label") or get_template(report_type).get("output_title", report_type.replace("_", " ").title())
    approved     = row.get("approval_status") == "approved"

    # Load section_data if stored
    section_results = None
    raw_sd = row.get("section_data")
    if raw_sd:
        import json as _json
        try:
            section_results = _json.loads(raw_sd) if isinstance(raw_sd, str) else raw_sd
        except Exception:
            pass

    # Load scope_params from the linked session if available
    scope_params: Dict[str, Any] = {"subject": row["subject_label"]} if row.get("subject_label") else {}
    session_id = row.get("session_id")
    if session_id:
        try:
            from src.services.report_session_service import get_session
            sess = get_session(session_id)
            scope_params = sess.get("scope_params") or {}
        except Exception:
            pass

    try:
        docx_bytes = _build_report_docx(
            full_report=full_report,
            section_title=section_title,
            report_type=report_type,
            section_results=section_results,
            scope_params=scope_params,
            approved=approved,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    filename = f"placeware_{report_type}_{'final' if approved else 'draft'}_{report_id[:8]}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/history/{report_id}")
async def report_detail(
    report_id: str,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> Dict[str, Any]:
    """Return the full narrative of a single stored report."""
    try:
        res = (
            db.table("placeware_report_memory")
            .select("*")
            .eq("id", report_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Report not found")
        return res.data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("report detail fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {exc}")
