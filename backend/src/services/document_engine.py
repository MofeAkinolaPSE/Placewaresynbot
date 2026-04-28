"""Document generation engine for Warebot QMS compliance documents.

Generates structured PDF reports using ReportLab Platypus and DOCX using
python-docx.  Each public method accepts a typed dict payload and returns
raw bytes that can be handed directly to the document_storage service.

Supported document types
─────────────────────────
  render_audit_report()            → PDF
  render_deviation_report()        → PDF
  render_maintenance_certificate() → PDF
  render_recall_notice()           → PDF (+ DOCX variant)
  render_recall_investigation()    → PDF
  render_recall_distribution_trace() → XLSX (openpyxl)
  render_sop_summary()             → PDF
"""

from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── ReportLab imports ───────────────────────────────────────────────────────────
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        HRFlowable,
        KeepTogether,
    )
    _REPORTLAB_OK = True
except ImportError:
    _REPORTLAB_OK = False
    logger.warning("reportlab not installed – PDF generation will be unavailable")

# ── python-docx imports ─────────────────────────────────────────────────────────
try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    _DOCX_OK = True
except ImportError:
    _DOCX_OK = False
    logger.warning("python-docx not installed – DOCX generation will be unavailable")

# ── openpyxl (already in requirements) ─────────────────────────────────────────
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    _XLSX_OK = True
except ImportError:
    _XLSX_OK = False
    logger.warning("openpyxl not installed – XLSX generation will be unavailable")


# ── Brand colours ───────────────────────────────────────────────────────────────
_BRAND_DARK  = (0x1E, 0x3A, 0x5F)   # deep navy
_BRAND_MID   = (0x2D, 0x6A, 0x4F)   # pharma green
_BRAND_LIGHT = (0xF0, 0xF4, 0xF9)   # soft blue-grey


# ═══════════════════════════════════════════════════════════════════════════════
# Internal PDF helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="BrandTitle",
        fontSize=18, spaceAfter=6,
        textColor=colors.HexColor("#1E3A5F"),
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        fontSize=12, spaceBefore=12, spaceAfter=4,
        textColor=colors.HexColor("#2D6A4F"),
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="BodyText2",
        fontSize=9, leading=14,
        fontName="Helvetica",
    ))
    styles.add(ParagraphStyle(
        name="SmallLabel",
        fontSize=8, textColor=colors.grey,
        fontName="Helvetica-Oblique",
    ))
    return styles


def _header_table(title: str, doc_ref: str, generated_on: str) -> Table:
    """Logo-less branded header banner."""
    data = [[
        Paragraph(f"<b>PLACEWARE NIGERIA</b><br/>Pharmaceutical Cold-Chain Distribution",
                  ParagraphStyle("h1", fontSize=11, fontName="Helvetica-Bold",
                                 textColor=colors.white)),
        Paragraph(
            f"<b>{title}</b><br/><font size='8'>{doc_ref}<br/>Generated: {generated_on}</font>",
            ParagraphStyle("h2", fontSize=10, fontName="Helvetica",
                           textColor=colors.white, alignment=2),  # 2 = right
        ),
    ]]
    t = Table(data, colWidths=[10.5 * cm, 7 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR",     (0, 0), (-1, -1), colors.white),
        ("PADDINGTOP",    (0, 0), (-1, -1), 10),
        ("PADDINGBOTTOM", (0, 0), (-1, -1), 10),
        ("PADDINGLEFT",   (0, 0), (-1, -1), 12),
        ("PADDINGRIGHT",  (0, 0), (-1, -1), 12),
    ]))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2 * cm, 1.2 * cm,
                      "PLACEWARE NIGERIA — Confidential compliance document. Not for public distribution.")
    canvas.drawRightString(
        19 * cm, 1.2 * cm,
        f"Page {doc.page}"
    )
    canvas.restoreState()


