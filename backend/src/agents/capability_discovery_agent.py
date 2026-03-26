"""Capability Discovery Agent.

Registered under the name ``capability_discovery``.  Runs a discovery cycle,
analyses the resulting proposals and signals, and emits an Insight describing
detected capability gaps and generated proposals.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight
from src.services.capability_engine import capability_snapshot, run_discovery_cycle

logger = logging.getLogger(__name__)


@register_agent
class CapabilityDiscoveryAgent(BaseAgent):
    """Capability Discovery — identifies missing capabilities and generates proposals."""

    name = "capability_discovery"
    required_role = "ops"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        snapshot = capability_snapshot()
        # Also trigger a fresh discovery cycle to ingest latest signals
        try:
            cycle_result = run_discovery_cycle()
            snapshot["latest_cycle"] = cycle_result
        except Exception as exc:
            logger.warning("capability_discovery: cycle error during collect: %s", exc)
            snapshot["latest_cycle"] = {}
        return snapshot

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        proposals = data.get("active_proposals", [])
        signals = data.get("recent_signals", [])
        cycle = data.get("latest_cycle", {})

        proposed_count = sum(1 for p in proposals if p.get("status") == "proposed")
        approved_count = sum(1 for p in proposals if p.get("status") == "approved")
        high_conf = [p for p in proposals if float(p.get("confidence_score", 0)) >= 0.7]
        top_proposal = max(proposals, key=lambda p: float(p.get("confidence_score", 0)), default=None)

        return {
            "total_active_proposals": len(proposals),
            "proposed_count": proposed_count,
            "approved_count": approved_count,
            "high_confidence_proposals": len(high_conf),
            "total_signals": len(signals),
            "new_proposals_this_cycle": cycle.get("proposals_created", 0),
            "signals_this_cycle": cycle.get("signals_ingested", 0),
            "top_proposal": top_proposal,
            "proposals": proposals,
            "signals": signals,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        proposals = analysis["proposals"]
        top = analysis.get("top_proposal")

        findings: list[str] = []
        risks: list[str] = []
        recommendations: list[str] = []

        if analysis["new_proposals_this_cycle"] > 0:
            findings.append(
                f"{analysis['new_proposals_this_cycle']} new capability proposal(s) generated this cycle."
            )

        if top:
            conf = float(top.get("confidence_score", 0))
            findings.append(
                f"Highest-confidence proposal: '{top['capability_name']}' "
                f"(confidence {conf:.0%}) — {top.get('problem', '')}"
            )

        for p in proposals[:5]:
            name = p.get("capability_name", "")
            status = p.get("status", "")
            conf = float(p.get("confidence_score", 0))
            findings.append(f"[{status.upper()}] {name} — confidence {conf:.0%}")
            if status == "proposed":
                recommendations.append(f"Review and approve/reject: '{name}'")

        if not findings:
            findings.append("No active capability proposals — system is operating within known capabilities.")

        if analysis["total_signals"] > 20:
            risks.append(
                f"{analysis['total_signals']} signals detected — elevated pattern density may indicate "
                "structural gaps requiring architecture review."
            )

        if analysis["approved_count"] > 0:
            recommendations.append(
                f"{analysis['approved_count']} approved proposal(s) pending implementation — "
                "schedule developer sprint to act on them."
            )

        if not risks:
            risks.append("No high-density signal clusters detected.")

        if not recommendations:
            recommendations.append("Continue monitoring signal frequency for new capability gaps.")

        return Insight(
            metrics={
                "total_active_proposals": analysis["total_active_proposals"],
                "proposed_count": analysis["proposed_count"],
                "approved_count": analysis["approved_count"],
                "high_confidence_proposals": analysis["high_confidence_proposals"],
                "total_signals": analysis["total_signals"],
                "new_proposals_this_cycle": analysis["new_proposals_this_cycle"],
            },
            findings=findings,
            risks=risks,
            recommendations=recommendations,
            confidence_score=0.8,
        )

    def write_cache(self, insight: Insight) -> None:
        try:
            from src.routers.cache_ui import get_shared_cache
            cache = get_shared_cache()
            cache.set(self.name, insight, ttl_seconds=3600)  # 1-hour cache for capability data
        except Exception as exc:
            logger.warning("capability_discovery: cache write failed: %s", exc)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "total_active_proposals": "int",
            "proposed_count": "int",
            "approved_count": "int",
            "high_confidence_proposals": "int",
            "total_signals": "int",
            "new_proposals_this_cycle": "int",
        }
