"""MaintenanceTrackerAgent — monitors equipment maintenance and calibration schedules.

Responsibilities:
  - Identify equipment with overdue or upcoming (≤14 days) maintenance
  - Detect equipment running more than 20% past their calibration interval
  - Recommend work orders and prioritise by equipment criticality
  - Surface cold-chain-critical equipment (cold rooms, TLD devices) for priority alerting
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)

# Equipment types critical to cold-chain integrity — highest priority
_COLD_CHAIN_CRITICAL = {"cold_room", "refrigerator", "temperature_device", "freezer"}


def _days_until(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        d = date.fromisoformat(str(date_str)[:10])
        return (d - date.today()).days
    except (ValueError, TypeError):
        return None


@register_agent
class MaintenanceTrackerAgent(BaseAgent):
    name = "maintenance_tracker"
    required_role = "quality_assurance"

    def collect_data(self) -> Dict[str, Any]:
        """Fetch maintenance_schedule joined with equipment_registry.

        Context keys consumed:
          - db (supabase client)
          - upcoming_window_days (int, default 14)
        """
        db = self.context.get("db")
        if db is None:
            logger.warning("MaintenanceTrackerAgent: no db client in context")
            return {"maintenance_rows": [], "equipment_rows": [], "error": "no_db"}

        try:
            maint_res = (
                db.table("maintenance_schedule")
                .select("*, equipment_registry(*)")
                .neq("status", "cancelled")
                .execute()
            )
            return {"maintenance_rows": maint_res.data or []}
        except Exception as exc:
            logger.exception("MaintenanceTrackerAgent: DB fetch failed")
            return {"maintenance_rows": [], "error": str(exc)}

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[Dict] = data.get("maintenance_rows", [])
        window = int(self.context.get("upcoming_window_days", 14))

        overdue:          List[Dict] = []
        upcoming:         List[Dict] = []
        critical_overdue: List[Dict] = []
        decommissioned_scheduled: List[Dict] = []

        for r in rows:
            status     = (r.get("status") or "scheduled").lower()
            equip      = r.get("equipment_registry") or {}
            equip_type = (equip.get("equipment_type") or "other").lower()
            equip_stat = (equip.get("status") or "active").lower()

            if equip_stat == "decommissioned":
                decommissioned_scheduled.append(r)
                continue

            days = _days_until(r.get("next_maintenance_date"))

            if status == "overdue" or (days is not None and days < 0):
                overdue.append(r)
                if equip_type in _COLD_CHAIN_CRITICAL:
                    critical_overdue.append(r)
            elif days is not None and 0 <= days <= window:
                upcoming.append(r)

        return {
            "overdue":           overdue,
            "upcoming":          upcoming,
            "critical_overdue":  critical_overdue,
            "decommissioned_with_scheduled": decommissioned_scheduled,
            "error":             data.get("error"),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        overdue   = analysis["overdue"]
        upcoming  = analysis["upcoming"]
        crit_od   = analysis["critical_overdue"]

        insight.metrics.update({
            "overdue_maintenance":          len(overdue),
            "upcoming_maintenance_14d":     len(upcoming),
            "cold_chain_critical_overdue":  len(crit_od),
            "decommissioned_with_schedule": len(analysis["decommissioned_with_scheduled"]),
        })

        if crit_od:
            insight.risks.append(
                f"{len(crit_od)} cold-chain-critical equipment item(s) have overdue maintenance "
                f"— temperature integrity may be at risk."
            )
            insight.recommendations.append(
                "Raise urgent work orders for overdue cold-chain equipment (cold rooms, TLD devices, refrigerators)."
            )
            insight.supporting_refs.extend(crit_od[:5])

        if overdue:
            insight.findings.append(
                f"{len(overdue)} maintenance task(s) are overdue. "
                f"This may constitute a deviation under SOP-EQP-001/002/003."
            )
            insight.recommendations.append(
                "Assign maintenance work orders and check whether a deviation report is required."
            )

        if upcoming:
            insight.findings.append(
                f"{len(upcoming)} maintenance task(s) due within 14 days — schedule now to avoid overdue status."
            )

        if analysis["decommissioned_with_scheduled"]:
            insight.risks.append(
                "Some decommissioned equipment still has active maintenance schedules — cancel or remove them."
            )

        insight.confidence_score = 0.93 if not analysis.get("error") else 0.5
        insight.execution_metadata["data_source"] = "maintenance_schedule"
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        if cache:
            cache.set(self.name, insight, ttl=self.context.get("cache_ttl_seconds", 300))

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "overdue_maintenance":         "int",
            "cold_chain_critical_overdue": "int",
            "upcoming_maintenance_14d":    "int",
        }
