"""Reports router — agent-powered intelligence report endpoints.

Endpoints:
  POST /reports/generate         — Run ReportGenerationAgent, return JSON narrative
  POST /reports/generate/docx    — Run ReportGenerationAgent, return .docx file
  GET  /reports/history          — List past stored reports from placeware_report_memory
  GET  /reports/history/{id}     — Full report detail
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


# ── Request / Response models ────────────────────────────────────────────────

class ReportRequest(BaseModel):
    report_type: Optional[str] = Field(
        None,
        description=(
            "Optional report type override. One of: deviation, maintenance, compliance, "
            "audit, financial, inventory, executive, sales, payroll, pl, ar_aging, frontdesk"
        ),
    )
    intent_text: Optional[str] = Field(
        None,
        description="Natural-language description of what report is needed. Used when report_type is absent.",
    )


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


# ── DOCX builder ─────────────────────────────────────────────────────────────

def _build_report_docx(full_report: str, section_title: str, report_type: str) -> bytes:
    """
    Convert a markdown-style report text to a branded .docx file.
    Handles: # H1, ## H2, numbered lists, bold **text**, italic *text*, --- separators.
    Returns raw bytes ready for StreamingResponse.
    """
    try:
        from docx import Document as DocxDocument
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise RuntimeError("python-docx is not installed on the server")

    doc = DocxDocument()

    # ── Page layout: A4 ──────────────────────────────────────────────────────
    section = doc.sections[0]
    section.page_width  = int(21.0 * 914400 / 25.4)   # A4 in EMU
    section.page_height = int(29.7 * 914400 / 25.4)
    section.left_margin   = int(2.54 * 914400 / 2.54)  # 1 inch
    section.right_margin  = int(2.54 * 914400 / 2.54)
    section.top_margin    = int(2.00 * 914400 / 2.54)
    section.bottom_margin = int(2.00 * 914400 / 2.54)

    # ── Brand header ─────────────────────────────────────────────────────────
    header_para = doc.add_paragraph()
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = header_para.add_run("PLACEWARE NIGERIA — INTELLIGENCE REPORT")
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(0x2D, 0x6A, 0x4F)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(
        f"Generated: {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}  |  "
        f"Type: {report_type.replace('_', ' ').title()}"
    ).font.size = Pt(8)

    doc.add_paragraph("─" * 80)

    # ── Parse and render report lines ────────────────────────────────────────
    lines = full_report.split("\n")
    for line in lines:
        stripped = line.strip()

        if stripped.startswith("# "):
            # Top-level heading
            p = doc.add_heading(stripped[2:], level=1)
            p.runs[0].font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)

        elif stripped.startswith("## "):
            # Section heading
            p = doc.add_heading(stripped[3:], level=2)
            p.runs[0].font.color.rgb = RGBColor(0x2D, 0x6A, 0x4F)

        elif stripped.startswith("---"):
            doc.add_paragraph("─" * 80)

        elif re.match(r"^\d+\.", stripped):
            # Numbered list item
            p = doc.add_paragraph(style="List Number")
            p.add_run(stripped[stripped.index(".") + 1:].strip()).font.size = Pt(10)

        elif stripped.startswith("* ") or stripped.startswith("- "):
            # Bullet list
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(stripped[2:]).font.size = Pt(10)

        elif stripped == "":
            doc.add_paragraph("")

        else:
            # Body paragraph — handle inline **bold** and *italic*
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            # Simple inline bold/italic detection
            parts = re.split(r"(\*\*.*?\*\*|\*.*?\*)", stripped)
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                    run.font.size = Pt(10)
                elif part.startswith("*") and part.endswith("*"):
                    run = p.add_run(part[1:-1])
                    run.italic = True
                    run.font.size = Pt(9)
                    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
                else:
                    run = p.add_run(part)
                    run.font.size = Pt(10)

    # ── Footer ───────────────────────────────────────────────────────────────
    doc.add_paragraph("")
    footer_p = doc.add_paragraph()
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer_p.add_run(
        "This report was generated by Warebot — Placeware Nigeria AI Executive Intelligence. "
        "For business use only. Not a substitute for professional regulatory advice."
    )
    fr.italic = True
    fr.font.size = Pt(8)
    fr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    body: ReportRequest,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> ReportResponse:
    """
    Run the ReportGenerationAgent to produce a full narrative intelligence report.
    The agent auto-detects the report type from `intent_text` when `report_type`
    is not supplied.  Results are persisted to `placeware_report_memory` if
    quality_score >= 7.
    """
    intent_text = body.intent_text or (
        f"generate {body.report_type} report" if body.report_type else "generate executive report"
    )

    try:
        from src.agent_registry import get_agent
        agent = get_agent("report_generation_agent", context={
            "intent_text": intent_text,
            "report_type": body.report_type,
            "actor_id": "api_reports",
            "simulation": False,
            "enable_memory": True,
        })
        if agent is None:
            raise HTTPException(status_code=503, detail="ReportGenerationAgent not available")

        insight = agent.run()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"report generation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    metrics = insight.metrics or {}
    full_report: str = metrics.get("full_report", "")
    if not full_report and insight.findings:
        full_report = "\n".join(insight.findings)

    return ReportResponse(
        report_type=metrics.get("report_type", body.report_type or "executive"),
        section_title=metrics.get("section_title", "Intelligence Report"),
        full_report=full_report,
        findings=insight.findings or [],
        recommendations=insight.recommendations or [],
        quality_score=float(metrics.get("quality_score", 0.0)),
        rag_hits=int(metrics.get("rag_hits", 0)),
        data_rows=int(metrics.get("data_rows", 0)),
        status="success",
    )


def _run_agent(body: ReportRequest) -> tuple[str, str, str]:
    """Shared logic: run the agent, return (full_report, section_title, report_type)."""
    intent_text = body.intent_text or (
        f"generate {body.report_type} report" if body.report_type else "generate executive report"
    )
    try:
        from src.agent_registry import get_agent
        agent = get_agent("report_generation_agent", context={
            "intent_text": intent_text,
            "report_type": body.report_type,
            "actor_id": "api_reports",
            "simulation": False,
            "enable_memory": True,
        })
        if agent is None:
            raise HTTPException(status_code=503, detail="ReportGenerationAgent not available")
        insight = agent.run()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"report agent failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    metrics = insight.metrics or {}
    full_report: str = metrics.get("full_report", "") or "\n".join(insight.findings or [])
    section_title: str = metrics.get("section_title", "Intelligence Report")
    resolved_type: str = metrics.get("report_type", body.report_type or "executive")
    return full_report, section_title, resolved_type


@router.post("/generate/docx")
async def generate_report_docx(
    body: ReportRequest,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> StreamingResponse:
    """
    Run the ReportGenerationAgent and return the result as a branded Word (.docx) document.
    The file is streamed for direct browser download.
    """
    full_report, section_title, report_type = _run_agent(body)

    try:
        docx_bytes = _build_report_docx(full_report, section_title, report_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    filename = f"placeware_{report_type}_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/history/{report_id}/docx")
async def report_detail_docx(
    report_id: str,
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> StreamingResponse:
    """Download a previously stored report as a .docx file."""
    try:
        res = (
            db.table("placeware_report_memory")
            .select("report_type, full_report, summary")
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

    row = res.data
    full_report: str = row.get("full_report") or row.get("summary", "No content available.")
    report_type: str = row.get("report_type", "report")
    section_title = report_type.replace("_", " ").title() + " Report"

    try:
        docx_bytes = _build_report_docx(full_report, section_title, report_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    filename = f"placeware_{report_type}_report_{report_id[:8]}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def report_history(
    report_type: Optional[str] = Query(None, description="Filter by report type"),
    limit: int = Query(10, ge=1, le=100),
    _user: Dict[str, Any] = Depends(verify_jwt),
) -> Dict[str, Any]:
    """
    Return the most recent stored reports from placeware_report_memory,
    ordered by quality score descending.
    """
    try:
        q = (
            db.table("placeware_report_memory")
            .select("id, report_type, summary, quality_score, created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if report_type:
            q = q.eq("report_type", report_type)
        res = q.execute()
        return {"reports": res.data or []}
    except Exception as exc:
        logger.error(f"report history fetch failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch report history: {exc}")


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
        logger.error(f"report detail fetch failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {exc}")
