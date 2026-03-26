"""Tests for the reliability agent stack.

Covers:
- Phase 2: reliability primitives (models, guardrails, correlation)
- Phase 4: Digital Twin service and agent
- Phase 5: Capability Discovery service and agent
- Phase 6: agent registry integration + keyword routing

All DB calls are stubbed via monkeypatch so tests are hermetic and fast.
"""
from __future__ import annotations

import types
import uuid
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared test stubs
# ---------------------------------------------------------------------------

def _make_db_stub(table_data: dict | None = None):
    """Build a minimal Supabase-compatible DB stub returning configurable data."""
    data = table_data or {}

    class _TableStub:
        def __init__(self, name):
            self._name = name
            self._rows = list(data.get(name, []))

        # chainable query methods
        def select(self, *a, **kw): return self
        def insert(self, row):
            new_row = {**row, "id": str(uuid.uuid4())}
            self._rows.append(new_row)
            self._inserted = new_row
            return self
        def update(self, *a, **kw): return self
        def eq(self, *a, **kw): return self
        def in_(self, *a, **kw): return self
        def not_(self): return self  # noqa: E704
        def lt(self, *a, **kw): return self
        def gt(self, *a, **kw): return self
        def gte(self, *a, **kw): return self
        def lte(self, *a, **kw): return self
        def is_(self, *a, **kw): return self
        def order(self, *a, **kw): return self
        def limit(self, *a, **kw): return self
        def execute(self):
            inserted = getattr(self, "_inserted", None)
            rows = [inserted] if inserted else self._rows
            return types.SimpleNamespace(data=rows, count=len(rows))

    class _DBStub:
        def table(self, name):
            return _TableStub(name)

    return _DBStub()


# ---------------------------------------------------------------------------
# Phase 2: Reliability primitives
# ---------------------------------------------------------------------------


class TestIncidentSeverityEnum:
    def test_values(self):
        from src.reliability.models import IncidentSeverity
        assert IncidentSeverity.LOW.value == "low"
        assert IncidentSeverity.CRITICAL.value == "critical"

    def test_string_compat(self):
        from src.reliability.models import IncidentSeverity
        assert IncidentSeverity.HIGH == "high"


class TestIncidentStatusEnum:
    def test_resolved(self):
        from src.reliability.models import IncidentStatus
        assert IncidentStatus.RESOLVED.value == "resolved"


class TestTwinHealthStatus:
    def test_healthy(self):
        from src.reliability.models import TwinHealthStatus
        assert TwinHealthStatus.HEALTHY.value == "healthy"


class TestCapabilityStatus:
    def test_proposed(self):
        from src.reliability.models import CapabilityStatus
        assert CapabilityStatus.PROPOSED.value == "proposed"

    def test_implemented(self):
        from src.reliability.models import CapabilityStatus
        assert CapabilityStatus.IMPLEMENTED.value == "implemented"


class TestGuardrails:
    def test_defaults(self):
        from src.reliability.guardrails import GUARDRAILS
        assert GUARDRAILS.max_auto_retries == 3
        assert GUARDRAILS.max_playbook_runs_per_incident == 5
        assert GUARDRAILS.min_signal_frequency_for_proposal == 3

    def test_safe_action(self):
        from src.reliability.guardrails import GUARDRAILS
        assert GUARDRAILS.is_action_safe("clear_cache") is True
        assert GUARDRAILS.is_action_safe("drop_database") is False

    def test_escalation_threshold_critical(self):
        from src.reliability.guardrails import GUARDRAILS
        assert GUARDRAILS.escalation_threshold_for("critical") == 0

    def test_escalation_threshold_unknown_defaults_medium(self):
        from src.reliability.guardrails import GUARDRAILS
        assert GUARDRAILS.escalation_threshold_for("unknown") == 5


class TestCorrelation:
    def test_new_correlation_id_format(self):
        from src.reliability.correlation import new_correlation_id
        cid = new_correlation_id()
        assert cid.startswith("rel-")
        # format: rel-YYYYMMDDHHMMSS-8hex
        parts = cid.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 14  # YYYYMMDDHHMMSS
        assert len(parts[2]) == 8

    def test_tag_context(self):
        from src.reliability.correlation import tag_context
        ctx = tag_context("rel-abc", "database", "detect")
        assert ctx["correlation_id"] == "rel-abc"
        assert ctx["component"] == "database"
        assert ctx["action"] == "detect"
        assert "ts" in ctx


