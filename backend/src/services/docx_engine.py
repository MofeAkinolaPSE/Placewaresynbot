"""
Branded DOCX engine — ACE / Placeware
=====================================
One Word renderer for every document the app exports (narrative reports,
client invoices, and anything added later), so branding and layout live in a
single place instead of being re-implemented per endpoint.

Companion to document_engine.py, which does the same job for ReportLab PDFs.

Why this module exists
----------------------
The previous hand-rolled builder in routers/reports.py produced visibly broken
documents. The defects it fixes, all confirmed against a real export:

  * Every list paragraph used the stock "List Number" style with no numbering
    id of its own, so Word ran ONE sequence through the whole file -- the table
    of contents was 1-9 and body bullets carried on at 10, 11, ... 42.
    Here bullets are bullets, and ordered lists carry their own literal
    numbers, so a list can never inherit a neighbour's counter.
  * The markdown "parser" understood only #/##/###, ---, N., -, * and **bold**.
    Everything else reached the page as source text: 39 literal backticks in
    one report, and pipe-table rows rendered as numbered paragraphs
    ("Financial | SEVERE | ..."). Tables, inline code, links, headings deeper
    than ###, blockquotes and fenced code are all handled here.
  * No logo, no real header/footer parts, so no page numbers anywhere.
  * "-" * 72 used as a horizontal rule, which wraps onto a second line at
    Calibri 11 on A4. Real paragraph borders are used instead.
  * doc.add_paragraph("") after every block, which is why ~38% of the
    paragraphs in a generated report were empty. Spacing comes from styles.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

logger = logging.getLogger(__name__)

# ── Brand palette (kept in step with document_engine.py) ──────────────────────
NAVY = RGBColor(0x1E, 0x3A, 0x5F)
GREEN = RGBColor(0x2D, 0x6A, 0x4F)
GREY = RGBColor(0x66, 0x66, 0x66)
LIGHT_GREY = RGBColor(0x99, 0x99, 0x99)
RED = RGBColor(0xCC, 0x00, 0x00)

NAVY_HEX = "1E3A5F"
LIGHT_HEX = "F0F4F9"
BORDER_HEX = "D5DDE7"

BODY_FONT = "Calibri"
HEAD_FONT = "Calibri"

# Must resolve inside the container: backend/Dockerfile copies only app.py,
# seed_admin.py, src/, config.yaml, config/, migrations/ and scripts/ -- so an
# asset anywhere outside src/ simply would not exist at runtime.
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "placeware-logo.png"

COMPANY_NAME = "PLACEWARE NIGERIA LIMITED"
CONFIDENTIALITY = "CONFIDENTIAL — For Authorised Recipients Only"


# ── Low-level OOXML helpers ───────────────────────────────────────────────────

def _shade(element, hex_fill: str) -> None:
    """Apply a background fill to a table cell or paragraph."""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    element.append(shd)


def _bottom_border(paragraph, hex_color: str = BORDER_HEX, size: int = 6) -> None:
    """A real paragraph border — the previous builder drew rules with 72 box
    characters, which wrap onto a second line on A4."""
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), hex_color)
    borders.append(bottom)
    p_pr.append(borders)


def _field(paragraph, instruction: str) -> None:
    """Insert a Word field code (used for PAGE / NUMPAGES)."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


# ── Document setup ────────────────────────────────────────────────────────────

def _style(doc, name: str, *, size: int, bold: bool = False,
           color: Optional[RGBColor] = None, space_before: int = 0,
           space_after: int = 6, font: str = BODY_FONT):
    """Define (or redefine) a paragraph style so the document stops depending
    on python-docx's stock template, whose Word-blue Calibri Light headings are
    what made generated reports look like nobody had designed them."""
    from docx.enum.style import WD_STYLE_TYPE

    styles = doc.styles
    try:
        st = styles[name]
    except KeyError:
        st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    st.font.name = font
    st.font.size = Pt(size)
    st.font.bold = bold
    if color is not None:
        st.font.color.rgb = color
    pf = st.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.keep_with_next = bold and size >= 13
    return st


def new_document() -> Any:
    """A4 document with Placeware styles already defined."""
    doc = DocxDocument()

    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Inches(1.0)
    sec.right_margin = Inches(1.0)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    _style(doc, "ACE Title", size=22, bold=True, color=NAVY, space_after=4, font=HEAD_FONT)
    _style(doc, "ACE Subtitle", size=11, color=GREY, space_after=10)
    _style(doc, "ACE H1", size=16, bold=True, color=NAVY, space_before=16, space_after=6, font=HEAD_FONT)
    _style(doc, "ACE H2", size=13, bold=True, color=GREEN, space_before=12, space_after=4, font=HEAD_FONT)
    _style(doc, "ACE H3", size=11.5, bold=True, color=NAVY, space_before=9, space_after=3, font=HEAD_FONT)
    _style(doc, "ACE Body", size=10.5, space_after=6)
    _style(doc, "ACE Caption", size=8.5, color=LIGHT_GREY, space_after=8)
    _style(doc, "ACE Quote", size=10.5, color=GREY, space_after=6)

    code = _style(doc, "ACE Code", size=9, space_after=6, font="Consolas")
    code.paragraph_format.left_indent = Inches(0.25)

    bullet = _style(doc, "ACE Bullet", size=10.5, space_after=3)
    bullet.paragraph_format.left_indent = Inches(0.3)
    bullet.paragraph_format.first_line_indent = Inches(-0.18)

    return doc


