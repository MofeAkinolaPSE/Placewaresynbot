"""Capability Discovery Engine.

Detects recurring capability gaps from system signals (maintenance incident
repairs, twin anomaly events, and repeated operational patterns) and generates
structured capability proposals for EOS / developer review.

This engine is strictly **proposal-only** — it never deploys, installs, or
modifies any system component.  All proposals require human approval before
any action can be taken.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.constants import (
    TABLE_CAPABILITY_PROPOSALS,
    TABLE_CAPABILITY_SIGNALS,
    TABLE_CAPABILITY_STATUS_HISTORY,
    TABLE_INCIDENT_LOG,
    TABLE_TWIN_ANOMALY_EVENTS,
)
from src.db import audit_event, db
from src.reliability.guardrails import GUARDRAILS
from src.reliability.models import CapabilityStatus

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# ---------------------------------------------------------------------------
# Signal ingestion
# ---------------------------------------------------------------------------

def record_signal(
    signal_type: str,
    description: str,
    component: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Upsert a capability signal, incrementing its frequency counter.

    If an identical description+signal_type combination already exists the
    frequency counter is bumped; otherwise a new signal is created.
    """
    existing = (
        db.table(TABLE_CAPABILITY_SIGNALS)
        .select("id,frequency")
        .eq("signal_type", signal_type)
        .eq("description", description)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        new_freq = int(row.get("frequency", 1)) + 1
        db.table(TABLE_CAPABILITY_SIGNALS).update({
            "frequency": new_freq,
            "last_seen_at": _utcnow_iso(),
            "metadata": metadata or {},
        }).eq("id", row["id"]).execute()
        return {"signal_id": row["id"], "frequency": new_freq, "created": False}

    res = db.table(TABLE_CAPABILITY_SIGNALS).insert({
        "signal_type": signal_type,
        "description": description,
        "component": component or "",
        "frequency": 1,
        "first_seen_at": _utcnow_iso(),
        "last_seen_at": _utcnow_iso(),
        "metadata": metadata or {},
    }).execute()
    signal_id = (res.data or [{}])[0].get("id", "")
    return {"signal_id": signal_id, "frequency": 1, "created": True}


def ingest_maintenance_signals() -> int:
    """Pull repeated open/escalated incidents as capability signals."""
    try:
        res = (
            db.table(TABLE_INCIDENT_LOG)
            .select("component,summary,status,detected_at")
            .in_("status", ["open", "escalated"])
            .order("detected_at", desc=True)
            .limit(GUARDRAILS.max_scan_rows)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        logger.error("capability: ingest_maintenance_signals failed: %s", exc)
        return 0

    ingested = 0
    # Group by component+summary to detect repeat patterns
    freq_map: Dict[str, int] = defaultdict(int)
    for row in rows:
        key = f"{row.get('component','')}: {row.get('summary','')}"
        freq_map[key] += 1

    for description, count in freq_map.items():
        if count >= 2:
            component = description.split(":")[0].strip()
            record_signal(
                signal_type="repeated_failure",
                description=description,
                component=component,
                metadata={"count": count, "source": "maintenance_incidents"},
            )
            ingested += 1

    return ingested


def ingest_twin_anomaly_signals() -> int:
    """Pull repeated twin anomaly events as capability signals."""
    try:
        res = (
            db.table(TABLE_TWIN_ANOMALY_EVENTS)
            .select("node_key,anomaly_type,severity")
            .is_("resolved_at", "null")
            .order("detected_at", desc=True)
            .limit(GUARDRAILS.max_scan_rows)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        logger.error("capability: ingest_twin_anomaly_signals failed: %s", exc)
        return 0

    ingested = 0
    freq_map: Dict[str, int] = defaultdict(int)
    for row in rows:
        key = f"{row.get('node_key','')}: {row.get('anomaly_type','')}"
        freq_map[key] += 1

    for description, count in freq_map.items():
        if count >= 2:
            component = description.split(":")[0].strip()
            record_signal(
                signal_type="twin_anomaly",
                description=description,
                component=component,
                metadata={"count": count, "source": "twin_anomaly_events"},
            )
            ingested += 1

    return ingested


# ---------------------------------------------------------------------------
# Clustering and proposal generation
# ---------------------------------------------------------------------------

def _get_high_frequency_signals(min_freq: int = 3) -> List[Dict[str, Any]]:
    """Return signals that meet the minimum frequency threshold."""
    try:
        res = (
            db.table(TABLE_CAPABILITY_SIGNALS)
            .select("*")
            .gte("frequency", min_freq)
            .order("frequency", desc=True)
            .limit(GUARDRAILS.max_signals_per_cluster * GUARDRAILS.max_proposals_per_run)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("capability: _get_high_frequency_signals failed: %s", exc)
        return []


def _build_blueprint(signal_cluster: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Generate a capability blueprint from a cluster of related signals.

    Returns None if the cluster is too weak to warrant a proposal.
    """
    if not signal_cluster:
        return None

    total_frequency = sum(int(s.get("frequency", 1)) for s in signal_cluster)
    if total_frequency < GUARDRAILS.min_signal_frequency_for_proposal:
        return None

    # Derive capability name from dominant signal
    primary = max(signal_cluster, key=lambda s: int(s.get("frequency", 1)))
    component = primary.get("component", "unknown")
    signal_type = primary.get("signal_type", "unknown")
    description = primary.get("description", "")

    # Confidence based on frequency and cluster size
    confidence = min(0.5 + (total_frequency / 20.0) + (len(signal_cluster) * 0.05), 0.95)

    # Map signal type to actionable blueprint fields
    if signal_type == "repeated_failure":
        capability_name = f"Automated Recovery: {component}"
        problem = f"Recurring failures detected in {component}: {description}"
        opportunity = (
            f"Implement automated recovery logic for {component} to reduce manual intervention "
            f"and MTTR. Observed {total_frequency} occurrences."
        )
        required_components = ["health_monitor", "auto_recovery_playbook", "escalation_handler"]
        integration_points = [f"{component}_service", "maintenance_agent", "incident_log"]
        estimated_impact = f"Estimated {min(total_frequency * 15, 120)} minutes/month saved in manual recovery time."
    elif signal_type == "twin_anomaly":
        capability_name = f"Resilient Pipeline: {component}"
        problem = f"Digital twin detects recurring anomalies in {component}: {description}"
        opportunity = (
            f"Build a self-healing pipeline layer for {component} to automatically "
            f"correct state drift. Observed {total_frequency} anomaly occurrences."
        )
        required_components = ["state_monitor", "pipeline_healer", "drift_corrector"]
        integration_points = [f"{component}_node", "digital_twin_engine", "anomaly_event_log"]
        estimated_impact = f"Reduce anomaly detection-to-resolution time for {component}."
    else:
        capability_name = f"Process Optimisation: {component}"
        problem = f"Repeated pattern detected in {component}: {description}"
        opportunity = f"Automate or optimise the {component} workflow. Observed {total_frequency} occurrences."
        required_components = ["workflow_automator"]
        integration_points = [f"{component}_service"]
        estimated_impact = "Reduce manual process overhead."

    return {
        "capability_name": capability_name,
        "problem": problem,
        "opportunity": opportunity,
        "required_components": required_components,
        "integration_points": integration_points,
        "estimated_impact": estimated_impact,
        "confidence_score": round(confidence, 3),
        "signal_ids": [s["id"] for s in signal_cluster if s.get("id")],
        "status": CapabilityStatus.PROPOSED.value,
    }


def _proposal_exists(capability_name: str) -> bool:
    """Return True if an active (non-rejected/implemented) proposal with this name exists."""
    try:
        res = (
            db.table(TABLE_CAPABILITY_PROPOSALS)
            .select("id")
            .eq("capability_name", capability_name)
            .not_.in_("status", [CapabilityStatus.REJECTED.value, CapabilityStatus.IMPLEMENTED.value])
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception:
        return False


def run_discovery_cycle() -> Dict[str, Any]:
    """Execute a full capability discovery cycle.

    Steps:
      1. Ingest signals from maintenance incidents and twin anomalies.
      2. Fetch high-frequency signal clusters.
      3. Generate blueprints and create proposals (skip duplicates).

    Returns a summary of ingested signals and proposals created.
    """
    maintenance_ingested = ingest_maintenance_signals()
    twin_ingested = ingest_twin_anomaly_signals()

    signals = _get_high_frequency_signals(min_freq=GUARDRAILS.min_signal_frequency_for_proposal)

    # Cluster by component
    component_clusters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in signals:
        component_clusters[s.get("component", "unknown")].append(s)

    proposals_created = 0
    proposal_names: List[str] = []

    for _component, cluster in list(component_clusters.items())[:GUARDRAILS.max_proposals_per_run]:
        blueprint = _build_blueprint(cluster)
        if blueprint is None:
            continue
        if _proposal_exists(blueprint["capability_name"]):
            continue

        try:
            res = db.table(TABLE_CAPABILITY_PROPOSALS).insert({
                "capability_name": blueprint["capability_name"],
                "problem": blueprint["problem"],
                "opportunity": blueprint["opportunity"],
                "required_components": blueprint["required_components"],
                "integration_points": blueprint["integration_points"],
                "estimated_impact": blueprint["estimated_impact"],
                "confidence_score": blueprint["confidence_score"],
                "signal_ids": blueprint["signal_ids"],
                "status": blueprint["status"],
            }).execute()
            proposal_id = (res.data or [{}])[0].get("id", "")
            proposals_created += 1
            proposal_names.append(blueprint["capability_name"])
            audit_event(
                "capability_proposal_created",
                {
                    "proposal_id": proposal_id,
                    "capability_name": blueprint["capability_name"],
                    "confidence": blueprint["confidence_score"],
                },
                event_class="reliability",
                action="create_proposal",
                outcome="success",
                subject_type="capability_proposal",
                subject_id=proposal_id,
            )
        except Exception as exc:
            logger.error("capability: failed to insert proposal: %s", exc)

    return {
        "signals_ingested": maintenance_ingested + twin_ingested,
        "maintenance_signals": maintenance_ingested,
        "twin_signals": twin_ingested,
        "high_frequency_signals": len(signals),
        "proposals_created": proposals_created,
        "proposals": proposal_names,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_active_proposals(limit: int = 50) -> List[Dict[str, Any]]:
    """Return proposals that are proposed or approved (not rejected/implemented)."""
    try:
        res = (
            db.table(TABLE_CAPABILITY_PROPOSALS)
            .select("*")
            .in_("status", [CapabilityStatus.PROPOSED.value, CapabilityStatus.APPROVED.value])
            .order("confidence_score", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("capability: get_active_proposals failed: %s", exc)
        return []


def get_recent_signals(limit: int = 100) -> List[Dict[str, Any]]:
    """Return recently updated signals."""
    try:
        res = (
            db.table(TABLE_CAPABILITY_SIGNALS)
            .select("*")
            .order("last_seen_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("capability: get_recent_signals failed: %s", exc)
        return []


def update_proposal_status(
    proposal_id: str,
    new_status: str,
    reviewer: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Transition a proposal's governance status."""
    # Get current status for history
    existing = (
        db.table(TABLE_CAPABILITY_PROPOSALS)
        .select("status,capability_name")
        .eq("id", proposal_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        return {"error": f"proposal {proposal_id} not found"}

    old_status = existing.data[0].get("status", "")
    update_payload: Dict[str, Any] = {
        "status": new_status,
        "updated_at": _utcnow_iso(),
    }
    if reviewer:
        update_payload["reviewed_by"] = reviewer
    if notes:
        update_payload["reviewer_notes"] = notes
    if new_status in (CapabilityStatus.APPROVED.value, CapabilityStatus.REJECTED.value):
        update_payload["reviewed_at"] = _utcnow_iso()

    db.table(TABLE_CAPABILITY_PROPOSALS).update(update_payload).eq("id", proposal_id).execute()

    # Record history
    db.table(TABLE_CAPABILITY_STATUS_HISTORY).insert({
        "proposal_id": proposal_id,
        "old_status": old_status,
        "new_status": new_status,
        "changed_by": reviewer or "system",
        "notes": notes or "",
        "changed_at": _utcnow_iso(),
    }).execute()

    audit_event(
        "capability_proposal_status_changed",
        {"proposal_id": proposal_id, "old": old_status, "new": new_status},
        event_class="reliability",
        action="update_proposal_status",
        outcome="success",
        subject_type="capability_proposal",
        subject_id=proposal_id,
    )
    return {"updated": True, "proposal_id": proposal_id, "old_status": old_status, "new_status": new_status}


def capability_snapshot() -> Dict[str, Any]:
    """Quick snapshot for agent collection: active proposals + recent signals."""
    return {
        "active_proposals": get_active_proposals(limit=20),
        "recent_signals": get_recent_signals(limit=50),
    }


# ---------------------------------------------------------------------------
# Background engine
# ---------------------------------------------------------------------------

@dataclass
class CapabilityDiscoveryEngine:
    """Periodic capability discovery loop."""

    light_interval_seconds: int = 86400    # daily light scan
    deep_interval_seconds: int = 604800    # weekly deep analysis

    async def run_loop(self) -> None:
        logger.info("CapabilityDiscoveryEngine: starting")
        await asyncio.sleep(60)  # stagger after app start
        cycle = 0
        while True:
            try:
                result = run_discovery_cycle()
                logger.info(
                    "capability_discovery: signals=%d proposals_created=%d",
                    result.get("signals_ingested", 0),
                    result.get("proposals_created", 0),
                )
            except Exception as exc:
                logger.error("CapabilityDiscoveryEngine loop error: %s", exc)
            cycle += 1
            await asyncio.sleep(self.light_interval_seconds)
