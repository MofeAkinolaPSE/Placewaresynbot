"""Digital Twin Monitor Service.

Maintains a live state map of every system layer (database → pipeline → API →
cache → dashboard).  On each sync cycle it:
  1. Collects the actual state of each registered node.
  2. Compares it against the expected state to compute an anomaly score.
  3. Persists a state-history snapshot.
  4. Emits anomaly events for nodes that fail their health contract.

The DigitalTwinEngine background loop feeds diagnostic intelligence to the
Maintenance Agent and the Capability Discovery Agent.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.constants import (
    RELIABILITY_OBSERVE_ONLY,
    TABLE_TWIN_ANOMALY_EVENTS,
    TABLE_TWIN_DEPENDENCY_EDGES,
    TABLE_TWIN_NODES,
    TABLE_TWIN_STATE_HISTORY,
)
from src.db import audit_event, db
from src.reliability.correlation import new_correlation_id
from src.reliability.models import TwinHealthStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System node definitions — the contract each layer is expected to satisfy
# ---------------------------------------------------------------------------

SYSTEM_NODE_DEFINITIONS: List[Dict[str, Any]] = [
    # ── Database layer ──────────────────────────────────────────────────────
    {
        "node_key": "database.ar_snapshot",
        "component": "database",
        "label": "AR Snapshot Table",
        "expected_state": {"min_row_count": 1, "table": "sage_ar_snapshot"},
    },
    {
        "node_key": "database.ap_snapshot",
        "component": "database",
        "label": "AP Snapshot Table",
        "expected_state": {"min_row_count": 1, "table": "sage_ap_snapshot"},
    },
    {
        "node_key": "database.gl_snapshot",
        "component": "database",
        "label": "GL Snapshot Table",
        "expected_state": {"min_row_count": 1, "table": "sage_gl_snapshot"},
    },
    {
        "node_key": "database.inventory_snapshot",
        "component": "database",
        "label": "Inventory Snapshot Table",
        "expected_state": {"min_row_count": 1, "table": "placeware_inventory_snapshot"},
    },
    # ── Pipeline layer ──────────────────────────────────────────────────────
    {
        "node_key": "pipeline.finance_import",
        "component": "pipeline",
        "label": "Finance Sage Import Pipeline",
        "expected_state": {
            "required_tables": ["sage_ar_snapshot", "sage_gl_snapshot", "sage_ap_snapshot"],
        },
    },
    # ── API layer ───────────────────────────────────────────────────────────
    {
        "node_key": "api.finance_kpis",
        "component": "api",
        "label": "Finance KPIs Aggregation",
        "expected_state": {"non_zero_fields": ["total_revenue", "cash"]},
    },
    # ── Cache layer ─────────────────────────────────────────────────────────
    {
        "node_key": "cache.finance",
        "component": "cache",
        "label": "Finance Cache",
        "expected_state": {"cache_key_prefix": "financial_analyst"},
    },
    # ── Dashboard layer ─────────────────────────────────────────────────────
    {
        "node_key": "dashboard.finance",
        "component": "dashboard",
        "label": "Finance Dashboard Readiness",
        "expected_state": {"kpi_fields_non_null": ["ar", "ap", "cash", "total_revenue"]},
    },
]

# Dependency edges (source feeds into target)
DEPENDENCY_EDGES = [
    ("database.ar_snapshot",     "pipeline.finance_import"),
    ("database.ap_snapshot",     "pipeline.finance_import"),
    ("database.gl_snapshot",     "pipeline.finance_import"),
    ("pipeline.finance_import",  "api.finance_kpis"),
    ("api.finance_kpis",         "cache.finance"),
    ("cache.finance",            "dashboard.finance"),
]


def _utcnow_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_row_count(table: str) -> int:
    """Return row count for *table* or 0 on any error."""
    try:
        res = db.table(table).select("id", count="exact").limit(1).execute()
        return int(getattr(res, "count", 0) or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Node seeding
# ---------------------------------------------------------------------------

def ensure_nodes_seeded() -> None:
    """Upsert all SYSTEM_NODE_DEFINITIONS into placeware_twin_nodes."""
    for defn in SYSTEM_NODE_DEFINITIONS:
        existing = (
            db.table(TABLE_TWIN_NODES)
            .select("id")
            .eq("node_key", defn["node_key"])
            .limit(1)
            .execute()
        )
        if existing.data:
            continue
        db.table(TABLE_TWIN_NODES).insert({
            "node_key": defn["node_key"],
            "component": defn["component"],
            "label": defn["label"],
            "expected_state": defn["expected_state"],
            "actual_state": {},
            "health_status": TwinHealthStatus.UNKNOWN.value,
        }).execute()

    # Upsert dependency edges
    for src, tgt in DEPENDENCY_EDGES:
        existing = (
            db.table(TABLE_TWIN_DEPENDENCY_EDGES)
            .select("id")
            .eq("source_key", src)
            .eq("target_key", tgt)
            .limit(1)
            .execute()
        )
        if not existing.data:
            db.table(TABLE_TWIN_DEPENDENCY_EDGES).insert({
                "source_key": src,
                "target_key": tgt,
                "direction": "forward",
                "weight": 1.0,
            }).execute()


# ---------------------------------------------------------------------------
# State collectors — one per component type
# ---------------------------------------------------------------------------

def _collect_database_state(node_defn: Dict[str, Any]) -> Dict[str, Any]:
    table = node_defn["expected_state"].get("table", "")
    row_count = _safe_row_count(table)
    return {"row_count": row_count, "table": table, "collected_at": _utcnow_iso()}


def _collect_pipeline_state(node_defn: Dict[str, Any]) -> Dict[str, Any]:
    required = node_defn["expected_state"].get("required_tables", [])
    table_counts = {t: _safe_row_count(t) for t in required}
    populated = sum(1 for v in table_counts.values() if v > 0)
    return {
        "tables": table_counts,
        "populated_count": populated,
        "total_required": len(required),
        "collected_at": _utcnow_iso(),
    }


def _collect_api_state(node_defn: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from src.services.sage_adapter.service import kpis  # local import to avoid circular
        data = kpis()
    except Exception as exc:
        data = {}
        logger.warning("digital_twin: kpis() fetch failed: %s", exc)
    return {"kpis": data, "collected_at": _utcnow_iso()}


def _collect_cache_state(node_defn: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from src.routers.cache_ui import get_shared_cache  # lazy import
        cache = get_shared_cache()
        # Probe a known cache key to determine freshness
        key_prefix = node_defn["expected_state"].get("cache_key_prefix", "")
        hit = cache.get(key_prefix) is not None if key_prefix else False
    except Exception:
        hit = False
    return {"cache_hit": hit, "collected_at": _utcnow_iso()}


def _collect_dashboard_state(node_defn: Dict[str, Any]) -> Dict[str, Any]:
    """Dashboard health is proxied by checking that KPI fields are non-null."""
    try:
        from src.services.sage_adapter.service import kpis
        data = kpis()
    except Exception:
        data = {}
    required = node_defn["expected_state"].get("kpi_fields_non_null", [])
    null_fields = [f for f in required if not data.get(f)]
    return {
        "null_fields": null_fields,
        "all_populated": len(null_fields) == 0,
        "collected_at": _utcnow_iso(),
    }


_COLLECTORS = {
    "database":  _collect_database_state,
    "pipeline":  _collect_pipeline_state,
    "api":       _collect_api_state,
    "cache":     _collect_cache_state,
    "dashboard": _collect_dashboard_state,
}


def collect_node_actual_state(node_defn: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch to the correct collector based on component type."""
    component = node_defn.get("component", "")
    collector = _COLLECTORS.get(component)
    if collector is None:
        return {"error": f"no collector for component '{component}'", "collected_at": _utcnow_iso()}
    try:
        return collector(node_defn)
    except Exception as exc:
        logger.error("twin: collection error for %s: %s", node_defn.get("node_key"), exc)
        return {"error": str(exc), "collected_at": _utcnow_iso()}