def add_logo_header(doc) -> None:
    """Logo in a real header part, so it repeats on every page."""
    header = doc.sections[0].header
    para = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if LOGO_PATH.exists():
        try:
            para.add_run().add_picture(str(LOGO_PATH), width=Inches(1.35))
            return
        except Exception as exc:  # pragma: no cover - corrupt asset shouldn't 500
            logger.warning("docx_engine: could not embed logo: %s", exc)
    run = para.add_run(COMPANY_NAME)
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = GREEN


def add_footer(doc, note: str = CONFIDENTIALITY) -> None:
    """Confidentiality line + 'Page X of Y'. There was previously no footer
    part at all, so no generated report had page numbers."""
    footer = doc.sections[0].footer
    para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(f"{note}    |    Page ")
    run.font.size = Pt(8)
    run.font.color.rgb = LIGHT_GREY
    _field(para, "PAGE")
    mid = para.add_run(" of ")
    mid.font.size = Pt(8)
    mid.font.color.rgb = LIGHT_GREY
    _field(para, "NUMPAGES")
    for r in para.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = LIGHT_GREY


def add_cover_logo(doc) -> None:
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if LOGO_PATH.exists():
        try:
            para.add_run().add_picture(str(LOGO_PATH), width=Inches(2.4))
            return
        except Exception as exc:  # pragma: no cover
            logger.warning("docx_engine: could not embed cover logo: %s", exc)
    run = para.add_run(COMPANY_NAME)
    run.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = GREEN


def rule(doc) -> None:
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(8)
    _bottom_border(para)


# ── Inline markdown ───────────────────────────────────────────────────────────

_INLINE_RE = re.compile(
    r"(\*\*\*.+?\*\*\*"          # ***bold italic***
    r"|\*\*.+?\*\*"              # **bold**
    r"|__.+?__"                  # __bold__
    r"|\*[^*\s].*?[^*\s]\*"      # *italic*
    r"|\*[^*\s]\*"               # *i*
    r"|`[^`]+`"                  # `code`
    r"|\[[^\]]+\]\([^)]*\))",    # [text](url)
    re.S,
)


def add_inline(paragraph, text: str, *, base_size: Optional[float] = None,
               color: Optional[RGBColor] = None) -> None:
    """Render inline markdown into runs.

    The old renderer handled only **bold**/*italic*, so backticks and links
    reached the page verbatim -- one sampled report contained 39 literal
    backticks.
    """
    if not text:
        return

    def _mk(chunk: str, *, bold=False, italic=False, mono=False):
        run = paragraph.add_run(chunk)
        run.bold = bold
        run.italic = italic
        if mono:
            run.font.name = "Consolas"
            run.font.size = Pt((base_size or 10.5) - 0.5)
        elif base_size:
            run.font.size = Pt(base_size)
        if color is not None:
            run.font.color.rgb = color
        return run

    for token in _INLINE_RE.split(text):
        if not token:
            continue
        if token.startswith("***") and token.endswith("***") and len(token) > 6:
            _mk(token[3:-3], bold=True, italic=True)
        elif token.startswith("**") and token.endswith("**") and len(token) > 4:
            _mk(token[2:-2], bold=True)
        elif token.startswith("__") and token.endswith("__") and len(token) > 4:
            _mk(token[2:-2], bold=True)
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            _mk(token[1:-1], mono=True)
        elif token.startswith("[") and "](" in token:
            label = token[1 : token.index("](")]
            _mk(label, italic=False)
        elif token.startswith("*") and token.endswith("*") and len(token) > 2:
            _mk(token[1:-1], italic=True)
        else:
            _mk(token)


# ── Block markdown ────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

_HEADING_STYLES = {1: "ACE H1", 2: "ACE H2", 3: "ACE H3"}


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|") and line.strip().count("|") >= 2


def add_table(doc, rows: Sequence[Sequence[str]]) -> None:
    """Render a real Word table. Markdown tables previously came out as
    pipe-delimited numbered paragraphs, e.g. 'Financial | SEVERE | ...'."""
    rows = [r for r in rows if r]
    if not rows:
        return
    width = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for r_idx, row in enumerate(rows):
        for c_idx in range(width):
            cell = table.cell(r_idx, c_idx)
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(2)
            value = row[c_idx] if c_idx < len(row) else ""
            if r_idx == 0:
                _shade(cell._tc.get_or_add_tcPr(), NAVY_HEX)
                run = para.add_run(re.sub(r"[*`]", "", value))
                run.bold = True
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            else:
                add_inline(para, value, base_size=9.5)
    doc.add_paragraph(style="ACE Caption")