# ---------------------------------------------------------------------------
# Phase 4: Digital Twin service
# ---------------------------------------------------------------------------


class TestDigitalTwinStateComparison:
    def test_healthy_database_node(self):
        from src.services.digital_twin_service import compare_states
        defn = {
            "node_key": "database.ar_snapshot",
            "component": "database",
            "expected_state": {"min_row_count": 1, "table": "sage_ar_snapshot"},
        }
        actual = {"row_count": 500, "table": "sage_ar_snapshot", "collected_at": "2026-01-01T00:00:00Z"}
        result = compare_states(defn, actual)
        assert result["health_status"] == "healthy"
        assert result["anomaly_score"] == 0.0
        assert result["anomalies"] == []

    def test_anomalous_database_node_empty_table(self):
        from src.services.digital_twin_service import compare_states
        defn = {
            "node_key": "database.ar_snapshot",
            "component": "database",
            "expected_state": {"min_row_count": 1, "table": "sage_ar_snapshot"},
        }
        actual = {"row_count": 0, "table": "sage_ar_snapshot", "collected_at": "2026-01-01T00:00:00Z"}
        result = compare_states(defn, actual)
        assert len(result["anomalies"]) >= 1
        assert "row_count 0" in result["anomalies"][0]

    def test_collection_error_returns_unknown(self):
        from src.services.digital_twin_service import compare_states
        defn = {"node_key": "x", "component": "database", "expected_state": {}}
        actual = {"error": "connection refused"}
        result = compare_states(defn, actual)
        assert result["health_status"] == "unknown"
        assert result["anomaly_score"] == 1.0

    def test_api_node_non_zero_check(self):
        from src.services.digital_twin_service import compare_states
        defn = {
            "node_key": "api.finance_kpis",
            "component": "api",
            "expected_state": {"non_zero_fields": ["total_revenue", "cash"]},
        }
        actual = {"kpis": {"total_revenue": 0, "cash": None}, "collected_at": "2026-01-01T00:00:00Z"}
        result = compare_states(defn, actual)
        assert len(result["anomalies"]) == 2  # both total_revenue and cash are bad

    def test_pipeline_node_partial_tables(self):
        from src.services.digital_twin_service import compare_states
        defn = {
            "node_key": "pipeline.finance_import",
            "component": "pipeline",
            "expected_state": {"required_tables": ["t1", "t2", "t3"]},
        }
        actual = {"tables": {"t1": 10, "t2": 0, "t3": 5}, "populated_count": 2, "total_required": 3, "collected_at": ""}
        result = compare_states(defn, actual)
        assert len(result["anomalies"]) == 1
        assert "1/3" in result["anomalies"][0]


class TestDigitalTwinAgent:
    def test_agent_registered(self):
        from src.agent_registry import get_agent
        import src.agents  # ensure agents are registered  # noqa: F401
        agent_cls = get_agent("digital_twin_monitor")
        assert agent_cls is not None

    def test_generate_insights_healthy(self):
        from src.agents.digital_twin_monitor_agent import DigitalTwinMonitorAgent
        agent = DigitalTwinMonitorAgent()
        analysis = {
            "healthy": 8, "degraded": 0, "anomalous": 0, "unknown": 0,
            "open_anomalies": 0, "system_health": "healthy",
            "state_map": [], "anomaly_events": [],
        }
        insight = agent.generate_insights(analysis)
        assert insight.metrics["system_health"] == "healthy"
        assert "No active risks" in insight.risks[0]

    def test_generate_insights_at_risk(self):
        from src.agents.digital_twin_monitor_agent import DigitalTwinMonitorAgent
        from src.reliability.models import TwinHealthStatus
        agent = DigitalTwinMonitorAgent()
        analysis = {
            "healthy": 5, "degraded": 1, "anomalous": 2, "unknown": 0,
            "open_anomalies": 3, "system_health": "at_risk",
            "state_map": [
                {"node_key": "database.ar_snapshot", "label": "AR Table", "component": "database",
                 "health_status": TwinHealthStatus.ANOMALOUS.value},
            ],
            "anomaly_events": [],
        }
        insight = agent.generate_insights(analysis)
        assert insight.metrics["system_health"] == "at_risk"
        assert any("ANOMALOUS" in f for f in insight.findings)
        assert any("cascade" in r.lower() for r in insight.risks)


