"""DeviationCAPAAgent — monitors deviation reports and CAPA action progress.

Responsibilities:
  - Identify open / overdue deviations and CAPA actions
  - Classify risk by deviation classification (minor / major / critical)
  - Detect stale investigations (open > 14 days with no activity)
  - Recommend escalation for critical or long-running deviations
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)


def _days_open(row: Dict) -> int:
    """Days since investigation_start_date (or creation date)."""
    raw = row.get("investigation_start_date") or row.get("created_at") or ""
    try:
        d = date.fromisoformat(str(raw)[:10])
        return (date.today() - d).days
    except (ValueError, TypeError):
        return 0


@register_agent
class DeviationCAPAAgent(BaseAgent):
    name = "deviation_capa"
    required_role = "quality_assurance"

    def collect_data(self) -> Dict[str, Any]:
        """Fetch deviation_reports from Supabase.

        Context keys consumed:
          - db (supabase client)
          - include_closed (bool, default False)
        """
        db             = self.context.get("db")
        include_closed = bool(self.context.get("include_closed", False))

        if db is None:
            logger.warning("DeviationCAPAAgent: no db client in context")
            return {"rows": [], "error": "no_db"}

        try:
            query = db.table("deviation_reports").select("*")
            if not include_closed:
                query = query.neq("status", "closed")
            res = query.order("created_at", desc=True).execute()
            return {"rows": res.data or []}
        except Exception as exc:
            logger.exception("DeviationCAPAAgent: DB fetch failed")
            return {"rows": [], "error": str(exc)}

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[Dict] = data.get("rows", [])

        open_devs:     List[Dict] = []
        investigating: List[Dict] = []
        escalated:     List[Dict] = []
        critical:      List[Dict] = []
        major:         List[Dict] = []
        stale:         List[Dict] = []     # open > 14 days
        capa_overdue:  List[Dict] = []     # individual overdue CAPA actions

        for r in rows:
            status     = (r.get("status") or "open").lower()
            cls_       = (r.get("classification") or "minor").lower()
            days       = _days_open(r)

            if status == "open":
                open_devs.append(r)
                if days > 14:
                    stale.append(r)
            elif status == "under_investigation":
                investigating.append(r)
                if days > 30:
                    stale.append(r)
            elif status == "escalated":
                escalated.append(r)

            if cls_ == "critical":
                critical.append(r)
            elif cls_ == "major":
                major.append(r)

            # Check CAPA action due dates
            for action in (r.get("capa_actions") or []):
                if isinstance(action, dict):
                    a_due = action.get("due_date")
                    a_st  = (action.get("status") or "open").lower()
                    if a_due and a_st not in ("closed", "complete", "completed"):
                        try:
                            due_d = date.fromisoformat(str(a_due)[:10])
                            if due_d < date.today():
                                capa_overdue.append({**r, "_capa_action": action})
                        except (ValueError, TypeError):
                            pass

        return {
            "open_deviations":  open_devs,
            "investigating":    investigating,
            "escalated":        escalated,
            "critical":         critical,
            "major":            major,
            "stale":            stale,
            "capa_overdue":     capa_overdue,
            "error":            data.get("error"),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        critical   = analysis["critical"]
        major      = analysis["major"]
        stale      = analysis["stale"]
        capa_od    = analysis["capa_overdue"]
        escalated  = analysis["escalated"]

        insight.metrics.update({
            "open_deviations":    len(analysis["open_deviations"]),
            "under_investigation": len(analysis["investigating"]),
            "escalated":          len(escalated),
            "critical_count":     len(critical),
            "major_count":        len(major),
            "stale_investigations": len(stale),
            "capa_actions_overdue": len(capa_od),
        })

        if critical:
            insight.risks.append(
                f"{len(critical)} CRITICAL deviation(s) require immediate QA Director attention."
            )
            insight.recommendations.append(
                "Critical deviations must be investigated within 24 hours per SOP-DEV-001."
            )
            insight.supporting_refs.extend(critical[:5])

        if major:
            insight.findings.append(
                f"{len(major)} MAJOR deviation(s) are open — investigation deadline: 5 days."
            )
            insight.recommendations.append(
                "Assign investigation leads for all major deviations and set CAPA milestones."
            )

        if stale:
            insight.risks.append(
                f"{len(stale)} deviation investigation(s) have been open for more than 14 days "
                f"with no closure — potential SOP breach."
            )
            insight.recommendations.append(
                "Review stale investigations and update status or escalate."
            )
            insight.supporting_refs.extend(stale[:5])

        if capa_od:
            insight.findings.append(
                f"{len(capa_od)} CAPA action(s) are past their due date."
            )
            insight.recommendations.append(
                "Review overdue CAPA actions and update owners with revised deadlines."
            )

        if escalated:
            insight.risks.append(
                f"{len(escalated)} deviation(s) have been escalated to management."
            )

        insight.confidence_score = 0.92 if not analysis.get("error") else 0.5
        insight.execution_metadata["data_source"] = "deviation_reports"
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        if cache:
            cache.set(self.name, insight, ttl=self.context.get("cache_ttl_seconds", 180))

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "open_deviations":    "int",
            "critical_count":     "int",
            "capa_overdue":       "int",
            "stale_investigations": "int",
        }