def render_markdown(doc, markdown: str) -> None:
    """Render a markdown body into the document.

    Deliberately handles everything the LLM is actually prompted to emit
    (report_generation_agent asks for '###', numbered lists and '**bold**',
    and the model additionally produces '####', tables, inline code and
    links). Anything unrecognised is emitted as plain text rather than being
    dropped, so content is never silently lost.
    """
    if not markdown:
        return

    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)

    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            if buf:
                para = doc.add_paragraph(style="ACE Code")
                _shade(para._p.get_or_add_pPr(), LIGHT_HEX)
                para.add_run("\n".join(buf))
            continue

        # Table
        if _is_table_row(line) and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_row(line)
            i += 2  # header + separator
            body: list[list[str]] = []
            while i < n and _is_table_row(lines[i]):
                body.append(_split_row(lines[i]))
                i += 1
            add_table(doc, [header] + body)
            continue

        # Horizontal rule
        if _HR_RE.match(stripped):
            rule(doc)
            i += 1
            continue

        # Heading
        m = _HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if text:
                style = _HEADING_STYLES.get(min(level, 3), "ACE H3")
                para = doc.add_paragraph(style=style)
                add_inline(para, text)
            i += 1
            continue

        # Blockquote
        m = _QUOTE_RE.match(stripped)
        if m:
            para = doc.add_paragraph(style="ACE Quote")
            para.paragraph_format.left_indent = Inches(0.3)
            _bottom_border(para, BORDER_HEX, 4)
            add_inline(para, m.group(1))
            i += 1
            continue

        # Ordered list. The number is written as literal text with a hanging
        # indent rather than using Word's List Number style: that style, used
        # without a per-list numbering id, is exactly what made one shared
        # sequence run 1..42 through an entire report.
        m = _ORDERED_RE.match(line)
        if m:
            counter = 1
            while i < n:
                mm = _ORDERED_RE.match(lines[i])
                if not mm:
                    break
                indent = len(mm.group(1)) // 2
                para = doc.add_paragraph(style="ACE Bullet")
                para.paragraph_format.left_indent = Inches(0.3 + 0.25 * indent)
                num = para.add_run(f"{counter}. ")
                num.bold = True
                add_inline(para, mm.group(3))
                counter += 1
                i += 1
            continue

        # Bullet list
        m = _BULLET_RE.match(line)
        if m:
            while i < n:
                mm = _BULLET_RE.match(lines[i])
                if not mm:
                    break
                indent = len(mm.group(1)) // 2
                para = doc.add_paragraph(style="ACE Bullet")
                para.paragraph_format.left_indent = Inches(0.3 + 0.25 * indent)
                para.add_run("• " if indent == 0 else "– ")
                add_inline(para, mm.group(2))
                i += 1
            continue

        # Plain paragraph — join soft-wrapped lines into one block
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or _HEADING_RE.match(nxt) or _HR_RE.match(nxt)
                    or _BULLET_RE.match(lines[i]) or _ORDERED_RE.match(lines[i])
                    or _is_table_row(nxt) or nxt.startswith("```") or _QUOTE_RE.match(nxt)):
                break
            buf.append(nxt)
            i += 1
        para = doc.add_paragraph(style="ACE Body")
        add_inline(para, " ".join(buf))


# ── Composite blocks ──────────────────────────────────────────────────────────

def add_cover(doc, *, title: str, subtitle: str = "",
              badge: Optional[str] = None, badge_ok: bool = False,
              meta: Optional[Iterable[tuple[str, str]]] = None) -> None:
    """Branded cover page."""
    doc.add_paragraph(style="ACE Caption")
    add_cover_logo(doc)

    sub = doc.add_paragraph(style="ACE Subtitle")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(subtitle or "Enterprise AI Intelligence Report")

    if badge:
        bp = doc.add_paragraph()
        bp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = bp.add_run(f"[ {badge} ]")
        run.bold = True
        run.font.size = Pt(14)
        run.font.color.rgb = GREEN if badge_ok else RED

    rule(doc)

    tp = doc.add_paragraph(style="ACE Title")
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tp.add_run((title or "Report").upper())

    for label, value in (meta or []):
        mp = doc.add_paragraph(style="ACE Body")
        mp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        mp.paragraph_format.space_after = Pt(2)
        lab = mp.add_run(f"{label}: ")
        lab.bold = True
        lab.font.color.rgb = NAVY
        lab.font.size = Pt(10)
        val = mp.add_run(str(value))
        val.font.color.rgb = GREY
        val.font.size = Pt(10)

    rule(doc)


def add_contents(doc, titles: Sequence[str]) -> None:
    if not titles:
        return
    head = doc.add_paragraph(style="ACE H1")
    head.add_run("Table of Contents")
    for idx, title in enumerate(titles, start=1):
        para = doc.add_paragraph(style="ACE Bullet")
        num = para.add_run(f"{idx}. ")
        num.bold = True
        para.add_run(str(title))


def add_signoff(doc, roles: Sequence[str] = ("Prepared By", "Reviewed By", "Approved By")) -> None:
    head = doc.add_paragraph(style="ACE H1")
    head.add_run("Sign-Off & Approval")
    add_table(doc, [["Role", "Name & Signature", "Date"]] + [[r, "", ""] for r in roles])


def serialize(doc) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
