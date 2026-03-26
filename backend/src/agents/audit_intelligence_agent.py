"""AuditIntelligenceAgent — analyses audit schedules and generates actionable insights.

Responsibilities:
  - Count overdue, in-progress, and upcoming audits (30-day horizon)
  - Detect patterns in repeated failures or skipped audits by department
  - Recommend risk escalation for high/critical-risk overdue audits
  - Optionally surface the audit schedule overview for EOS summary responses
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)


@register_agent
class AuditIntelligenceAgent(BaseAgent):
    name = "audit_intelligence"
    required_role = "quality_assurance"

    def collect_data(self) -> Dict[str, Any]:
        """Fetch audit schedule rows from Supabase.

        Context keys consumed:
          - db (supabase client)
          - year (int, optional — defaults to current year)
        """
        db   = self.context.get("db")
        year = self.context.get("year", date.today().year)

        if db is None:
            logger.warning("AuditIntelligenceAgent: no db client in context")
            return {"rows": [], "error": "no_db"}

        try:
            res = (
                db.table("audit_schedule")
                .select("*")
                .eq("year", year)
                .execute()
            )
            return {"rows": res.data or [], "year": year}
        except Exception as exc:
            logger.exception("AuditIntelligenceAgent: DB fetch failed")
            return {"rows": [], "error": str(exc)}

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[Dict] = data.get("rows", [])
        today = date.today()
        horizon = today + timedelta(days=30)

        overdue:   List[Dict] = []
        upcoming:  List[Dict] = []
        completed: List[Dict] = []
        skipped:   List[Dict] = []
        in_prog:   List[Dict] = []

        high_risk_overdue: List[Dict] = []
        dept_miss: Dict[str, int] = {}

        for r in rows:
            status = (r.get("status") or "scheduled").lower()
            risk   = (r.get("risk_level") or "medium").lower()
            dept   = r.get("department") or "Unknown"
            month  = r.get("month_due")
            year   = r.get("year", today.year)

            if status == "overdue":
                overdue.append(r)
                if risk in ("high", "critical"):
                    high_risk_overdue.append(r)
                dept_miss[dept] = dept_miss.get(dept, 0) + 1
            elif status == "in_progress":
                in_prog.append(r)
            elif status == "completed":
                completed.append(r)
            elif status == "skipped":
                skipped.append(r)
                dept_miss[dept] = dept_miss.get(dept, 0) + 1
            else:  # scheduled
                if month and year:
                    try:
                        due = date(int(year), int(month), 28)  # safe end-of-month proxy
                        if today <= due <= horizon:
                            upcoming.append(r)
                    except ValueError:
                        pass

        total = len(rows)
        compliance_pct = round(len(completed) / total * 100, 1) if total else 0.0

        return {
            "total_audits": total,
            "overdue":         overdue,
            "upcoming":        upcoming,
            "in_progress":     in_prog,
            "completed":       completed,
            "skipped":         skipped,
            "high_risk_overdue": high_risk_overdue,
            "dept_miss_count": dept_miss,
            "compliance_pct":  compliance_pct,
            "error":           data.get("error"),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        overdue   = analysis["overdue"]
        upcoming  = analysis["upcoming"]
        hr_over   = analysis["high_risk_overdue"]
        dept_miss = analysis["dept_miss_count"]
        comp_pct  = analysis["compliance_pct"]

        insight.metrics.update({
            "total_audits":          analysis["total_audits"],
            "overdue_count":         len(overdue),
            "in_progress_count":     len(analysis["in_progress"]),
            "completed_count":       len(analysis["completed"]),
            "upcoming_30d_count":    len(upcoming),
            "high_risk_overdue":     len(hr_over),
            "compliance_completion": comp_pct,
        })

        if hr_over:
            insight.risks.append(
                f"{len(hr_over)} HIGH/CRITICAL risk audit(s) are overdue — "
                f"immediate escalation required."
            )
            insight.recommendations.append(
                "Escalate overdue high-risk audits to QA Management within 24 hours."
            )
            insight.supporting_refs.extend(hr_over[:5])

        if overdue:
            insight.findings.append(
                f"{len(overdue)} audit(s) are overdue across "
                f"{len(set(r.get('department','?') for r in overdue))} departments."
            )
            insight.recommendations.append(
                "Schedule make-up audit sessions for overdue items and update records."
            )

        for dept, count in sorted(dept_miss.items(), key=lambda x: -x[1])[:3]:
            insight.findings.append(
                f"Department '{dept}' has {count} overdue/skipped audit(s)."
            )

        if upcoming:
            insight.findings.append(
                f"{len(upcoming)} audit(s) due within the next 30 days."
            )

        if comp_pct < 70:
            insight.risks.append(
                f"Audit completion rate is {comp_pct}% — below the 70% minimum threshold."
            )

        insight.confidence_score = 0.9 if not analysis.get("error") else 0.5
        insight.execution_metadata["data_source"] = "audit_schedule"
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        if cache:
            cache.set(self.name, insight, ttl=self.context.get("cache_ttl_seconds", 300))

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "total_audits":       "int",
            "overdue_count":      "int",
            "compliance_pct":     "float",
            "high_risk_overdue":  "list[dict]",
            "upcoming_30d_count": "int",
        }
