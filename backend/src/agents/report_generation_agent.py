"""
ReportGenerationAgent — Template-driven, section-by-section report generation.
===============================================================================
Responsibilities:
  • Detect report type from natural language request using REPORT_TEMPLATE_REGISTRY
  • Accept optional session_id to load pre-collected scope params and evidence notes
  • Retrieve RAG context: SOPs + NAFDAC docs from main match_documents index
  • Pull past reports from placeware_report_memory as improvement baselines
  • Query live Supabase data with scope-aware WHERE filters (date, dept, etc.)
  • Generate each report section INDEPENDENTLY via focused LLM prompts
  • Validate each section for completeness before moving on
  • Self-score the full report (1-10); store in memory only if score >= 7
  • Return Insight.findings (full text) + metrics with per-section data

Context keys consumed:
    intent_text   str   — user request e.g. "generate a deviation report"
    report_type   str   — optional override; if absent, auto-detected
    session_id    str   — optional; links to placeware_report_sessions row
    scope_params  dict  — optional; date_from, date_to, department, etc.
    actor_id      str   — for audit log
    simulation    bool  — if True, skip Supabase memory write
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight
from src.report_templates import (
    REPORT_TEMPLATE_REGISTRY,
    detect_report_type,
    get_template,
    TEMPLATE_VERSION,
)

logger = logging.getLogger(__name__)

# Keep legacy alias so any external callers using _REPORT_REGISTRY still work
_REPORT_REGISTRY: Dict[str, Dict[str, Any]] = {
    rtype: {
        "keywords": cfg.get("keywords", []),
        "tables": cfg.get("tables", []),
        "section_title": cfg.get("output_title", rtype.replace("_", " ").title()),
        **({k: v for k, v in cfg.items() if k in ("is_executive", "delegate_to", "is_invoice")}),
    }
    for rtype, cfg in REPORT_TEMPLATE_REGISTRY.items()
}

# ── Shim: sales / payroll / pl / ar_aging / frontdesk section_titles ─────────
# (kept for any legacy route that calls _REPORT_REGISTRY["sales"]["section_title"])
for _rt, _cfg in _REPORT_REGISTRY.items():
    if "section_title" not in _cfg:
        _cfg["section_title"] = REPORT_TEMPLATE_REGISTRY.get(_rt, {}).get(
            "output_title", _rt.replace("_", " ").title()
        )

# ── Sales keywords shim (in case _REPORT_REGISTRY["sales"] is accessed) ──────
_REPORT_REGISTRY.setdefault("sales", {}).setdefault("keywords", [
    "sales report", "weekly sales", "pipeline report", "crm report", "lead report",
    "sales performance", "revenue report", "sales summary", "sales activity",
])
_REPORT_REGISTRY.setdefault("sales", {}).setdefault("tables", [
    {"table": "crm_sales_pipeline", "select": "*", "order": "created_at", "limit": 100},
    {"table": "crm_lead_activity_log", "select": "*", "order": "created_at", "limit": 50},
])
_REPORT_REGISTRY["sales"]["section_title"] = "Sales & Pipeline Performance Report"

# Default if nothing matches
_DEFAULT_REPORT_TYPE = "executive"


@register_agent
class ReportGenerationAgent(BaseAgent):
    """
    Template-driven, section-by-section report generation agent.

    Generation lifecycle:
      1. Detect / load report type + template from REPORT_TEMPLATE_REGISTRY
      2. Load scope params from context or linked report session
      3. Retrieve RAG context + past reports + live data (scope-filtered)
      4. Generate each template section independently via focused LLM prompts
      5. Validate each section; mark incomplete if it fails twice
      6. Assemble full_report + per-section metadata
      7. Self-score; persist to placeware_report_memory if score >= 7
    """

    name = "report_generation_agent"
    required_role = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        """Detect report type, load session/scope, retrieve RAG + live data."""
        intent_text = self.context.get("intent_text", "")
        report_type = (
            self.context.get("report_type")
            or detect_report_type(intent_text)
        )

        # Load scope from context first, then from linked session
        scope_params = dict(self.context.get("scope_params") or {})
        session_id   = self.context.get("session_id")
        if session_id and not scope_params:
            scope_params = self._load_session_scope(session_id)

        rag_context  = self._retrieve_rag(intent_text)
        past_reports = self._get_past_reports(report_type, limit=3)
        live_data    = self._fetch_live_data(report_type, scope_params)
        memories     = self._get_memories(intent_text)

        return {
            "intent_text":   intent_text,
            "report_type":   report_type,
            "scope_params":  scope_params,
            "session_id":    session_id,
            "rag_context":   rag_context,
            "past_reports":  past_reports,
            "live_data":     live_data,
            "memories":      memories,
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate each report section independently, then assemble the full report."""
        report_type  = data["report_type"]
        intent_text  = data["intent_text"]
        scope_params = data["scope_params"]
        rag_context  = data["rag_context"]
        past_reports = data["past_reports"]
        live_data    = data["live_data"]
        memories     = data["memories"]

        template      = get_template(report_type)
        section_title = template.get("output_title", report_type.replace("_", " ").title())
        sections      = sorted(template.get("sections", []), key=lambda s: s["order"])

        section_results = self._generate_sections(
            sections=sections,
            intent_text=intent_text,
            report_type=report_type,
            section_title=section_title,
            rag_context=rag_context,
            past_reports=past_reports,
            live_data=live_data,
            memories=memories,
            scope_params=scope_params,
        )

        # Assemble full markdown document from sections
        full_report = self._assemble_report(
            section_title=section_title,
            report_type=report_type,
            sections=section_results,
        )

        quality_score = self._self_score(full_report, report_type)
        structured    = self._extract_structured(full_report)

        return {
            "report_type":    report_type,
            "section_title":  section_title,
            "full_report":    full_report,
            "structured":     structured,
            "section_results": section_results,
            "quality_score":  quality_score,
            "live_data_rows": len(live_data) if isinstance(live_data, list) else 0,
            "rag_hits":       len(rag_context),
            "past_count":     len(past_reports),
            "scope_params":   scope_params,
            "session_id":     data.get("session_id"),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        """Package the report as an Insight and persist to report memory."""
        report_type     = analysis["report_type"]
        full_report     = analysis["full_report"]
        structured      = analysis.get("structured", {})
        section_results = analysis.get("section_results", [])
        quality_score   = analysis.get("quality_score", 0.0)
        session_id      = analysis.get("session_id")
        simulation      = bool(self.context.get("simulation", False))

        report_memory_id: Optional[str] = None

        # ── Persist to report memory if quality ≥ 7 ─────────────────────────
        if not simulation and quality_score >= 7.0:
            report_memory_id = self._store_report(
                report_type=report_type,
                intent_text=self.context.get("intent_text", ""),
                full_report=full_report,
                summary=structured.get("summary", full_report[:500]),
                findings=structured.get("findings", []),
                recommendations=structured.get("recommendations", []),
                quality_score=quality_score,
                section_data=section_results,
                session_id=session_id,
            )
            # Store a memory so other agents can recall this pattern
            try:
                from src.services.agent_memory import AgentMemory
                AgentMemory(self.name).store(
                    findings=[structured.get("summary", full_report[:400])],
                    confidence=min(quality_score / 10.0, 1.0),
                    memory_type="finding",
                )
            except Exception:
                pass

        # Complete the session if one was provided
        if session_id and report_memory_id and not simulation:
            try:
                from src.services.report_session_service import complete_session
                complete_session(session_id, report_memory_id)
            except Exception as exc:
                logger.warning("ReportAgent: complete_session failed: %s", exc)

        findings = [full_report] if full_report else ["Report generation completed but produced no content."]

        return Insight(
            findings=findings,
            recommendations=structured.get("recommendations", []),
            confidence_score=min(quality_score / 10.0, 1.0),
            metrics={
                "report_type":       report_type,
                "quality_score":     quality_score,
                "rag_hits":          analysis.get("rag_hits", 0),
                "data_rows":         analysis.get("live_data_rows", 0),
                "past_reports_used": analysis.get("past_count", 0),
                "section_title":     analysis["section_title"],
                "full_report":       full_report,
                "summary":           structured.get("summary") or full_report[:400],
                "section_results":   section_results,
                "template_version":  TEMPLATE_VERSION,
                "report_memory_id":  report_memory_id,
                "session_id":        session_id,
            },
        )

    def write_cache(self, insight: Insight) -> None:
        pass  # Persisted inside generate_insights

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "findings": "list[str] — full report text",
            "metrics": {
                "report_type":      "str",
                "quality_score":    "float",
                "rag_hits":         "int",
                "section_results":  "list[dict] — per-section data",
                "template_version": "str",
            },
        }

    # ── Session / Scope loading ────────────────────────────────────────────────

    def _load_session_scope(self, session_id: str) -> Dict[str, Any]:
        """Fetch scope_params from a report session row."""
        try:
            from src.services.report_session_service import get_session
            session = get_session(session_id)
            return session.get("scope_params") or {}
        except Exception as exc:
            logger.warning("ReportAgent: load_session_scope failed: %s", exc)
            return {}

    # ── Detection (kept for legacy callers) ───────────────────────────────────

    def _detect_report_type(self, text: str) -> str:
        return detect_report_type(text)

    # ── RAG retrieval ──────────────────────────────────────────────────────────

    def _retrieve_rag(self, query: str, k: int = 5) -> List[Tuple[str, str]]:
        """Retrieve relevant SOP/NAFDAC/procedure context from the vector store."""
        try:
            from src.embed_proxy import get_embedding
            from src.retrieval import QnARetriever
            embedding = get_embedding(query)
            if embedding is None:
                return []
            retriever = QnARetriever()
            return retriever.retrieve(embedding, k=k)
        except Exception as exc:
            logger.warning(f"ReportAgent: RAG retrieval failed: {exc}")
            return []

    # ── Past report retrieval ─────────────────────────────────────────────────

    def _get_past_reports(self, report_type: str, limit: int = 3) -> List[Dict[str, Any]]:
        try:
            from src.db import db
            res = (
                db.table("placeware_report_memory")
                .select("summary, findings, recommendations, quality_score, created_at")
                .eq("report_type", report_type)
                .order("quality_score", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            logger.warning(f"ReportAgent: past report fetch failed: {exc}")
            return []

    # ── Live data (scope-aware) ───────────────────────────────────────────────

    def _fetch_live_data(self, report_type: str, scope_params: Optional[Dict] = None) -> Any:
        scope_params = scope_params or {}
        template = get_template(report_type)

        # Delegate financial data when needed
        if template.get("delegate_to") == "financial_analyst":
            return self._delegate_to_agent("financial_analyst")

        # Executive report pulls across multiple tables
        if template.get("is_executive"):
            return self._pull_executive_data()

        rows: List[Dict] = []
        try:
            from src.db import db
            for tbl_cfg in template.get("tables", []):
                tbl   = tbl_cfg.get("table")
                sel   = tbl_cfg.get("select", "*")
                lim   = tbl_cfg.get("limit", 50)
                order = tbl_cfg.get("order") or "imported_at"
                try:
                    q = db.table(tbl).select(sel).limit(lim)
                    if order:
                        q = q.order(order, desc=True)
                    # Apply scope date filters where column names exist
                    date_from = scope_params.get("date_from")
                    date_to   = scope_params.get("date_to")
                    if date_from and order:
                        q = q.gte(order, date_from)
                    if date_to and order:
                        q = q.lte(order, date_to)
                    # Department filter
                    dept = scope_params.get("department")
                    if dept:
                        q = q.eq("department", dept)
                    res = q.execute()
                    rows.extend(res.data or [])
                except Exception as exc:
                    logger.warning("ReportAgent: table %r fetch failed: %s", tbl, exc)
        except Exception as exc:
            logger.warning("ReportAgent: live data fetch failed: %s", exc)

        return rows

    def _delegate_to_agent(self, agent_name: str) -> Any:
        try:
            from src.agent_registry import get_agent
            from src.routers.agents_exec import create_db_executor, _get_default_specs_for_agent
            agent = get_agent(agent_name, context={
                "db_executor": create_db_executor(),
                "query_specs": _get_default_specs_for_agent(agent_name),
            })
            if agent:
                insight = agent.run()
                return {"metrics": insight.metrics, "findings": insight.findings}
        except Exception as exc:
            logger.warning(f"ReportAgent: delegate to {agent_name} failed: {exc}")
        return {}

    def _pull_executive_data(self) -> Dict[str, Any]:
        """Pull multi-table data for executive report from both DB and tool registry."""
        result: Dict[str, Any] = {}

        # Pull live tables defined in registry
        try:
            from src.db import db
            cfg = _REPORT_REGISTRY.get("executive", {})
            for tbl_cfg in cfg.get("tables", []):
                tbl = tbl_cfg.get("table")
                sel = tbl_cfg.get("select", "*")
                lim = tbl_cfg.get("limit", 30)
                order = tbl_cfg.get("order")
                try:
                    q = db.table(tbl).select(sel).limit(lim)
                    if order:
                        q = q.order(order, desc=True)
                    res = q.execute()
                    result[tbl] = res.data or []
                except Exception as exc:
                    logger.warning(f"ReportAgent: executive table {tbl!r} fetch failed: {exc}")
        except Exception as exc:
            logger.warning(f"ReportAgent: executive DB pull failed: {exc}")

        # Supplement with tool registry signals when available
        try:
            from src.services.tool_registry import ToolRegistry
            result["risk_signals"] = ToolRegistry.execute("getRiskSignals", {}, ["executive"], "executive")
        except Exception:
            pass

        return result

    def _get_memories(self, query: str) -> List[str]:
        try:
            from src.services.agent_memory import AgentMemory
            return AgentMemory(self.name).recall(query_text=query, k=3)
        except Exception:
            return []

    # ── Section-by-section generation ────────────────────────────────────────

    def _generate_sections(
        self,
        sections: List[Dict],
        intent_text: str,
        report_type: str,
        section_title: str,
        rag_context: List,
        past_reports: List,
        live_data: Any,
        memories: List,
        scope_params: Dict,
    ) -> List[Dict[str, Any]]:
        """
        Iterate through template sections and generate each independently.
        Returns a list of SectionResult dicts.
        """
        import json as _json
        from src.constants import BOT_NAME, BOT_BRAND

        # Build shared context blocks once
        rag_block = ""
        if rag_context:
            hits = "\n\n".join(f"Document: {r[0]}\n{r[1]}" for r in rag_context if r[1])
            rag_block = f"\n--- Regulatory/SOP Context ---\n{hits}\n"

        past_block = ""
        if past_reports:
            lines = []
            for i, p in enumerate(past_reports):
                lines.append(
                    f"Report {i+1} (score {p.get('quality_score',0)}/10, "
                    f"{str(p.get('created_at',''))[:10]}):\n  {p.get('summary','')[:300]}"
                )
            past_block = (
                f"\n--- Previous {report_type.title()} Reports (improve on these) ---\n"
                + "\n".join(lines) + "\n"
            )

        try:
            live_str = _json.dumps(live_data, default=str, indent=2)
            if len(live_str) > 8000:
                live_str = live_str[:8000] + "\n... [truncated]"
        except Exception:
            live_str = str(live_data)[:3000]
        live_block = f"\n--- Live Database Data ---\n{live_str}\n" if live_str else ""
        ground_truth_block = self._compute_ground_truth(live_data)

        memory_block = ""
        if memories:
            memory_block = "\n--- Historical Intelligence ---\n" + "\n".join(f"• {m}" for m in memories) + "\n"

        scope_block = ""
        if scope_params:
            scope_lines = [f"  {k}: {v}" for k, v in scope_params.items() if v]
            if scope_lines:
                scope_block = "\n--- Report Scope ---\n" + "\n".join(scope_lines) + "\n"

        improvement_note = (
            "\nIMPORTANT: Your report MUST be more specific, contain more data-backed findings, "
            "and sharper recommendations than the previous reports shown above."
            if past_reports else ""
        )

        def _generate_one(sec: Dict) -> Dict[str, Any]:
            sec_id    = sec["id"]
            sec_title = sec["title"]
            hint      = sec.get("prompt_hint", "")
            required  = sec.get("required", True)

            content = ""
            confidence = 0.0
            status = "incomplete"

            for attempt in range(2):
                try:
                    content, confidence = self._generate_section_content(
                        bot_name=BOT_NAME,
                        bot_brand=BOT_BRAND,
                        report_type=report_type,
                        section_title=section_title,
                        sec_title=sec_title,
                        hint=hint,
                        rag_block=rag_block,
                        past_block=past_block,
                        live_block=live_block,
                        ground_truth_block=ground_truth_block,
                        memory_block=memory_block,
                        scope_block=scope_block,
                        improvement_note=improvement_note,
                        intent_text=intent_text,
                    )
                    # Validate the section output
                    if self._validate_section(sec_id, content, required):
                        status = "complete"
                        break
                    logger.warning(
                        "ReportAgent: section %r failed validation (attempt %d)", sec_id, attempt + 1
                    )
                except Exception as exc:
                    logger.warning("ReportAgent: section %r generation error: %s", sec_id, exc)

            return {
                "section_id":       sec_id,
                "title":            sec_title,
                "content":          content,
                "confidence_score": round(confidence, 2),
                "status":           status,
                "order":            sec["order"],
            }

        # Each section is an independent DeepSeek call sharing only the
        # already-built context blocks above (no ordering dependency between
        # sections) -- run them concurrently on a thread pool instead of one
        # at a time. This class's lifecycle (BaseAgent.run() and everything
        # that calls it) is fully synchronous, so a thread pool -- not
        # asyncio -- matches the surrounding code; the bottleneck is I/O
        # (waiting on the HTTP response), so threads parallelize it fine
        # despite the GIL. Results are re-sorted by "order" below regardless
        # of completion order, and _assemble_report() re-sorts again anyway.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(sections), 8) or 1) as pool:
            results = list(pool.map(_generate_one, sections))

        results.sort(key=lambda r: r["order"])
        return results

    def _compute_ground_truth(self, live_data: Any) -> str:
        """
        Deterministically compute a small set of aggregate figures from
        live_data so every independently-generated section anchors on the
        same real totals, instead of each LLM call guessing its own number
        when the underlying data is sparse or empty.
        """
        if not isinstance(live_data, list):
            return ""
        if not live_data:
            return (
                "\n--- Ground Truth Figures (LOCKED) ---\n"
                "No live records were returned for this scope. State clearly that "
                "0 records were found for this period/filter — do NOT invent SKUs, "
                "counts, or totals to fill the section.\n"
            )

        numeric_totals: Dict[str, float] = {}
        for row in live_data:
            if not isinstance(row, dict):
                continue
            for key, val in row.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    numeric_totals[key] = numeric_totals.get(key, 0.0) + val

        lines = [f"Total records: {len(live_data)}"]
        for key, total in numeric_totals.items():
            lines.append(f"Sum of {key}: {round(total, 2)}")

        return (
            "\n--- Ground Truth Figures (LOCKED — you MUST use these exact numbers "
            "for any total/count; do not invent or recompute a different figure, and "
            "keep this consistent with any other section of the same report) ---\n"
            + "\n".join(lines) + "\n"
        )

    def _generate_section_content(
        self,
        bot_name: str,
        bot_brand: str,
        report_type: str,
        section_title: str,
        sec_title: str,
        hint: str,
        rag_block: str,
        past_block: str,
        live_block: str,
        ground_truth_block: str,
        memory_block: str,
        scope_block: str,
        improvement_note: str,
        intent_text: str,
    ) -> Tuple[str, float]:
        """
        Generate a single report section via LLM.
        Returns (content_text, confidence_score).
        confidence_score is estimated from content length and specificity heuristics.
        """
        prompt = f"""You are {bot_name}, the AI executive intelligence system for {bot_brand} (pharmaceutical distribution).

You are generating ONE SECTION of a {section_title}.
{scope_block}
{rag_block}
{past_block}
{live_block}
{ground_truth_block}
{memory_block}

SECTION TO GENERATE NOW: "{sec_title}"
Section guidance: {hint}

Original request: {intent_text}
{improvement_note}

Instructions:
- Write ONLY the content for the "{sec_title}" section. Do NOT repeat other sections.
- Use specific numbers, dates, and records from the live data above.
- If a "Ground Truth Figures" block is present, treat those numbers as locked facts —
  use them exactly as given rather than recomputing or estimating your own totals.
- Never fabricate data not present in the provided context.
- Be precise, business-grade, and actionable.
- Format with sub-headings (###), numbered lists, and **bold** key figures where appropriate.
- Minimum 3, maximum 6 meaningful, data-backed sentences. Do not pad the section with
  generic industry commentary to fill space — if there is little to report, say so briefly.

Begin the section content now (do NOT include the section heading itself):
"""
        from src.deepseek import DeepSeek
        llm = DeepSeek(os.getenv("DEEPSEEK_API_KEY", ""))
        content = llm.generate_response(
            context="",
            question=prompt,
            instruction=(
                f"You are {bot_name}, a senior business analyst. "
                "Generate ONLY the requested report section. "
                "Use real data. Be specific. 3-6 sentences, no padding."
            ),
            max_tokens=450,
        ).strip()

        # Heuristic confidence: longer + more numbers = higher confidence
        num_count = len(re.findall(r"\d+(?:\.\d+)?", content))
        word_count = len(content.split())
        confidence = min(0.95, 0.4 + (word_count / 400) * 0.3 + min(num_count / 10, 1) * 0.25)
        return content, confidence

    def _validate_section(self, section_id: str, content: str, required: bool) -> bool:
        """
        Basic completeness check: non-empty, minimum length, not a refusal.
        Returns True if section passes validation.
        """
        if not content or len(content.strip()) < 60:
            return not required  # Allow empty optional sections through
        refusal_phrases = [
            "i cannot", "i'm unable", "i don't have", "no data available",
            "cannot generate", "not enough information",
        ]
        lower = content.lower()
        if any(phrase in lower for phrase in refusal_phrases) and len(content) < 200:
            logger.warning("ReportAgent: section %r appears to be a refusal", section_id)
            return not required
        return True

    def _assemble_report(
        self,
        section_title: str,
        report_type: str,
        sections: List[Dict[str, Any]],
    ) -> str:
        """
        Assemble per-section content into a single full markdown document.
        """
        lines: List[str] = [
            f"# {section_title}",
            f"**Generated:** {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}",
            f"**Report Type:** {report_type.replace('_', ' ').title()}",
            "",
        ]
        for sec in sorted(sections, key=lambda s: s["order"]):
            title   = sec["title"]
            content = sec["content"]
            status  = sec["status"]
            conf    = sec["confidence_score"]

            lines.append(f"## {title}")
            if status == "incomplete":
                lines.append("*[Section incomplete — insufficient data available for this period.]*")
            elif content:
                lines.append(content)
            lines.append(f"*Section confidence: {conf:.0%}*")
            lines.append("")

        lines += [
            "---",
            f"*Report generated by ACE — Placeware Nigeria AI Executive Intelligence*",
        ]
        return "\n".join(lines)

    # ── Legacy single-pass report generation (kept as fallback) ──────────────

    def _generate_report(
        self,
        intent_text: str,
        report_type: str,
        section_title: str,
        rag_context: List[Tuple],
        past_reports: List[Dict],
        live_data: Any,
        memories: List[str],
    ) -> Tuple[str, Dict]:
        """Generate a structured report using the full context stack."""
        import json as _json
        from src.constants import BOT_NAME, BOT_BRAND

        rag_block = ""
        if rag_context:
            hits = "\n\n".join(
                f"Document: {r[0]}\n{r[1]}" for r in rag_context if r[1]
            )
            rag_block = f"\n--- Regulatory/SOP Context ---\n{hits}\n"

        past_block = ""
        if past_reports:
            past_lines = []
            for i, p in enumerate(past_reports):
                score = p.get("quality_score", 0)
                summary = p.get("summary", "")[:400]
                dt = str(p.get("created_at", ""))[:10]
                past_lines.append(f"Report {i+1} (score {score}/10, {dt}):\n  {summary}")
            past_block = f"\n--- Previous {report_type.title()} Reports (improve on these) ---\n" + "\n".join(past_lines) + "\n"

        live_block = ""
        if live_data:
            try:
                live_str = _json.dumps(live_data, default=str, indent=2)
                # Truncate to avoid token overflow
                if len(live_str) > 6000:
                    live_str = live_str[:6000] + "\n... [truncated]"
                live_block = f"\n--- Live Database Data ---\n{live_str}\n"
            except Exception:
                live_block = f"\n--- Live Data (raw) ---\n{str(live_data)[:2000]}\n"

        memory_block = ""
        if memories:
            memory_block = "\n--- Historical Intelligence ---\n" + "\n".join(f"• {m}" for m in memories) + "\n"

        improvement_note = ""
        if past_reports:
            improvement_note = (
                "\nIMPORTANT: The previous reports are shown above. "
                "Your report MUST be more specific, contain more data-backed findings, "
                "and provide sharper recommendations than those previous reports. "
                "This is how the system demonstrates continuous improvement."
            )

        prompt = f"""You are {BOT_NAME}, the AI executive intelligence system for {BOT_BRAND} (pharmaceutical distribution).
Generate a professional {section_title}.
{rag_block}
{past_block}
{live_block}
{memory_block}

Request: {intent_text}
Report Type: {report_type}
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
{improvement_note}

Structure the report EXACTLY as follows:

# {section_title}
**Generated:** {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}

## Executive Summary
[2-3 sentences: current state, key concern, overall health]

## Key Findings
[Numbered list — use specific numbers/dates/records from the live data. Minimum 4 findings.]

## Risk Analysis
[Numbered list of risks with severity (High/Medium/Low) and business impact]

## Recommendations
[Numbered list — specific, actionable, time-bound. Minimum 3.]

## Data Coverage
Tables queried: [list] | RAG documents referenced: {len(rag_context)} | Previous reports reviewed: {len(past_reports)}

---
*Report generated by {BOT_NAME} — {BOT_BRAND} AI Executive Intelligence*
"""

        full_report = ""
        try:
            from src.deepseek import DeepSeek
            llm = DeepSeek(os.getenv("DEEPSEEK_API_KEY", ""))
            full_report = llm.generate_response(
                context="",
                question=prompt,
                instruction=(
                    f"You are {BOT_NAME}, a senior business analyst AI. "
                    "Generate a thorough, data-backed report. Use specific numbers from the live data. "
                    "Never make up data not present in the context. "
                    "Be more specific and insightful than the previous reports shown."
                ),
            )
        except Exception as exc:
            logger.error(f"ReportAgent: LLM generation failed: {exc}")
            full_report = f"# {section_title}\n\nReport generation encountered an error: {exc}"

        # Extract structured data from the report text
        structured = self._extract_structured(full_report)
        return full_report, structured

    def _extract_structured(self, report_text: str) -> Dict[str, Any]:
        """Extract findings/recommendations as lists from the rendered report."""
        findings: List[str] = []
        recommendations: List[str] = []
        summary = ""

        lines = report_text.split("\n")
        section = None
        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()
            if "## executive summary" in lower:
                section = "summary"
            elif "## key findings" in lower:
                section = "findings"
            elif "## recommendations" in lower:
                section = "recommendations"
            elif stripped.startswith("## "):
                section = "other"
            elif section == "summary" and stripped and not stripped.startswith("#"):
                summary += stripped + " "
            elif section == "findings" and re.match(r"^\d+\.", stripped):
                findings.append(stripped)
            elif section == "recommendations" and re.match(r"^\d+\.", stripped):
                recommendations.append(stripped)

        return {
            "summary": summary.strip()[:600],
            "findings": findings,
            "recommendations": recommendations,
        }

    # ── Self-scoring ──────────────────────────────────────────────────────────

    def _self_score(self, report_text: str, report_type: str) -> float:
        """Ask the LLM to score the report quality 1-10. Returns float."""
        try:
            from src.deepseek import DeepSeek
            llm = DeepSeek(os.getenv("DEEPSEEK_API_KEY", ""))
            score_prompt = (
                f"Rate the following {report_type} business report on a scale of 1-10.\n"
                "Criteria: specificity, use of data, actionability of recommendations, clarity.\n"
                "Respond with ONLY a number (e.g. 8.5).\n\n"
                f"Report excerpt:\n{report_text[:1500]}"
            )
            raw = llm.generate_response(
                context="",
                question=score_prompt,
                instruction="You are a report quality evaluator. Respond with ONLY a number from 1 to 10.",
            ).strip()
            # Extract first number found
            match = re.search(r"(\d+(?:\.\d+)?)", raw)
            if match:
                score = float(match.group(1))
                return min(max(score, 0.0), 10.0)
        except Exception as exc:
            logger.warning(f"ReportAgent: self-scoring failed: {exc}")
        return 7.0  # Safe default

    # ── Persistence ───────────────────────────────────────────────────────────

    def _store_report(
        self,
        report_type: str,
        intent_text: str,
        full_report: str,
        summary: str,
        findings: List[str],
        recommendations: List[str],
        quality_score: float,
        section_data: Optional[List[Dict]] = None,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """Persist report to placeware_report_memory. Returns the inserted row id."""
        import json as _json
        try:
            from src.db import db
            payload: Dict[str, Any] = {
                "report_type":     report_type,
                "intent_text":     intent_text,
                "full_report":     full_report[:10000],
                "summary":         summary,
                "findings":        _json.dumps(findings),
                "recommendations": _json.dumps(recommendations),
                "quality_score":   quality_score,
                "template_version": TEMPLATE_VERSION,
                "approval_status": "complete",
            }
            if section_data is not None:
                payload["section_data"] = _json.dumps(section_data)
            if session_id:
                payload["session_id"] = session_id

            res = db.table("placeware_report_memory").insert(payload).execute()
            if res.data:
                return str(res.data[0].get("id"))
        except Exception as exc:
            logger.warning("ReportAgent: store_report failed: %s", exc)
        return None
