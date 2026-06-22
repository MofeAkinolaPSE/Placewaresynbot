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


# â”€â”€ DOCX builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_report_docx(
    full_report: str,
    section_title: str,
    report_type: str,
    section_results: Optional[List[Dict[str, Any]]] = None,
    scope_params: Optional[Dict[str, Any]] = None,
    approved: bool = False,
) -> bytes:
    """
    Build a professional, enterprise-grade branded .docx report.

    Features:
      - Cover page (title, scope dates, classification badge, DRAFT/FINAL watermark)
      - Table of contents (auto-built from section titles)
      - Section-by-section rendering when section_results is provided
      - Findings table (No. | Finding | Source)
      - Recommendations table (Priority | Recommendation)
      - Signature block (Prepared By / Reviewed By / Approved By)
      - DRAFT watermark until approved=True
    """
    try:
        from docx import Document as DocxDocument
        from docx.shared import Pt, RGBColor, Inches, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        raise RuntimeError("python-docx is not installed on the server")

    # â”€â”€ Brand constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    GREEN    = RGBColor(0x2D, 0x6A, 0x4F)  # Placeware pharma green
    NAVY     = RGBColor(0x1E, 0x3A, 0x5F)  # Deep navy
    GREY     = RGBColor(0x66, 0x66, 0x66)
    LIGHT_GREY = RGBColor(0x99, 0x99, 0x99)
    WATERMARK_COLOR = RGBColor(0xCC, 0x00, 0x00) if not approved else RGBColor(0x00, 0x88, 0x44)
    watermark_text = "FINAL" if approved else "DRAFT"

    doc = DocxDocument()

    # â”€â”€ Page layout: A4 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    word_section = doc.sections[0]
    word_section.page_width  = int(21.0 * 914400 / 25.4)
    word_section.page_height = int(29.7 * 914400 / 25.4)
    word_section.left_margin   = Inches(1.0)
    word_section.right_margin  = Inches(1.0)
    word_section.top_margin    = Cm(2.0)
    word_section.bottom_margin = Cm(2.0)

    # â”€â”€ Helper: add coloured paragraph â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _add_coloured_run(para, text: str, color: RGBColor, bold: bool = False, size: int = 10):
        run = para.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.color.rgb = color
        return run

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # COVER PAGE
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    doc.add_paragraph("")
    doc.add_paragraph("")

    # Company brand header
    brand_p = doc.add_paragraph()
    brand_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_coloured_run(brand_p, "PLACEWARE NIGERIA LIMITED", GREEN, bold=True, size=14)

    tagline_p = doc.add_paragraph()
    tagline_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_coloured_run(tagline_p, "Enterprise AI Intelligence Report", GREY, size=10)

    doc.add_paragraph("")

    # Watermark badge
    wm_p = doc.add_paragraph()
    wm_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    wm_run = wm_p.add_run(f"[ {watermark_text} ]")
    wm_run.bold = True
    wm_run.font.size = Pt(16)
    wm_run.font.color.rgb = WATERMARK_COLOR

    doc.add_paragraph("")
    doc.add_paragraph("â”€" * 72)
    doc.add_paragraph("")

    # Report title
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_coloured_run(title_p, section_title.upper(), NAVY, bold=True, size=18)

    doc.add_paragraph("")

    # Report metadata block
    now_str      = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")
    date_from    = (scope_params or {}).get("date_from", "N/A")
    date_to      = (scope_params or {}).get("date_to", "N/A")
    client_scope = (scope_params or {}).get("client_name") or (scope_params or {}).get("entity_filter", "Placeware Nigeria")

    for label, value in [
        ("Report Type",     report_type.replace("_", " ").title()),
        ("Report Period",   f"{date_from} to {date_to}"),
        ("Entity / Scope",  client_scope),
        ("Generated",       now_str),
        ("Prepared By",     "ACE - Placeware Nigeria AI Executive Intelligence"),
        ("Classification",  "CONFIDENTIAL â€” For Authorised Recipients Only"),
    ]:
        meta_p = doc.add_paragraph()
        meta_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_coloured_run(meta_p, f"{label}: ", NAVY, bold=True, size=10)
        _add_coloured_run(meta_p, value, GREY, size=10)

    doc.add_paragraph("")
    doc.add_paragraph("â”€" * 72)

    # Page break after cover
    doc.add_page_break()

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # TABLE OF CONTENTS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    toc_heading = doc.add_heading("Table of Contents", level=1)
    toc_heading.runs[0].font.color.rgb = NAVY

    if section_results:
        for sec in sorted(section_results, key=lambda s: s.get("order", 0)):
            toc_p = doc.add_paragraph(style="List Number")
            _add_coloured_run(toc_p, sec["title"], NAVY, bold=False, size=10)
    else:
        # Fallback: parse ## headings from full_report
        for line in full_report.split("\n"):
            if line.startswith("## "):
                toc_p = doc.add_paragraph(style="List Number")
                _add_coloured_run(toc_p, line[3:], NAVY, size=10)

    doc.add_page_break()

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # REPORT BODY â€” section-by-section or fallback markdown parse
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if section_results:
        _render_sections(doc, section_results, GREEN, NAVY, GREY)
    else:
        _render_markdown_body(doc, full_report, GREEN, NAVY, GREY)

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # SIGNATURE BLOCK
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    doc.add_page_break()
    sig_heading = doc.add_heading("Sign-Off & Approval", level=1)
    sig_heading.runs[0].font.color.rgb = NAVY

    doc.add_paragraph("")
    sig_table = doc.add_table(rows=4, cols=3)
    sig_table.style = "Table Grid"
    headers = ["Role", "Name & Signature", "Date"]
    roles   = ["Prepared By", "Reviewed By", "Approved By"]
    hdr_row = sig_table.rows[0]
    for i, h in enumerate(headers):
        cell = hdr_row.cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = NAVY
    for i, role in enumerate(roles):
        row = sig_table.rows[i + 1]
        row.cells[0].text = role
        row.cells[1].text = ""
        row.cells[2].text = ""

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # FOOTER
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    doc.add_paragraph("")
    footer_p = doc.add_paragraph()
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer_p.add_run(
        "This report was generated by ACE - Placeware Nigeria AI Executive Intelligence. "
        "CONFIDENTIAL. Not a substitute for professional regulatory or financial advice."
    )
    fr.italic = True
    fr.font.size = Pt(8)
    fr.font.color.rgb = LIGHT_GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _render_sections(
    doc: Any,
    section_results: List[Dict[str, Any]],
    green: Any,
    navy: Any,
    grey: Any,
) -> None:
    """Render a list of SectionResult dicts into the Word document."""
    from docx.shared import Pt, RGBColor

    for sec in sorted(section_results, key=lambda s: s.get("order", 0)):
        title   = sec.get("title", "")
        content = sec.get("content", "")
        status  = sec.get("status", "complete")
        conf    = sec.get("confidence_score", 0.0)

        h = doc.add_heading(title, level=2)
        h.runs[0].font.color.rgb = green

        if status == "incomplete":
            p = doc.add_paragraph()
            r = p.add_run("[Section incomplete â€” insufficient data available for this period.]")
            r.italic = True
            r.font.color.rgb = grey
        elif content:
            _render_markdown_body(doc, content, green, navy, grey, top_level=False)

        # Confidence line
        conf_p = doc.add_paragraph()
        conf_run = conf_p.add_run(f"Section confidence: {conf:.0%}")
        conf_run.italic = True
        conf_run.font.size = Pt(8)
        conf_run.font.color.rgb = grey

        doc.add_paragraph("")