# ---------------------------------------------------------------------------
# State comparison — expected vs actual → anomaly score + health status
# ---------------------------------------------------------------------------

def compare_states(node_defn: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    """Compare expected contract against actual state.

    Returns:
        {
          "anomaly_score": float (0.0–1.0),
          "health_status": str,
          "anomalies": List[str],   # human-readable failure descriptions
        }
    """
    expected = node_defn.get("expected_state", {})
    component = node_defn.get("component", "")
    anomalies: List[str] = []

    if actual.get("error"):
        return {
            "anomaly_score": 1.0,
            "health_status": TwinHealthStatus.UNKNOWN.value,
            "anomalies": [f"collection_error: {actual['error']}"],
        }

    if component == "database":
        min_rows = expected.get("min_row_count", 1)
        got = actual.get("row_count", 0)
        if got < min_rows:
            anomalies.append(f"row_count {got} < expected {min_rows}")

    elif component == "pipeline":
        populated = actual.get("populated_count", 0)
        total = actual.get("total_required", 1)
        missing = total - populated
        if missing > 0:
            anomalies.append(f"{missing}/{total} required pipeline tables empty")

    elif component == "api":
        non_zero = expected.get("non_zero_fields", [])
        kpi_data = actual.get("kpis", {})
        for field in non_zero:
            val = kpi_data.get(field)
            if val is None or val == 0:
                anomalies.append(f"api field '{field}' is null/zero")

    elif component == "cache":
        if not actual.get("cache_hit"):
            anomalies.append("cache miss — no warm data found")

    elif component == "dashboard":
        nulls = actual.get("null_fields", [])
        if nulls:
            anomalies.append(f"dashboard null fields: {', '.join(nulls)}")

    # Score: fraction of detected anomalies vs total checks (min 1 check)
    total_checks = max(len(expected) or 1, 1)
    score = min(len(anomalies) / total_checks, 1.0)

    if score == 0:
        health = TwinHealthStatus.HEALTHY.value
    elif score < 0.5:
        health = TwinHealthStatus.DEGRADED.value
    else:
        health = TwinHealthStatus.ANOMALOUS.value

    return {"anomaly_score": round(score, 4), "health_status": health, "anomalies": anomalies}


# ---------------------------------------------------------------------------
# Anomaly event persistence
# ---------------------------------------------------------------------------

def emit_anomaly_event(
    node_key: str,
    node_id: Optional[str],
    anomaly_type: str,
    severity: str,
    details: Dict[str, Any],
    correlation_id: str,
) -> str:
    """Insert a new anomaly event and return its ID.

    In RELIABILITY_OBSERVE_ONLY mode the event is logged but NOT persisted,
    so shadow-mode deployments don't pollute the anomaly log.
    """
    if RELIABILITY_OBSERVE_ONLY:
        logger.info(
            "observe-only: twin anomaly suppressed — node=%s type=%s severity=%s",
            node_key, anomaly_type, severity,
        )
        return ""
    row = {
        "node_key": node_key,
        "anomaly_type": anomaly_type,
        "severity": severity,
        "details": details,
        "correlation_id": correlation_id,
        "detected_at": _utcnow_iso(),
    }
    if node_id:
        row["node_id"] = node_id
    res = db.table(TABLE_TWIN_ANOMALY_EVENTS).insert(row).execute()
    event_id = (res.data or [{}])[0].get("id", "")
    audit_event(
        "twin_anomaly_detected",
        {"node_key": node_key, "anomaly_type": anomaly_type, "correlation_id": correlation_id},
        event_class="reliability",
        action="detect_anomaly",
        outcome="detected",
        subject_type="twin_node",
        subject_id=node_key,
    )
    return event_id


# ---------------------------------------------------------------------------
# Full sync cycle
# ---------------------------------------------------------------------------

def run_twin_sync() -> Dict[str, Any]:
    """Run one full sync pass over all registered system nodes.

    For each node:
      - Collect actual state
      - Compare with expected
      - Update the node record
      - Insert a history snapshot
      - Emit anomaly events for unhealthy nodes

    Returns a summary dict with counts and list of unhealthy nodes.
    """
    try:
        ensure_nodes_seeded()
    except Exception as exc:
        logger.error("twin: failed to seed nodes: %s", exc)
        return {"error": str(exc), "healthy": 0, "degraded": 0, "anomalous": 0}

    correlation_id = new_correlation_id()
    healthy_count = 0
    degraded_count = 0
    anomalous_count = 0
    anomaly_events_emitted: List[str] = []

    for defn in SYSTEM_NODE_DEFINITIONS:
        node_key = defn["node_key"]
        try:
            actual = collect_node_actual_state(defn)
            comparison = compare_states(defn, actual)
            health = comparison["health_status"]
            score = comparison["anomaly_score"]
            anomalies = comparison["anomalies"]

            # Look up node DB id
            node_row = (
                db.table(TABLE_TWIN_NODES)
                .select("id")
                .eq("node_key", node_key)
                .limit(1)
                .execute()
            )
            node_id = (node_row.data or [{}])[0].get("id")

            # Update node record
            db.table(TABLE_TWIN_NODES).update({
                "actual_state": actual,
                "health_status": health,
                "last_sync_at": _utcnow_iso(),
            }).eq("node_key", node_key).execute()

            # Insert history snapshot
            db.table(TABLE_TWIN_STATE_HISTORY).insert({
                "node_id": node_id,
                "node_key": node_key,
                "snapshot": {"actual": actual, "comparison": comparison},
                "anomaly_score": score,
                "captured_at": _utcnow_iso(),
            }).execute()

            if health == TwinHealthStatus.HEALTHY.value:
                healthy_count += 1
            elif health == TwinHealthStatus.DEGRADED.value:
                degraded_count += 1
                if anomalies:
                    eid = emit_anomaly_event(
                        node_key, node_id,
                        anomaly_type="degraded_state",
                        severity="medium",
                        details={"anomalies": anomalies, "actual": actual},
                        correlation_id=correlation_id,
                    )
                    anomaly_events_emitted.append(eid)
            elif health == TwinHealthStatus.ANOMALOUS.value:
                anomalous_count += 1
                if anomalies:
                    eid = emit_anomaly_event(
                        node_key, node_id,
                        anomaly_type="anomalous_state",
                        severity="high",
                        details={"anomalies": anomalies, "actual": actual},
                        correlation_id=correlation_id,
                    )
                    anomaly_events_emitted.append(eid)

        except Exception as exc:
            logger.error("twin sync error for node %s: %s", node_key, exc)
            anomalous_count += 1

    return {
        "correlation_id": correlation_id,
        "synced_at": _utcnow_iso(),
        "healthy": healthy_count,
        "degraded": degraded_count,
        "anomalous": anomalous_count,
        "anomaly_events_emitted": len(anomaly_events_emitted),
        "total_nodes": len(SYSTEM_NODE_DEFINITIONS),
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_current_state_map() -> List[Dict[str, Any]]:
    """Return all twin nodes with their latest actual state."""
    try:
        res = (
            db.table(TABLE_TWIN_NODES)
            .select("node_key,component,label,actual_state,health_status,last_sync_at")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("twin: get_current_state_map failed: %s", exc)
        return []


def get_open_anomalies(limit: int = 50) -> List[Dict[str, Any]]:
    """Return unresolved anomaly events ordered by detected_at DESC."""
    try:
        res = (
            db.table(TABLE_TWIN_ANOMALY_EVENTS)
            .select("*")
            .is_("resolved_at", "null")
            .order("detected_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("twin: get_open_anomalies failed: %s", exc)
        return []


def resolve_anomaly(anomaly_id: str, note: str = "") -> Dict[str, Any]:
    """Mark an anomaly event as resolved."""
    db.table(TABLE_TWIN_ANOMALY_EVENTS).update({
        "resolved_at": _utcnow_iso(),
        "details": db.table(TABLE_TWIN_ANOMALY_EVENTS)  # merge note inline via Python
    }).eq("id", anomaly_id).execute()
    # Simpler approach: just set resolved_at
    db.table(TABLE_TWIN_ANOMALY_EVENTS).update({"resolved_at": _utcnow_iso()}).eq("id", anomaly_id).execute()
    return {"resolved": True, "anomaly_id": anomaly_id}


def get_dependency_graph() -> Dict[str, Any]:
    """Return nodes and edges for a dependency graph view."""
    try:
        nodes_res = db.table(TABLE_TWIN_NODES).select("node_key,component,label,health_status").execute()
        edges_res = db.table(TABLE_TWIN_DEPENDENCY_EDGES).select("source_key,target_key,direction,weight").execute()
        return {
            "nodes": nodes_res.data or [],
            "edges": edges_res.data or [],
        }
    except Exception as exc:
        logger.error("twin: get_dependency_graph failed: %s", exc)
        return {"nodes": [], "edges": []}


def twin_snapshot() -> Dict[str, Any]:
    """Quick snapshot for agent collection: state map + open anomalies."""
    return {
        "state_map": get_current_state_map(),
        "open_anomalies": get_open_anomalies(limit=20),
        "dependency_graph": get_dependency_graph(),
    }


# ---------------------------------------------------------------------------
# Background engine
# ---------------------------------------------------------------------------

@dataclass
class DigitalTwinEngine:
    """Periodic twin sync loop — runs as an asyncio background task."""

    interval_seconds: int = 600  # 10-minute default cycle

    async def run_loop(self) -> None:
        logger.info("DigitalTwinEngine: starting (interval=%ds)", self.interval_seconds)
        await asyncio.sleep(30)  # stagger after app start
        while True:
            try:
                result = run_twin_sync()
                logger.info(
                    "twin_sync: healthy=%d degraded=%d anomalous=%d events=%d",
                    result.get("healthy", 0),
                    result.get("degraded", 0),
                    result.get("anomalous", 0),
                    result.get("anomaly_events_emitted", 0),
                )
            except Exception as exc:
                logger.error("DigitalTwinEngine loop error: %s", exc)
            await asyncio.sleep(self.interval_seconds)

    def run_once(self) -> Dict[str, Any]:
        """Synchronous single-pass twin sync (for testing / manual trigger)."""
        return run_twin_sync()
