"""RecallManagerAgent — monitors active recalls and validates distribution trace completeness.

Responsibilities:
  - Identify active/in-progress recalls and flag stalled ones
  - Validate distribution_data completeness (no customer without recovery status)
  - Calculate recall effectiveness: recovered_qty / dispatched_qty
  - Recommend escalation to NAFDAC for overdue mandatory recalls
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)


def _days_since(date_str: Optional[str]) -> int:
    if not date_str:
        return 0
    try:
        d = date.fromisoformat(str(date_str)[:10])
        return (date.today() - d).days
    except (ValueError, TypeError):
        return 0


@register_agent
class RecallManagerAgent(BaseAgent):
    name = "recall_manager"
    required_role = "quality_assurance"

    def collect_data(self) -> Dict[str, Any]:
        """Fetch recall_cases from Supabase.

        Context keys consumed:
          - db (supabase client)
          - include_closed (bool, default False)
        """
        db             = self.context.get("db")
        include_closed = bool(self.context.get("include_closed", False))

        if db is None:
            logger.warning("RecallManagerAgent: no db client in context")
            return {"rows": [], "error": "no_db"}

        try:
            query = db.table("recall_cases").select("*")
            if not include_closed:
                query = query.neq("status", "closed")
            res = query.order("initiation_date", desc=True).execute()
            return {"rows": res.data or []}
        except Exception as exc:
            logger.exception("RecallManagerAgent: DB fetch failed")
            return {"rows": [], "error": str(exc)}

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[Dict] = data.get("rows", [])

        initiated:  List[Dict] = []
        in_progress: List[Dict] = []
        stalled:    List[Dict] = []       # > 7 days since initiation with no completion
        mandatory_overdue: List[Dict] = []  # mandatory scope > 48 h without closure
        effectiveness: List[Dict] = []

        for r in rows:
            status   = (r.get("status") or "initiated").lower()
            scope    = (r.get("scope") or "voluntary").lower()
            days     = _days_since(r.get("initiation_date"))
            dist     = r.get("distribution_data") or []

            if status == "initiated":
                initiated.append(r)
                if days > 3:
                    stalled.append(r)
                if scope == "mandatory" and days > 2:
                    mandatory_overdue.append(r)
            elif status == "in_progress":
                in_progress.append(r)
                if days > 7:
                    stalled.append(r)

            # Effectiveness calculation
            total_dispatched = sum(
                int(x.get("qty") or 0) for x in dist if isinstance(x, dict)
            )
            total_recovered = sum(
                int(x.get("recovered_qty") or 0) for x in dist
                if isinstance(x, dict) and x.get("recovered_qty") is not None
            )
            pending_customers = [
                x for x in dist
                if isinstance(x, dict) and (x.get("status") or "pending").lower() == "pending"
            ]

            effectiveness.append({
                "recall_id":           r.get("recall_id"),
                "product_name":        r.get("product_name"),
                "total_dispatched":    total_dispatched,
                "total_recovered":     total_recovered,
                "effectiveness_pct":   round(total_recovered / total_dispatched * 100, 1)
                                       if total_dispatched else None,
                "pending_customers":   len(pending_customers),
            })

        return {
            "initiated":           initiated,
            "in_progress":         in_progress,
            "stalled":             stalled,
            "mandatory_overdue":   mandatory_overdue,
            "effectiveness":       effectiveness,
            "error":               data.get("error"),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        stalled   = analysis["stalled"]
        mand_od   = analysis["mandatory_overdue"]
        eff_list  = analysis["effectiveness"]
        in_prog   = analysis["in_progress"]
        initiated = analysis["initiated"]

        active = len(initiated) + len(in_prog)
        low_eff = [e for e in eff_list
                   if e.get("effectiveness_pct") is not None and e["effectiveness_pct"] < 80]

        insight.metrics.update({
            "active_recalls":            active,
            "initiated":                 len(initiated),
            "in_progress":               len(in_prog),
            "stalled":                   len(stalled),
            "mandatory_overdue":         len(mand_od),
            "low_effectiveness_recalls": len(low_eff),
        })

        if mand_od:
            insight.risks.append(
                f"{len(mand_od)} MANDATORY recall(s) have exceeded the 48-hour NAFDAC "
                f"reporting deadline — immediate regulatory notification required."
            )
            insight.recommendations.append(
                "Contact NAFDAC immediately and complete Form SR-001 within the hour."
            )
            insight.supporting_refs.extend(mand_od[:3])

        if stalled:
            insight.risks.append(
                f"{len(stalled)} recall(s) appear stalled with no progress update."
            )
            insight.recommendations.append(
                "Review stalled recalls and reassign or escalate to recall coordinator."
            )

        if low_eff:
            insight.findings.append(
                f"{len(low_eff)} recall(s) have a product recovery rate below 80% — "
                f"distribution trace may be incomplete."
            )
            insight.recommendations.append(
                "Cross-reference dispatch records in Sage 200 to identify uncontacted customers."
            )
            insight.supporting_refs.extend(low_eff[:3])

        if active:
            insight.findings.append(
                f"{active} active recall(s) currently under management."
            )

        insight.confidence_score = 0.91 if not analysis.get("error") else 0.5
        insight.execution_metadata["data_source"] = "recall_cases"
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        if cache:
            cache.set(self.name, insight, ttl=self.context.get("cache_ttl_seconds", 120))

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "active_recalls":            "int",
            "stalled":                   "int",
            "mandatory_overdue":         "int",
            "low_effectiveness_recalls": "int",
        }
