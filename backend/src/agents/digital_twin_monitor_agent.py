"""Digital Twin Monitor Agent.

Registered in the agent framework under the name ``digital_twin_monitor``.
Runs a twin sync, analyses the resulting state map, and emits an Insight
describing every anomalous or degraded system node.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight
from src.reliability.models import TwinHealthStatus
from src.services.digital_twin_service import twin_snapshot

logger = logging.getLogger(__name__)


@register_agent
class DigitalTwinMonitorAgent(BaseAgent):
    """Digital Twin Monitor — live system-state map and anomaly detection."""

    name = "digital_twin_monitor"
    required_role = "ops"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        return twin_snapshot()

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        state_map = data.get("state_map", [])
        open_anomalies = data.get("open_anomalies", [])

        healthy = sum(1 for n in state_map if n.get("health_status") == TwinHealthStatus.HEALTHY.value)
        degraded = sum(1 for n in state_map if n.get("health_status") == TwinHealthStatus.DEGRADED.value)
        anomalous = sum(1 for n in state_map if n.get("health_status") == TwinHealthStatus.ANOMALOUS.value)
        unknown = sum(1 for n in state_map if n.get("health_status") == TwinHealthStatus.UNKNOWN.value)

        if anomalous > 0:
            system_health = "at_risk"
        elif degraded > 0:
            system_health = "attention"
        else:
            system_health = "healthy"

        return {
            "healthy": healthy,
            "degraded": degraded,
            "anomalous": anomalous,
            "unknown": unknown,
            "open_anomalies": len(open_anomalies),
            "system_health": system_health,
            "state_map": state_map,
            "anomaly_events": open_anomalies,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        system_health = analysis["system_health"]
        state_map = analysis["state_map"]
        anomaly_events = analysis["anomaly_events"]

        findings: list[str] = []
        risks: list[str] = []
        recommendations: list[str] = []

        # Findings — describe anomalous/degraded nodes
        for node in state_map:
            hs = node.get("health_status", "unknown")
            label = node.get("label", node.get("node_key", "unknown"))
            component = node.get("component", "unknown")
            if hs == TwinHealthStatus.ANOMALOUS.value:
                findings.append(f"[ANOMALOUS] {label} ({component}) — significant deviation from expected state")
                risks.append(f"{label} failure may cascade to downstream components")
                recommendations.append(f"Investigate {label} immediately; check component logs and run maintenance playbook")
            elif hs == TwinHealthStatus.DEGRADED.value:
                findings.append(f"[DEGRADED] {label} ({component}) — partial state contract failure")
                recommendations.append(f"Monitor {label} closely; consider proactive refresh")
            elif hs == TwinHealthStatus.UNKNOWN.value:
                findings.append(f"[UNKNOWN] {label} — state could not be collected")

        if not findings:
            findings.append("All system nodes are within expected state contracts.")

        # Risk summary
        if system_health == "at_risk":
            risks.insert(0, f"{analysis['anomalous']} node(s) in anomalous state — user-facing dashboards may be impacted")
        elif system_health == "attention":
            risks.insert(0, f"{analysis['degraded']} node(s) degraded — monitor for escalation")

        if not risks:
            risks.append("No active risks detected in twin state map.")

        # Recommendations
        if system_health == "healthy" and not recommendations:
            recommendations.append("System state map healthy — no action required.")

        open_count = analysis["open_anomalies"]
        if open_count > 0:
            recommendations.append(f"Review {open_count} open anomaly event(s) in the twin anomaly log.")

        return Insight(
            metrics={
                "healthy_nodes": analysis["healthy"],
                "degraded_nodes": analysis["degraded"],
                "anomalous_nodes": analysis["anomalous"],
                "unknown_nodes": analysis["unknown"],
                "open_anomaly_events": open_count,
                "system_health": system_health,
            },
            findings=findings,
            risks=risks,
            recommendations=recommendations,
            confidence_score=0.9 if analysis["healthy"] + analysis["degraded"] + analysis["anomalous"] > 0 else 0.5,
        )

    def write_cache(self, insight: Insight) -> None:
        try:
            from src.routers.cache_ui import get_shared_cache
            cache = get_shared_cache()
            cache.set(self.name, insight, ttl_seconds=300)
        except Exception as exc:
            logger.warning("digital_twin_monitor: cache write failed: %s", exc)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "healthy_nodes": "int",
            "degraded_nodes": "int",
            "anomalous_nodes": "int",
            "unknown_nodes": "int",
            "open_anomaly_events": "int",
            "system_health": "str",
        }
