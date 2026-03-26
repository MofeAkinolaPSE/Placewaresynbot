"""Correlation ID utilities for the reliability stack.

A correlation ID ties together a single incident, its diagnostics,
remediation actions, and any twin anomaly events that triggered it.

Format: rel-YYYYMMDDHHMMSS-<8 hex chars>
Example: rel-20260316142300-a3f7c812
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict


def new_correlation_id() -> str:
    """Generate a new, time-prefixed correlation ID."""
    ts = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"rel-{ts}-{suffix}"


def tag_context(correlation_id: str, component: str, action: str) -> Dict[str, Any]:
    """Build a structured context dict for audit logging and incident details.

    Args:
        correlation_id: The shared correlation ID for this incident chain.
        component: The system component involved (e.g. 'database', 'cache').
        action: The action being performed (e.g. 'detect', 'remediate').

    Returns:
        Dict suitable for passing as ``details`` in audit_event calls.
    """
    return {
        "correlation_id": correlation_id,
        "component": component,
        "action": action,
        "ts": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