def _render_markdown_body(
    doc: Any,
    text: str,
    green: Any,
    navy: Any,
    grey: Any,
    top_level: bool = True,
) -> None:
    """Parse markdown-ish text and render into doc paragraphs."""
    from docx.shared import Pt, RGBColor

    # Extract findings and recommendations for table rendering
    findings: List[str] = []
    recommendations: List[str] = []
    current_section = ""

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("# ") and top_level:
            h = doc.add_heading(stripped[2:], level=1)
            h.runs[0].font.color.rgb = navy

        elif stripped.startswith("## "):
            h = doc.add_heading(stripped[3:], level=2)
            h.runs[0].font.color.rgb = green
            current_section = stripped[3:].lower()

        elif stripped.startswith("### "):
            h = doc.add_heading(stripped[4:], level=3)
            if h.runs:
                h.runs[0].font.color.rgb = navy

        elif stripped.startswith("---"):
            doc.add_paragraph("â”€" * 72)

        elif re.match(r"^\d+\.", stripped):
            item_text = stripped[stripped.index(".") + 1:].strip()
            p = doc.add_paragraph(style="List Number")
            _add_inline_formatting(p, item_text, Pt(10), grey)
            if "finding" in current_section or "key finding" in current_section:
                findings.append(item_text)
            if "recommendation" in current_section:
                recommendations.append(item_text)

        elif stripped.startswith("* ") or stripped.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            _add_inline_formatting(p, stripped[2:], Pt(10), grey)

        elif stripped == "":
            doc.add_paragraph("")

        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            _add_inline_formatting(p, stripped, Pt(10), grey)

        i += 1

    # Render findings table if we collected any numbered findings
    if findings and top_level:
        doc.add_heading("Findings Summary", level=2).runs[0].font.color.rgb = green
        t = doc.add_table(rows=1 + len(findings), cols=2)
        t.style = "Table Grid"
        t.rows[0].cells[0].text = "No."
        t.rows[0].cells[1].text = "Finding"
        for j, f in enumerate(findings):
            t.rows[j + 1].cells[0].text = str(j + 1)
            t.rows[j + 1].cells[1].text = f
        doc.add_paragraph("")

    # Render recommendations table
    if recommendations and top_level:
        doc.add_heading("Recommendations Summary", level=2).runs[0].font.color.rgb = green
        t = doc.add_table(rows=1 + len(recommendations), cols=2)
        t.style = "Table Grid"
        t.rows[0].cells[0].text = "Priority"
        t.rows[0].cells[1].text = "Recommendation"
        for j, r in enumerate(recommendations):
            t.rows[j + 1].cells[0].text = str(j + 1)
            t.rows[j + 1].cells[1].text = r
        doc.add_paragraph("")


