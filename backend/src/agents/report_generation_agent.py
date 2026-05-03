"""
ReportGenerationAgent — RAG-powered progressive report generation for EOS.
==========================================================================
Responsibilities:
  • Detect report type from natural language request
    (deviation | maintenance | compliance | audit | financial | inventory | executive)
  • Retrieve RAG context: SOPs + NAFDAC docs from main match_documents index
  • Pull past reports from placeware_report_memory as improvement baselines
  • Query live Supabase data relevant to the report type
  • Generate a structured report via LLM that is provably better than the
    last report on the same topic (enforced via explicit "improve-on" prompt)
  • Self-score the report (1-10); store in memory only if score >= 7
  • Return report as Insight.findings (rendered text) + metrics (structured data)

Context keys consumed:
    intent_text   str  — user request e.g. "generate a deviation report"
    report_type   str  — optional override; if absent, auto-detected
    actor_id      str  — for audit log
    simulation    bool — if True, skip Supabase memory write
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)

# ── Report type registry ───────────────────────────────────────────────────────
# Maps report_type → table(s) to query + relevant fields
_REPORT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "deviation": {
        "keywords": ["deviation", "capa", "non-conformance", "nonconformance", "corrective action"],
        "tables": [
            {"table": "placeware_deviation_reports", "select": "*", "order": "created_at", "limit": 50},
        ],
        "section_title": "Deviation & CAPA Report",
    },
    "maintenance": {
        "keywords": ["maintenance", "calibration", "equipment", "service schedule", "overdue maintenance"],
        "tables": [
            {"table": "placeware_equipment_registry", "select": "*", "order": "next_maintenance_date", "limit": 50},
        ],
        "section_title": "Equipment Maintenance & Calibration Report",
    },
    "compliance": {
        "keywords": ["compliance", "sop", "nafdac", "qms", "regulatory", "standard operating"],
        "tables": [
            {"table": "placeware_compliance_activities", "select": "*", "order": "due_date", "limit": 50},
        ],
        "section_title": "Regulatory Compliance Report",
    },
    "audit": {
        "keywords": ["audit schedule", "overdue audit", "upcoming audit", "audit calendar", "audit review"],
        "tables": [
            {"table": "audit_schedule", "select": "*", "limit": 50},
        ],
        "section_title": "Audit Intelligence Report",
    },
    "financial": {
        "keywords": ["financial performance", "cashflow", "cash flow", "financial overview", "financial summary"],
        "tables": [
            {"table": "sage_gl_journal_entries", "select": "*", "order": "transaction_date", "limit": 100},
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 100},
        ],
        "section_title": "Financial Performance Report",
    },
    "inventory": {
        "keywords": ["inventory", "stock", "expiry", "stock level", "low stock", "expiring"],
        "tables": [
            {"table": "placeware_inventory_snapshot", "select": "*", "limit": 100},
        ],
        "section_title": "Inventory Status Report",
    },
    "executive": {
        "keywords": ["executive summary", "board report", "leadership brief", "business health", "kpi overview"],
        "tables": [
            {"table": "crm_sales_pipeline", "select": "*", "order": "created_at", "limit": 50},
            {"table": "placeware_inventory_snapshot", "select": "*", "limit": 50},
            {"table": "placeware_compliance_activities", "select": "*", "order": "due_date", "limit": 30},
            {"table": "sage_payroll_snapshot", "select": "*", "order": "pay_period", "limit": 20},
        ],
        "section_title": "Executive Business Health Report",
        "is_executive": True,
    },
    "sales": {
        "keywords": [
            "sales report", "weekly sales", "pipeline report", "crm report", "lead report",
            "sales performance", "revenue report", "sales summary", "sales activity",
        ],
        "tables": [
            {"table": "crm_sales_pipeline", "select": "*", "order": "created_at", "limit": 100},
            {"table": "crm_lead_activity_log", "select": "*", "order": "created_at", "limit": 50},
        ],
        "section_title": "Sales & Pipeline Performance Report",
    },
    "payroll": {
        "keywords": [
            "payroll", "salary", "hr report", "compensation", "payroll report",
            "staff payroll", "payroll summary", "wages", "staff salary",
        ],
        "tables": [
            {"table": "sage_payroll_snapshot", "select": "*", "order": "pay_period", "limit": 50},
            {"table": "sage_hr_absences", "select": "*", "order": "absence_date", "limit": 50},
        ],
        "section_title": "Payroll & HR Summary Report",
    },
    "pl": {
        "keywords": [
            "p&l", "profit and loss", "income statement", "pl report", "profit loss",
            "net income", "profit & loss", "loss statement",
        ],
        "tables": [
            {"table": "sage_gl_journal_entries", "select": "*", "order": "transaction_date", "limit": 100},
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 100},
        ],
        "section_title": "Profit & Loss Report",
    },
    "ar_aging": {
        "keywords": [
            "ar aging", "accounts receivable", "outstanding invoices", "aging report",
            "overdue payments", "receivables", "ar report", "accounts receivable aging",
        ],
        "tables": [
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 100},
            {"table": "sage_customers", "select": "*", "limit": 50},
        ],
        "section_title": "Accounts Receivable Aging Report",
    },
    "frontdesk": {
        "keywords": [
            "frontdesk report", "daily report", "reception report", "walk-in summary",
            "daily operations", "frontdesk summary", "daily frontdesk", "front desk report",
        ],
        "tables": [
            {"table": "placeware_walk_ins", "select": "*", "order": "created_at", "limit": 100},
            {"table": "placeware_invoices", "select": "*", "order": "created_at", "limit": 50},
        ],
        "section_title": "Frontdesk & Daily Operations Report",
    },
}

# Default if nothing matches
_DEFAULT_REPORT_TYPE = "executive"


@register_agent
class ReportGenerationAgent(BaseAgent):
    """
    EOS-callable agent for generating progressively-improving business reports.
    Each run is better than the previous one on the same topic.
    """

    name = "report_generation_agent"
    required_role = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        """Detect report type, retrieve RAG context, past reports, and live data."""
        intent_text = self.context.get("intent_text", "")
        report_type = self.context.get("report_type") or self._detect_report_type(intent_text)

        rag_context  = self._retrieve_rag(intent_text)
        past_reports = self._get_past_reports(report_type, limit=3)
        live_data    = self._fetch_live_data(report_type)
        memories     = self._get_memories(intent_text)

        return {
            "intent_text":  intent_text,
            "report_type":  report_type,
            "rag_context":  rag_context,
            "past_reports": past_reports,
            "live_data":    live_data,
            "memories":     memories,
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate the report via LLM using all collected context."""
        report_type  = data["report_type"]
        intent_text  = data["intent_text"]
        rag_context  = data["rag_context"]
        past_reports = data["past_reports"]
        live_data    = data["live_data"]
        memories     = data["memories"]

        report_cfg   = _REPORT_REGISTRY.get(report_type, _REPORT_REGISTRY[_DEFAULT_REPORT_TYPE])
        section_title = report_cfg["section_title"]

        full_report, structured = self._generate_report(
            intent_text=intent_text,
            report_type=report_type,
            section_title=section_title,
            rag_context=rag_context,
            past_reports=past_reports,
            live_data=live_data,
            memories=memories,
        )

        quality_score = self._self_score(full_report, report_type)

        return {
            "report_type":    report_type,
            "section_title":  section_title,
            "full_report":    full_report,
            "structured":     structured,
            "quality_score":  quality_score,
            "live_data_rows": len(live_data) if isinstance(live_data, list) else 0,
            "rag_hits":       len(rag_context),
            "past_count":     len(past_reports),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        """Package the report as an Insight and persist to report memory."""
        report_type   = analysis["report_type"]
        full_report   = analysis["full_report"]
        structured    = analysis.get("structured", {})
        quality_score = analysis.get("quality_score", 0.0)
        simulation    = bool(self.context.get("simulation", False))

        # ── Persist to report memory if quality ≥ 7 ─────────────────────────
        if not simulation and quality_score >= 7.0:
            self._store_report(
                report_type=report_type,
                intent_text=self.context.get("intent_text", ""),
                full_report=full_report,
                summary=structured.get("summary", full_report[:500]),
                findings=structured.get("findings", []),
                recommendations=structured.get("recommendations", []),
                quality_score=quality_score,
            )
            # Also store a memory so agents can recall this pattern
            from src.services.agent_memory import AgentMemory
            AgentMemory(self.name).store(
                findings=[structured.get("summary", full_report[:400])],
                confidence=min(quality_score / 10.0, 1.0),
                memory_type="finding",
            )

        findings = [full_report] if full_report else ["Report generation completed but produced no content."]

        return Insight(
            findings=findings,
            recommendations=structured.get("recommendations", []),
            confidence_score=min(quality_score / 10.0, 1.0),
            metrics={
                "report_type":   report_type,
                "quality_score": quality_score,
                "rag_hits":      analysis.get("rag_hits", 0),
                "data_rows":     analysis.get("live_data_rows", 0),
                "past_reports_used": analysis.get("past_count", 0),
                "section_title": analysis["section_title"],
                "full_report":   full_report,
            },
        )

    def write_cache(self, insight: Insight) -> None:
        pass  # Persisted inside generate_insights

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "findings": "list[str] — full report text",
            "metrics": {
                "report_type": "str",
                "quality_score": "float",
                "rag_hits": "int",
            },
        }

    # ── Detection ──────────────────────────────────────────────────────────────

    def _detect_report_type(self, text: str) -> str:
        text_lower = text.lower()
        for rtype, cfg in _REPORT_REGISTRY.items():
            if any(kw in text_lower for kw in cfg.get("keywords", [])):
                return rtype
        return _DEFAULT_REPORT_TYPE

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

    # ── Live data ─────────────────────────────────────────────────────────────

    def _fetch_live_data(self, report_type: str) -> Any:
        cfg = _REPORT_REGISTRY.get(report_type, {})

        # Special case: delegate financial data to FinancialAnalystAgent
        if cfg.get("delegate_to") == "financial_analyst":
            return self._delegate_to_agent("financial_analyst")

        # Special case: executive report pulls from tool registry
        if cfg.get("is_executive"):
            return self._pull_executive_data()

        rows: List[Dict] = []
        try:
            from src.db import db
            for tbl_cfg in cfg.get("tables", []):
                tbl = tbl_cfg.get("table")
                sel = tbl_cfg.get("select", "*")
                lim = tbl_cfg.get("limit", 50)
                order = tbl_cfg.get("order")
                try:
                    q = db.table(tbl).select(sel).limit(lim)
                    if order:
                        q = q.order(order, desc=True)
                    res = q.execute()
                    rows.extend(res.data or [])
                except Exception as exc:
                    logger.warning(f"ReportAgent: table {tbl!r} fetch failed: {exc}")
        except Exception as exc:
            logger.warning(f"ReportAgent: live data fetch failed: {exc}")

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

    # ── LLM report generation ─────────────────────────────────────────────────

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
    ) -> None:
        import json as _json
        try:
            from src.db import db
            db.table("placeware_report_memory").insert({
                "report_type":     report_type,
                "intent_text":     intent_text,
                "full_report":     full_report[:10000],
                "summary":         summary,
                "findings":        _json.dumps(findings),
                "recommendations": _json.dumps(recommendations),
                "quality_score":   quality_score,
            }).execute()
        except Exception as exc:
            logger.warning(f"ReportAgent: store_report failed: {exc}")
