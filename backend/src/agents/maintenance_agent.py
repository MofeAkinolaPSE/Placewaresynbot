from __future__ import annotations

from typing import Any, Dict

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight
from src.services.maintenance_service import maintenance_snapshot


@register_agent
class MaintenanceTrackingAgent(BaseAgent):
    name = "maintenance_tracking"
    required_role = "ops"

    def collect_data(self) -> Dict[str, Any]:
        return maintenance_snapshot()

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        counts = data.get("counts") or {}
        open_incidents = int(counts.get("open_incidents") or 0)
        overdue_tasks = int(counts.get("overdue_tasks") or 0)

        health_state = "healthy"
        if open_incidents > 0 or overdue_tasks > 0:
            health_state = "attention"
        if open_incidents > 5 or overdue_tasks > 10:
            health_state = "at_risk"

        return {
            "open_incidents": data.get("open_incidents") or [],
            "overdue_tasks": data.get("overdue_tasks") or [],
            "counts": counts,
            "highest_severity": data.get("highest_severity") or "low",
            "health_state": health_state,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()

        counts = analysis.get("counts") or {}
        open_incidents = int(counts.get("open_incidents") or 0)
        overdue_tasks = int(counts.get("overdue_tasks") or 0)
        highest_severity = analysis.get("highest_severity") or "low"
        health_state = analysis.get("health_state") or "healthy"

        insight.metrics.update(
            {
                "open_incidents": open_incidents,
                "overdue_tasks": overdue_tasks,
                "highest_severity": highest_severity,
                "health_state": health_state,
            }
        )

        if open_incidents == 0 and overdue_tasks == 0:
            insight.findings.append("Maintenance reliability checks are healthy.")
        else:
            insight.findings.append(
                f"Maintenance monitor found {open_incidents} open incident(s) and {overdue_tasks} overdue task(s)."
            )

        if highest_severity in {"critical", "high"}:
            insight.risks.append(
                f"Highest open incident severity is {highest_severity}; service continuity is at risk."
            )

        if open_incidents > 0:
            insight.recommendations.append("Run the maintenance playbook for open incidents and verify dashboard recovery.")
        if overdue_tasks > 0:
            insight.recommendations.append("Assign and close overdue maintenance tasks to prevent recurring failures.")

        refs = []
        refs.extend((analysis.get("open_incidents") or [])[:20])
        refs.extend((analysis.get("overdue_tasks") or [])[:20])
        insight.supporting_refs = refs

        if health_state == "healthy":
            insight.confidence_score = 0.9
        elif health_state == "attention":
            insight.confidence_score = 0.85
        else:
            insight.confidence_score = 0.8

        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 180))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "open_incidents": "int",
            "overdue_tasks": "int",
            "highest_severity": "str",
            "health_state": "str",
            "findings": "list",
            "risks": "list",
            "recommendations": "list",
        }
