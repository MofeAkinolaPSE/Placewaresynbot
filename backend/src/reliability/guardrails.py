"""Guardrails for the reliability stack.

Centralises all safety limits so they can be reviewed and adjusted in one
place without hunting through service files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass(frozen=True)
class ReliabilityGuardrails:
    """Immutable safety configuration for the reliability agent stack."""

    # ── Retry / playbook limits ─────────────────────────────────────────────
    max_auto_retries: int = 3
    """Maximum times a playbook step may be auto-retried before giving up."""

    max_playbook_runs_per_incident: int = 5
    """Maximum total playbook executions allowed against a single incident."""

    # ── Safe-action whitelist ────────────────────────────────────────────────
    auto_fix_whitelist: FrozenSet[str] = field(default_factory=lambda: frozenset({
        "clear_cache",
        "recompute_kpi_aggregates",
        "restart_kpi_worker",
        "rebuild_cache_keyset",
        "refresh_finance_cache",
    }))
    """Only actions listed here may be executed automatically without EOS approval."""

    # ── Escalation thresholds (failed remediations before escalating) ────────
    escalation_threshold_critical: int = 0
    """Escalate immediately on critical severity — no auto-fix attempts."""

    escalation_threshold_high: int = 3
    escalation_threshold_medium: int = 5
    escalation_threshold_low: int = 10

    # ── Scan caps ────────────────────────────────────────────────────────────
    max_scan_rows: int = 500
    """Maximum rows read per table in a single diagnostic pass."""

    max_incidents_per_cycle: int = 20
    """How many open incidents the monitor loop processes per run."""

    max_twin_history_rows: int = 1000
    """Rows retained in state-history before oldest are pruned."""

    max_signals_per_cluster: int = 50
    """Cap on clustered signals fed into a single capability blueprint."""

    # ── Capability Discovery limits ─────────────────────────────────────────
    min_signal_frequency_for_proposal: int = 3
    """A signal cluster must appear at least this many times before generating a proposal."""

    max_proposals_per_run: int = 5
    """How many new proposals may be generated in a single discovery cycle."""

    def escalation_threshold_for(self, severity: str) -> int:
        """Return the escalation threshold for a given severity string."""
        mapping = {
            "critical": self.escalation_threshold_critical,
            "high": self.escalation_threshold_high,
            "medium": self.escalation_threshold_medium,
            "low": self.escalation_threshold_low,
        }
        return mapping.get(severity, self.escalation_threshold_medium)

    def is_action_safe(self, action_name: str) -> bool:
        """Return True if action_name is in the auto-fix whitelist."""
        return action_name in self.auto_fix_whitelist


# Singleton instance — import this directly in service modules
GUARDRAILS = ReliabilityGuardrails()