def _add_inline_formatting(para: Any, text: str, font_size: Any, grey: Any) -> None:
    """Handle **bold** and *italic* inline markdown in a paragraph."""
    from docx.shared import RGBColor

    parts = re.split(r"(\*\*.*?\*\*|\*.*?\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = para.add_run(part[2:-2])
            run.bold = True
            run.font.size = font_size
        elif part.startswith("*") and part.endswith("*"):
            run = para.add_run(part[1:-1])
            run.italic = True
            run.font.size = font_size
            run.font.color.rgb = grey
        elif part:
            run = para.add_run(part)
            run.font.size = font_size


# â”€â”€ Invoice DOCX builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_invoice_docx(scope_params: Dict[str, Any], service_description: str = "") -> bytes:
    """
    Build a branded tax invoice as a .docx file.
    All monetary calculations use scope_params line_items.
    """
    try:
        from docx import Document as DocxDocument
        from docx.shared import Pt, RGBColor, Inches, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise RuntimeError("python-docx is not installed on the server")

    GREEN = RGBColor(0x2D, 0x6A, 0x4F)
    NAVY  = RGBColor(0x1E, 0x3A, 0x5F)
    GREY  = RGBColor(0x66, 0x66, 0x66)

    doc = DocxDocument()
    word_section = doc.sections[0]
    word_section.page_width  = int(21.0 * 914400 / 25.4)
    word_section.page_height = int(29.7 * 914400 / 25.4)
    word_section.left_margin   = Inches(1.0)
    word_section.right_margin  = Inches(1.0)
    word_section.top_margin    = Cm(2.0)
    word_section.bottom_margin = Cm(2.0)

    # Header
    hdr = doc.add_paragraph()
    hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = hdr.add_run("PLACEWARE NIGERIA LIMITED"); r.bold = True; r.font.size = Pt(14); r.font.color.rgb = GREEN

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = sub.add_run("TAX INVOICE"); r2.bold = True; r2.font.size = Pt(18); r2.font.color.rgb = NAVY

    doc.add_paragraph("â”€" * 72)
    doc.add_paragraph("")

    # Client + invoice metadata two-column layout via table
    meta_table = doc.add_table(rows=1, cols=2)
    meta_table.style = "Table Grid"
    left  = meta_table.rows[0].cells[0]
    right = meta_table.rows[0].cells[1]

    bill_to = f"Bill To:\n{scope_params.get('client_name','')}\n{scope_params.get('client_address','')}\n{scope_params.get('client_email','')}"
    left.text = bill_to

    inv_num = f"INVOICE-{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    inv_info = (
        f"Invoice No: {inv_num}\n"
        f"Invoice Date: {scope_params.get('invoice_date','')}\n"
        f"Due Date: {scope_params.get('due_date','')}\n"
        f"Currency: {scope_params.get('currency','NGN')}"
    )
    right.text = inv_info

    doc.add_paragraph("")

    # Service description
    if service_description:
        desc_h = doc.add_heading("Description of Services", level=2)
        desc_h.runs[0].font.color.rgb = GREEN
        doc.add_paragraph(service_description)
        doc.add_paragraph("")

    # Line items table
    line_items: List[Dict] = scope_params.get("line_items") or []
    items_heading = doc.add_heading("Invoice Items", level=2)
    items_heading.runs[0].font.color.rgb = GREEN

    n_rows = 1 + max(len(line_items), 1)
    items_table = doc.add_table(rows=n_rows, cols=4)
    items_table.style = "Table Grid"
    col_headers = ["Description", "Qty", "Unit Price", "Total"]
    for j, ch in enumerate(col_headers):
        cell = items_table.rows[0].cells[j]
        cell.text = ch
        cell.paragraphs[0].runs[0].bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = NAVY

    subtotal = 0.0
    for j, item in enumerate(line_items):
        qty   = float(item.get("qty", item.get("quantity", 1)))
        price = float(item.get("unit_price", item.get("price", 0)))
        total = qty * price
        subtotal += total
        row = items_table.rows[j + 1]
        row.cells[0].text = str(item.get("description", item.get("name", "")))
        row.cells[1].text = str(qty)
        row.cells[2].text = f"{price:,.2f}"
        row.cells[3].text = f"{total:,.2f}"

    doc.add_paragraph("")

    # Totals
    vat_rate = float(scope_params.get("vat_rate") or 0.0) / 100
    vat_amt  = subtotal * vat_rate
    grand    = subtotal + vat_amt
    currency = scope_params.get("currency", "NGN")

    for label, value in [
        ("Subtotal",  f"{currency} {subtotal:,.2f}"),
        (f"VAT ({scope_params.get('vat_rate',0)}%)", f"{currency} {vat_amt:,.2f}"),
        ("TOTAL DUE", f"{currency} {grand:,.2f}"),
    ]:
        tot_p = doc.add_paragraph()
        tot_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_l = tot_p.add_run(f"{label}: "); r_l.bold = True; r_l.font.color.rgb = NAVY
        r_v = tot_p.add_run(value); r_v.bold = (label == "TOTAL DUE"); r_v.font.color.rgb = GREEN if label == "TOTAL DUE" else NAVY

    doc.add_paragraph("")

    # Payment terms + bank details
    pt = scope_params.get("payment_terms")
    if pt:
        h = doc.add_heading("Payment Terms", level=2); h.runs[0].font.color.rgb = GREEN
        doc.add_paragraph(pt)

    bd = scope_params.get("bank_details")
    if bd:
        h = doc.add_heading("Bank Details", level=2); h.runs[0].font.color.rgb = GREEN
        doc.add_paragraph(bd)

    notes = scope_params.get("custom_notes")
    if notes:
        h = doc.add_heading("Additional Notes", level=2); h.runs[0].font.color.rgb = GREEN
        doc.add_paragraph(notes)

    doc.add_paragraph("")
    doc.add_paragraph("â”€" * 72)
    footer_p = doc.add_paragraph()
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer_p.add_run("Placeware Nigeria Limited | Thank you for your business.")
    fr.italic = True; fr.font.size = Pt(9); fr.font.color.rgb = GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


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


# â”€â”€ History endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                    "approved_by, approved_at, template_version, session_id, created_at")
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
                    "approval_status, approved_by, approved_at, session_id")
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
    section_title = get_template(report_type).get("output_title", report_type.replace("_", " ").title())
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
    scope_params: Dict[str, Any] = {}
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
