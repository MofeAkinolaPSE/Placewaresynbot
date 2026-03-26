"""Domain models and enums shared across the reliability stack.

These enums are intentionally *string-based* so they serialise cleanly to/from
JSON and PostgreSQL VARCHAR columns without extra conversion helpers.
"""
from __future__ import annotations

from enum import Enum


class IncidentSeverity(str, Enum):
    """Incident severity levels ordered from lowest to highest impact."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    """Lifecycle phases for an incident record."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class SystemComponent(str, Enum):
    """Recognised system layers tracked by the Digital Twin."""
    DATABASE = "database"
    PIPELINE = "pipeline"
    API = "api"
    CACHE = "cache"
    DASHBOARD = "dashboard"
    WORKER = "worker"


class ActionOutcome(str, Enum):
    """Result of a remediation or playbook action."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ESCALATED = "escalated"


class CapabilityStatus(str, Enum):
    """Governance lifecycle for a Capability Discovery proposal."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    DEFERRED = "deferred"


class TwinHealthStatus(str, Enum):
    """Health classification for a Digital Twin node."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ANOMALOUS = "anomalous"
    UNKNOWN = "unknown"
