"""Shared reliability primitives for the Placeware Maintenance, Digital Twin,
and Capability Discovery agents.

Re-exports the most commonly used symbols so callers can write:
    from src.reliability import IncidentSeverity, new_correlation_id, GUARDRAILS
"""
from .models import (
    IncidentSeverity,
    IncidentStatus,
    SystemComponent,
    ActionOutcome,
    CapabilityStatus,
    TwinHealthStatus,
)
from .correlation import new_correlation_id, tag_context
from .guardrails import GUARDRAILS

__all__ = [
    "IncidentSeverity",
    "IncidentStatus",
    "SystemComponent",
    "ActionOutcome",
    "CapabilityStatus",
    "TwinHealthStatus",
    "new_correlation_id",
    "tag_context",
    "GUARDRAILS",
]