# ---------------------------------------------------------------------------
# Phase 5: Capability Discovery service
# ---------------------------------------------------------------------------


class TestCapabilityGuardrailIntegration:
    def test_blueprint_below_threshold_returns_none(self):
        from src.services.capability_engine import _build_blueprint
        from src.reliability.guardrails import GUARDRAILS
        # frequency = 1, below min_signal_frequency_for_proposal = 3
        signals = [{"id": "s1", "signal_type": "repeated_failure", "component": "database",
                    "description": "db error", "frequency": 1}]
        result = _build_blueprint(signals)
        assert result is None

    def test_blueprint_above_threshold_generated(self):
        from src.services.capability_engine import _build_blueprint
        signals = [{"id": "s1", "signal_type": "repeated_failure", "component": "database",
                    "description": "repeated db timeout", "frequency": 5}]
        result = _build_blueprint(signals)
        assert result is not None
        assert "database" in result["capability_name"].lower()
        assert result["confidence_score"] > 0.5
        assert result["status"] == "proposed"

    def test_twin_anomaly_blueprint(self):
        from src.services.capability_engine import _build_blueprint
        signals = [{"id": "s2", "signal_type": "twin_anomaly", "component": "pipeline",
                    "description": "pipeline empty output", "frequency": 8}]
        result = _build_blueprint(signals)
        assert result is not None
        assert "pipeline" in result["capability_name"].lower()


class TestCapabilityDiscoveryAgent:
    def test_agent_registered(self):
        from src.agent_registry import get_agent
        import src.agents  # noqa: F401
        agent_cls = get_agent("capability_discovery")
        assert agent_cls is not None

    def test_generate_insights_no_proposals(self):
        from src.agents.capability_discovery_agent import CapabilityDiscoveryAgent
        agent = CapabilityDiscoveryAgent()
        analysis = {
            "total_active_proposals": 0, "proposed_count": 0, "approved_count": 0,
            "high_confidence_proposals": 0, "total_signals": 0,
            "new_proposals_this_cycle": 0, "signals_this_cycle": 0,
            "top_proposal": None, "proposals": [], "signals": [],
        }
        insight = agent.generate_insights(analysis)
        assert insight.metrics["total_active_proposals"] == 0
        assert "No active capability" in insight.findings[0]

    def test_generate_insights_with_proposals(self):
        from src.agents.capability_discovery_agent import CapabilityDiscoveryAgent
        agent = CapabilityDiscoveryAgent()
        proposals = [
            {"capability_name": "Auto Recovery: database", "status": "proposed", "confidence_score": 0.85,
             "problem": "db timeouts", "opportunity": "auto-retry"},
        ]
        analysis = {
            "total_active_proposals": 1, "proposed_count": 1, "approved_count": 0,
            "high_confidence_proposals": 1, "total_signals": 5,
            "new_proposals_this_cycle": 1, "signals_this_cycle": 3,
            "top_proposal": proposals[0], "proposals": proposals, "signals": [],
        }
        insight = agent.generate_insights(analysis)
        assert insight.metrics["total_active_proposals"] == 1
        assert any("Auto Recovery" in f for f in insight.findings)
        assert any("Review" in r for r in insight.recommendations)


# ---------------------------------------------------------------------------
# Phase 6: Agent routing
# ---------------------------------------------------------------------------


class TestAgentKeywordRouting:
    def test_twin_keyword_routes_to_monitor(self):
        from src.agents.router import route_question
        result = route_question("show me the digital twin state map", {"ops"}, "assistant")
        assert "digital_twin_monitor" in result

    def test_capability_keyword_routes_to_discovery(self):
        from src.agents.router import route_question
        result = route_question("what capability gaps have been discovered?", {"ops"}, "assistant")
        assert "capability_discovery" in result

    def test_maintenance_keyword_routes_to_maintenance(self):
        from src.agents.router import route_question
        result = route_question("any maintenance incidents today?", {"ops"}, "assistant")
        assert "maintenance_tracking" in result

    def test_anomaly_keyword_routes_to_twin(self):
        from src.agents.router import route_question
        result = route_question("check system anomaly events", {"ops"}, "assistant")
        assert "digital_twin_monitor" in result