def _kv_table(pairs: List[tuple], col_widths=None) -> Table:
    """Two-column key-value table for document metadata blocks."""
    col_widths = col_widths or [5.5 * cm, 12 * cm]
    styles_obj = getSampleStyleSheet()
    data = []
    for k, v in pairs:
        data.append([
            Paragraph(f"<b>{k}</b>",
                      ParagraphStyle("kk", fontSize=9, fontName="Helvetica-Bold")),
            Paragraph(str(v) if v is not None else "—",
                      ParagraphStyle("vv", fontSize=9, fontName="Helvetica")),
        ])
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#EEEEEE")),
        ("BACKGROUND",    (0, 0), (0, -1),  colors.HexColor("#F0F4F9")),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("PADDINGTOP",    (0, 0), (-1, -1), 4),
        ("PADDINGBOTTOM", (0, 0), (-1, -1), 4),
        ("PADDINGLEFT",   (0, 0), (-1, -1), 6),
    ]))
    return t


def _section(title: str, styles) -> List:
    return [
        Spacer(1, 0.3 * cm),
        Paragraph(title, styles["SectionHeading"]),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#2D6A4F")),
        Spacer(1, 0.2 * cm),
    ]


def _build_pdf(elements: List, buffer: io.BytesIO) -> None:
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.8 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )
    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentEngine:
    """Stateless factory — all methods are pure functions over data dicts."""

    # ── Audit Report ───────────────────────────────────────────────────────────

    def render_audit_report(self, data: Dict[str, Any]) -> bytes:
        """Generate a QMS audit report PDF.

        Expected keys in *data*:
          audit_type, department, month_due, year, assigned_to, status,
          auditor_name, summary, findings (list of str),
          observations (list of str), recommendations (list of str),
          audit_id (str), completed_at
        """
        if not _REPORTLAB_OK:
            raise RuntimeError("reportlab is not installed")

        styles = _make_styles()
        buf = io.BytesIO()
        today_str = str(date.today())
        doc_ref = f"AUDIT-{data.get('year', date.today().year)}-{data.get('month_due', 'XX'):02d}"
        elements = []

        elements.append(_header_table("AUDIT REPORT", doc_ref, today_str))
        elements.append(Spacer(1, 0.5 * cm))

        # Meta section
        elements += _section("Audit Metadata", styles)
        elements.append(_kv_table([
            ("Audit Type",   data.get("audit_type", "—")),
            ("Department",   data.get("department", "—")),
            ("Period",       f"{data.get('month_due', '?')}/{data.get('year', '?')}"),
            ("Assigned To",  data.get("assigned_to", "—")),
            ("Auditor",      data.get("auditor_name", "—")),
            ("Status",       data.get("status", "—").upper()),
            ("Completed On", data.get("completed_at", "—")),
        ]))

        # Summary
        if data.get("summary"):
            elements += _section("Executive Summary", styles)
            elements.append(Paragraph(data["summary"], styles["BodyText2"]))

        # Findings
        findings = data.get("findings") or []
        if findings:
            elements += _section("Audit Findings", styles)
            for i, f in enumerate(findings, 1):
                elements.append(Paragraph(f"  {i}. {f}", styles["BodyText2"]))

        # Observations
        observations = data.get("observations") or []
        if observations:
            elements += _section("Observations", styles)
            for obs in observations:
                elements.append(Paragraph(f"  • {obs}", styles["BodyText2"]))

        # Recommendations
        recs = data.get("recommendations") or []
        if recs:
            elements += _section("Recommendations", styles)
            for rec in recs:
                elements.append(Paragraph(f"  ► {rec}", styles["BodyText2"]))

        # Signature block
        elements += _section("Sign-Off", styles)
        elements.append(_kv_table([
            ("Auditor Signature",  "__________________________"),
            ("QA Manager Review",  "__________________________"),
            ("Date Authorised",    today_str),
        ]))

        # Knowledge Base Reference (injected when available)
        kb_ctx = (data.get("kb_context") or "").strip()
        if kb_ctx:
            elements += _section("Knowledge Base Reference", styles)
            elements.append(Paragraph(
                "The following content from the compliance knowledge base was referenced "
                "during report preparation:",
                styles["SmallLabel"],
            ))
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph(kb_ctx[:3000], styles["BodyText2"]))

        _build_pdf(elements, buf)
        return buf.getvalue()

    # ── Deviation / CAPA Report ────────────────────────────────────────────────

    def render_deviation_report(self, data: Dict[str, Any]) -> bytes:
        """Generate a Deviation & CAPA report PDF.

        Expected keys: deviation_id, classification, trigger_type,
          investigation_start_date, observation, impact_assessment,
          recommendations, responsible_department, responsible_person,
          capa_actions (list of {action, owner, due_date, status}), status
        """
        if not _REPORTLAB_OK:
            raise RuntimeError("reportlab is not installed")

        styles = _make_styles()
        buf = io.BytesIO()
        today_str = str(date.today())
        doc_ref = data.get("deviation_id", "DEV-UNKNOWN")
        classification = data.get("classification", "minor").upper()
        cls_color = {"MINOR": "#2D6A4F", "MAJOR": "#E67E22", "CRITICAL": "#C0392B"}.get(
            classification, "#1E3A5F"
        )

        elements = []
        elements.append(_header_table("DEVIATION & CAPA REPORT", doc_ref, today_str))
        elements.append(Spacer(1, 0.4 * cm))

        # Classification badge
        badge = Table(
            [[Paragraph(f"<b>CLASSIFICATION: {classification}</b>",
                        ParagraphStyle("badge", fontSize=11, fontName="Helvetica-Bold",
                                       textColor=colors.white))]],
            colWidths=[17.5 * cm],
        )
        badge.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor(cls_color)),
            ("PADDINGTOP",    (0, 0), (-1, -1), 6),
            ("PADDINGBOTTOM", (0, 0), (-1, -1), 6),
            ("PADDINGLEFT",   (0, 0), (-1, -1), 12),
        ]))
        elements.append(badge)
        elements.append(Spacer(1, 0.3 * cm))

        elements += _section("Deviation Details", styles)
        elements.append(_kv_table([
            ("Deviation ID",         doc_ref),
            ("Trigger Type",         data.get("trigger_type", "—")),
            ("Start Date",           data.get("investigation_start_date", "—")),
            ("Responsible Dept.",    data.get("responsible_department", "—")),
            ("Responsible Person",   data.get("responsible_person", "—")),
            ("Current Status",       data.get("status", "—").upper()),
        ]))

        # Observation
        if data.get("observation"):
            elements += _section("Observation / Non-Conformance", styles)
            elements.append(Paragraph(data["observation"], styles["BodyText2"]))

        if data.get("impact_assessment"):
            elements += _section("Impact Assessment", styles)
            elements.append(Paragraph(data["impact_assessment"], styles["BodyText2"]))

        if data.get("recommendations"):
            elements += _section("Immediate Corrective Actions", styles)
            elements.append(Paragraph(data["recommendations"], styles["BodyText2"]))

        # CAPA actions table
        capa = data.get("capa_actions") or []
        if capa:
            elements += _section("CAPA Action Plan", styles)
            rows = [["#", "Action", "Owner", "Due Date", "Status"]]
            for i, a in enumerate(capa, 1):
                rows.append([
                    str(i),
                    a.get("action", "—"),
                    a.get("owner", "—"),
                    str(a.get("due_date", "—")),
                    (a.get("status") or "open").upper(),
                ])
            capa_t = Table(rows, colWidths=[1 * cm, 6.5 * cm, 3.5 * cm, 3 * cm, 3.5 * cm])
            capa_t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F4F9")]),
                ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#EEEEEE")),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("PADDING",       (0, 0), (-1, -1), 4),
            ]))
            elements.append(capa_t)

        # Sign-off
        elements += _section("Approval & Closure", styles)
        elements.append(_kv_table([
            ("Investigating Officer", "__________________________"),
            ("QA Manager Approved",  "__________________________"),
            ("Close-Out Date",       data.get("closed_at") or "______________"),
        ]))

        # Knowledge Base Reference (injected when available)
        kb_ctx = (data.get("kb_context") or "").strip()
        if kb_ctx:
            elements += _section("Knowledge Base Reference", styles)
            elements.append(Paragraph(
                "The following content from the compliance knowledge base was referenced "
                "during report preparation:",
                styles["SmallLabel"],
            ))
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph(kb_ctx[:3000], styles["BodyText2"]))

        _build_pdf(elements, buf)
        return buf.getvalue()

    # ── Maintenance Certificate ────────────────────────────────────────────────

    def render_maintenance_certificate(self, data: Dict[str, Any]) -> bytes:
        """Generate a preventive-maintenance completion certificate PDF.

        Expected keys: equipment_name, equipment_type, location, serial_number,
          maintenance_type, last_maintenance_date, next_maintenance_date,
          performed_by, completion_notes, certificate_id
        """
        if not _REPORTLAB_OK:
            raise RuntimeError("reportlab is not installed")

        styles = _make_styles()
        buf = io.BytesIO()
        today_str = str(date.today())
        cert_id = data.get("certificate_id", "CERT-UNKNOWN")

        elements = []
        elements.append(_header_table("MAINTENANCE CERTIFICATE", cert_id, today_str))
        elements.append(Spacer(1, 0.6 * cm))
        elements.append(Paragraph("CERTIFICATE OF MAINTENANCE COMPLETION",
                                   styles["BrandTitle"]))
        elements.append(Paragraph(
            "This document certifies that the maintenance activity described below was "
            "carried out in accordance with the applicable SOP.",
            styles["BodyText2"],
        ))
        elements.append(Spacer(1, 0.5 * cm))

        elements += _section("Equipment Details", styles)
        elements.append(_kv_table([
            ("Equipment Name",     data.get("equipment_name", "—")),
            ("Equipment Type",     data.get("equipment_type", "—")),
            ("Location",           data.get("location", "—")),
            ("Serial Number",      data.get("serial_number", "—")),
            ("Maintenance Type",   data.get("maintenance_type", "—").title()),
            ("Date Performed",     str(data.get("last_maintenance_date", "—"))),
            ("Next Maintenance",   str(data.get("next_maintenance_date", "—"))),
            ("Performed By",       data.get("performed_by", "—")),
        ]))

        if data.get("completion_notes"):
            elements += _section("Works Performed / Notes", styles)
            elements.append(Paragraph(data["completion_notes"], styles["BodyText2"]))

        elements += _section("Certification", styles)
        elements.append(_kv_table([
            ("Technician Signature",     "__________________________"),
            ("QA Reviewer Signature",   "__________________________"),
            ("Certificate Issued Date",  today_str),
        ]))

        _build_pdf(elements, buf)
        return buf.getvalue()

    # ── Recall Notice ─────────────────────────────────────────────────────────

    def render_recall_notice(self, data: Dict[str, Any]) -> bytes:
        """Generate a product recall customer notification PDF.

        Expected keys: recall_id, batch_number, product_name, recall_reason,
          initiation_date, scope, regulatory_authority, customer_list (list of str)
        """
        if not _REPORTLAB_OK:
            raise RuntimeError("reportlab is not installed")

        styles = _make_styles()
        buf = io.BytesIO()
        today_str = str(date.today())
        doc_ref = data.get("recall_id", "RECALL-UNKNOWN")

        elements = []
        elements.append(_header_table("PRODUCT RECALL NOTICE", doc_ref, today_str))

        # Urgent banner
        urgent = Table(
            [[Paragraph(
                "<b>URGENT — PRODUCT RECALL NOTICE</b>",
                ParagraphStyle("urg", fontSize=13, fontName="Helvetica-Bold",
                               textColor=colors.white),
            )]],
            colWidths=[17.5 * cm],
        )
        urgent.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#C0392B")),
            ("PADDINGTOP",    (0, 0), (-1, -1), 8),
            ("PADDINGBOTTOM", (0, 0), (-1, -1), 8),
            ("PADDINGLEFT",   (0, 0), (-1, -1), 12),
        ]))
        elements.append(Spacer(1, 0.4 * cm))
        elements.append(urgent)
        elements.append(Spacer(1, 0.4 * cm))

        elements += _section("Recall Details", styles)
        elements.append(_kv_table([
            ("Recall Reference",     doc_ref),
            ("Product Name",         data.get("product_name", "—")),
            ("Affected Batch(es)",   data.get("batch_number", "—")),
            ("Recall Category",      data.get("scope", "voluntary").title()),
            ("Regulatory Authority", data.get("regulatory_authority", "NAFDAC")),
            ("Initiation Date",      str(data.get("initiation_date", today_str))),
        ]))

        elements += _section("Reason for Recall", styles)
        elements.append(Paragraph(data.get("recall_reason", "See attached investigation report."),
                                   styles["BodyText2"]))

        elements += _section("Required Immediate Actions", styles)
        for action in [
            "CEASE distribution of all units from the affected batch immediately.",
            "QUARANTINE all remaining stock in a locked, clearly labelled area.",
            "COMPLETE the attached product recovery form within 48 hours.",
            "RETURN all affected stock to Placeware Nigeria using the provided instructions.",
            "DO NOT use or dispense any units from the recalled batch.",
        ]:
            elements.append(Paragraph(f"  ► {action}", styles["BodyText2"]))

        contacts = [
            ("Quality Assurance", "qa@placewarenigeria.com"),
            ("Operations",        "ops@placewarenigeria.com"),
            ("Regulatory",        "+234 800 PLACEWARE"),
        ]
        elements += _section("Contact Information", styles)
        elements.append(_kv_table(contacts))

        _build_pdf(elements, buf)
        return buf.getvalue()

    # ── Recall Investigation Report ────────────────────────────────────────────

    def render_recall_investigation(self, data: Dict[str, Any]) -> bytes:
        """Generate a recall root-cause investigation report PDF.

        Expected keys: recall_id, batch_number, product_name, recall_reason,
          root_cause_analysis, capa_actions (list), findings (list), status
        """
        if not _REPORTLAB_OK:
            raise RuntimeError("reportlab is not installed")

        styles = _make_styles()
        buf = io.BytesIO()
        today_str = str(date.today())
        doc_ref = f"{data.get('recall_id', 'RECALL-?')}-INVESTIGATION"

        elements = []
        elements.append(_header_table("RECALL INVESTIGATION REPORT", doc_ref, today_str))
        elements.append(Spacer(1, 0.4 * cm))

        elements += _section("Recall Reference", styles)
        elements.append(_kv_table([
            ("Recall ID",      data.get("recall_id", "—")),
            ("Product",        data.get("product_name", "—")),
            ("Batch Number",   data.get("batch_number", "—")),
            ("Status",         data.get("status", "—").upper()),
            ("Report Date",    today_str),
        ]))

        if data.get("recall_reason"):
            elements += _section("Recall Reason", styles)
            elements.append(Paragraph(data["recall_reason"], styles["BodyText2"]))

        if data.get("root_cause_analysis"):
            elements += _section("Root Cause Analysis", styles)
            elements.append(Paragraph(data["root_cause_analysis"], styles["BodyText2"]))

        findings = data.get("findings") or []
        if findings:
            elements += _section("Investigation Findings", styles)
            for i, f in enumerate(findings, 1):
                elements.append(Paragraph(f"  {i}. {f}", styles["BodyText2"]))

        capa = data.get("capa_actions") or []
        if capa:
            elements += _section("CAPA / Preventive Actions", styles)
            rows = [["#", "Action", "Owner", "Due Date", "Status"]]
            for i, a in enumerate(capa, 1):
                rows.append([str(i), a.get("action", "—"), a.get("owner", "—"),
                              str(a.get("due_date", "—")), (a.get("status") or "open").upper()])
            t = Table(rows, colWidths=[1 * cm, 7 * cm, 3.5 * cm, 3 * cm, 3 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F4F9")]),
                ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#EEEEEE")),
                ("PADDING",       (0, 0), (-1, -1), 4),
            ]))
            elements.append(t)

        _build_pdf(elements, buf)
        return buf.getvalue()

    # ── Recall Distribution Trace (XLSX) ───────────────────────────────────────

    def render_recall_distribution_trace(self, data: Dict[str, Any]) -> bytes:
        """Generate a distribution trace spreadsheet (XLSX) for a recall.

        Expected keys: recall_id, batch_number, product_name,
          distribution_data (list of {customer_name, location, qty,
          delivered_at, recovered_qty, status})
        """
        if not _XLSX_OK:
            raise RuntimeError("openpyxl is not installed")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Distribution Trace"

        navy = "1E3A5F"
        green = "2D6A4F"
        light = "F0F4F9"

        header_font = Font(bold=True, color="FFFFFF", size=10)
        sub_font    = Font(bold=True, color="FFFFFF", size=9)
        body_font   = Font(size=9)

        # Title row
        ws.merge_cells("A1:H1")
        c = ws["A1"]
        c.value = f"DISTRIBUTION TRACE — {data.get('recall_id','RECALL')} — {data.get('product_name','')}"
        c.font = Font(bold=True, color="FFFFFF", size=12)
        c.fill = PatternFill("solid", fgColor=navy)
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 24

        # Sub-header
        ws.merge_cells("A2:H2")
        c2 = ws["A2"]
        c2.value = (
            f"Batch: {data.get('batch_number','—')}   "
            f"Product: {data.get('product_name','—')}   "
            f"Generated: {date.today()}"
        )
        c2.font = sub_font
        c2.fill = PatternFill("solid", fgColor=green)
        c2.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[2].height = 18

        # Column headers
        headers = ["#", "Customer Name", "Location", "Qty Delivered",
                   "Delivered On", "Qty Recovered", "Recovery Status", "Notes"]
        col_widths = [4, 28, 20, 15, 16, 15, 18, 30]
        for col, (h, w) in enumerate(zip(headers, col_widths), 1):
            cell = ws.cell(row=3, column=col, value=h)
            cell.font = Font(bold=True, color="FFFFFF", size=9)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center")
            ws.column_dimensions[cell.column_letter].width = w

        thin = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )

        distribution = data.get("distribution_data") or []
        for i, row_data in enumerate(distribution):
            row_num = 4 + i
            fill = PatternFill("solid", fgColor=light) if i % 2 == 0 else None
            row_values = [
                i + 1,
                row_data.get("customer_name", "—"),
                row_data.get("location", "—"),
                row_data.get("qty", 0),
                str(row_data.get("delivered_at", "—")),
                row_data.get("recovered_qty", "—"),
                (row_data.get("status") or "pending").title(),
                row_data.get("notes", ""),
            ]
            for col, val in enumerate(row_values, 1):
                cell = ws.cell(row=row_num, column=col, value=val)
                cell.font = body_font
                cell.border = thin
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if fill:
                    cell.fill = fill

        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:H{3 + len(distribution)}"

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # ── SOP Summary ───────────────────────────────────────────────────────────

    def render_sop_summary(self, data: Dict[str, Any]) -> bytes:
        """Generate a SOP index / summary PDF.

        Expected keys: category_label, sops (list of {sop_id, title,
          version, effective_from, owner_department, status, description})
        """
        if not _REPORTLAB_OK:
            raise RuntimeError("reportlab is not installed")

        styles = _make_styles()
        buf = io.BytesIO()
        today_str = str(date.today())

        elements = []
        elements.append(_header_table(
            f"SOP INDEX — {data.get('category_label','All Categories').upper()}",
            "SOP-INDEX",
            today_str,
        ))
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(Paragraph(
            "This document lists all Standard Operating Procedures in the selected category. "
            "Only SOPs with status 'active' are referenced for current operations.",
            styles["BodyText2"],
        ))

        sops = data.get("sops") or []
        if sops:
            rows = [["SOP ID", "Title", "Ver.", "Effective From", "Department", "Status"]]
            for s in sops:
                rows.append([
                    s.get("sop_id", "—"),
                    s.get("title", "—"),
                    s.get("version", "—"),
                    str(s.get("effective_from", "—")),
                    s.get("owner_department", "—"),
                    (s.get("status") or "active").upper(),
                ])
            t = Table(rows, colWidths=[2.5 * cm, 6 * cm, 1.5 * cm, 3 * cm, 3 * cm, 1.5 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND",     (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
                ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",       (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F4F9")]),
                ("BOX",            (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("INNERGRID",      (0, 0), (-1, -1), 0.25, colors.HexColor("#EEEEEE")),
                ("VALIGN",         (0, 0), (-1, -1), "TOP"),
                ("PADDING",        (0, 0), (-1, -1), 4),
            ]))
            elements += _section(f"SOPs ({len(sops)} total)", styles)
            elements.append(t)

        _build_pdf(elements, buf)
        return buf.getvalue()
