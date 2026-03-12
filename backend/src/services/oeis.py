from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

from src.cache import invalidate_cache_tags
from src.db import audit_event, db
from src.constants import TABLE_AUDIT_LOGS
from src.services.realtime import realtime_hub
from src.services import kg_graph
from src.services.schema_registry_service import get_schema, validate_event_payload
from src.workflow.workflow_jobs import engine as workflow_jobs_engine

logger = logging.getLogger("oeis")

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")


@dataclass
class OeisResult:
    event_id: str | None
    version_hash: str
    schema_valid: bool
    schema_errors: list[dict[str, str]]
    workflow_job_ids: list[str]
    agent_runs: list[dict[str, Any]]
    kg_updates: dict[str, int]


def _append_local_ledger(event: dict[str, Any]) -> None:
    parent = os.path.dirname(LEDGER_PATH)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _compute_version_hash(event: dict[str, Any]) -> str:
    clone = dict(event)
    clone.pop("version_hash", None)
    serialized = json.dumps(clone, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _cache_tags_for_event(department: str, event_type: str) -> list[str]:
    dep = (department or "").lower().strip()
    tags = ["executive", "alerts"]

    if dep in {"inventory", "operations", "ops", "logistics"}:
        tags.extend(["inventory", "inventory_dashboard", "logistics", "ops_kpis"])
    if dep in {"finance", "billing", "accounting"}:
        tags.extend(["finance", "finance_kpis", "finance_trend", "finance_gl"])
    if dep in {"crm", "sales"}:
        tags.extend(["crm", "crm_dashboard", "crm_risk_scores"])
    if dep in {"hr", "staff", "workforce"}:
        tags.extend(["staff", "workforce_dashboard", "hr_summary"])

    et = (event_type or "").lower()
    if "approval" in et or "workflow" in et:
        tags.extend(["finance", "ops_kpis"])

    return list(dict.fromkeys(tags))


def _workflow_triggers_for_event(department: str, event_type: str, payload: dict[str, Any], schema: dict[str, Any] | None) -> list[str]:
    dep = (department or "").lower().strip()
    et = (event_type or "").lower().strip()

    explicit = schema.get("workflow_id") if isinstance(schema, dict) else None
    if explicit:
        return [str(explicit)]

    triggers: list[str] = []
    if dep in {"inventory", "ops", "operations"} and ("stock" in et or "inventory" in et):
        triggers.append("inventory.create_replenishment")
    if dep in {"finance"} and ("credit" in et or "risk" in et):
        triggers.append("finance.flag_credit_risk")
    if dep in {"procurement"} and ("clearance" in et or "shipment" in et):
        triggers.append("procurement.escalate_clearance")
    if dep in {"compliance"} and ("lock" in et):
        triggers.append("compliance.lock_batch")
    if dep in {"logistics"} and ("breach" in et or "delay" in et):
        triggers.append("logistics.delivery_breach")

    if payload.get("approval_required") or payload.get("approval_status") == "pending":
        # discover flow will create approvable jobs for all events, so no extra hard requirement.
        pass

    return list(dict.fromkeys(triggers))


def _agent_names_for_event(department: str, event_type: str) -> list[str]:
    dep = (department or "").lower().strip()
    et = (event_type or "").lower().strip()

    names: list[str] = []
    if dep in {"inventory", "ops", "operations"}:
        names.extend(["inventory_intelligence", "logistics_optimization"])
    if dep in {"finance"}:
        names.extend(["financial_analyst", "enterprise_risk"])
    if dep in {"crm", "sales"}:
        names.extend(["revenue_strategy", "enterprise_risk"])
    if dep in {"compliance"}:
        names.extend(["compliance_monitoring", "enterprise_risk"])
    if dep in {"procurement"}:
        names.extend(["import_clearance", "enterprise_risk"])

    if "expiry" in et:
        names.append("expiry_monitoring")

    return list(dict.fromkeys(names))


def _run_agents(agent_names: list[str], actor_id: str | None) -> list[dict[str, Any]]:
    from src.agent_registry import get_agent

    results: list[dict[str, Any]] = []
    for name in agent_names:
        try:
            agent = get_agent(name, context={"actor_id": actor_id, "auto_trigger_workflow": False})
            if not agent:
                results.append({"agent": name, "status": "missing"})
                continue
            insight = agent.run()
            results.append({"agent": name, "status": "ok", "insight": getattr(insight, "__dict__", insight)})
        except Exception as exc:
            logger.warning("agent run failed name=%s err=%s", name, exc)
            results.append({"agent": name, "status": "error", "error": str(exc)})
    return results


def _update_kg_for_event(event_row: dict[str, Any]) -> dict[str, int]:
    nodes = 0
    edges = 0
    payload = event_row.get("payload") or {}

    def _node(entity: str, table: str, ref_value: Any, properties: dict[str, Any] | None = None) -> int | None:
        nonlocal nodes
        node_id = kg_graph.ensure_node(node_type=entity, ref_table=table, ref_value=ref_value, properties=properties)
        if node_id:
            nodes += 1
        return node_id

    def _edge(src: int | None, dst: int | None, edge_type: str, properties: dict[str, Any] | None = None) -> None:
        nonlocal edges
        if kg_graph.ensure_edge(from_node=src, to_node=dst, edge_type=edge_type, properties=properties):
            edges += 1

    event_id = event_row.get("event_id")
    ev_node = _node(
        node_type="event",
        ref_table="event_ledger",
        ref_value=event_id,
        properties={
            "department": event_row.get("department"),
            "event_type": event_row.get("event_type"),
            "created_by": event_row.get("created_by"),
        },
    )

    created_by = event_row.get("created_by")
    if created_by:
        staff_node = _node("staff", "placeware_users", created_by, {"role": "actor"})
        _edge(staff_node, ev_node, "Performed")

    customer_id = event_row.get("linked_customer_id")
    if not customer_id:
        customer_id = payload.get("customer_id")
    if customer_id:
        cust_node = _node("customer", "customers", customer_id, {})
        _edge(cust_node, ev_node, "LinkedTo")

    supplier_id = event_row.get("linked_supplier_id")
    if not supplier_id:
        supplier_id = payload.get("supplier_id")
    if supplier_id:
        supp_node = _node("supplier", "suppliers", supplier_id, {})
        _edge(supp_node, ev_node, "LinkedTo")

    project_id = event_row.get("linked_project_id")
    if not project_id:
        project_id = payload.get("project_id")
    if project_id:
        proj_node = _node("project", "placeware_projects", project_id, {})
        _edge(proj_node, ev_node, "LinkedTo")

    opportunity_id = payload.get("opportunity_id") or event_row.get("linked_opportunity_id")
    if opportunity_id:
        opp_node = _node("opportunity", "opportunities", opportunity_id, {})
        _edge(opp_node, ev_node, "LinkedTo")

    delivery_id = payload.get("delivery_id") or payload.get("shipment_id")
    delivery_node = None
    if delivery_id:
        delivery_node = _node("delivery", "deliveries", delivery_id, {})
        _edge(delivery_node, ev_node, "LinkedTo")

    inventory_item = payload.get("inventory_item_id") or payload.get("item_id") or payload.get("sku")
    if inventory_item:
        inv_node = _node("inventory_item", "inventory_items", inventory_item, {"sku": payload.get("sku")})
        _edge(inv_node, ev_node, "LinkedTo")

    document_id = payload.get("document_id")
    if document_id:
        doc_node = _node("document", "documents", document_id, {})
        _edge(doc_node, ev_node, "LinkedTo")

    assigned_to = payload.get("assigned_to") or payload.get("assigned_rep")
    if assigned_to:
        assignee = _node("staff", "placeware_users", assigned_to, {"role": "assignee"})
        _edge(ev_node, assignee, "Assigned")

    if delivery_node and customer_id:
        customer_node = _node("customer", "customers", customer_id, {})
        _edge(delivery_node, customer_node, "Delivered")

    if payload.get("approval_required") or event_row.get("approval_status"):
        approval_ref = f"{event_id}:approval"
        approval_node = _node("approval", "workflow_jobs", approval_ref, {"status": event_row.get("approval_status") or "pending"})
        if str(event_row.get("approval_status") or "").lower() in {"approved", "accepted"}:
            _edge(approval_node, ev_node, "Approved")
        else:
            _edge(approval_node, ev_node, "Requested")

    delayed = False
    if payload.get("delay_minutes") or payload.get("delay_hours"):
        delayed = True
    if "delay" in str(event_row.get("event_type") or ""):
        delayed = True
    if delayed:
        anchor = delivery_node or ev_node
        _edge(anchor, ev_node, "Delayed")

    return {"nodes": nodes, "edges": edges}


def build_event_trace(event_id: str) -> dict[str, Any]:
    try:
        uuid.UUID(str(event_id))
    except Exception:
        return {
            "event": None,
            "workflow_jobs": [],
            "agent_reactions": [],
            "cache_updates": [],
            "kg": {"event_node": None, "nodes": [], "edges": []},
            "proof": {
                "eventledger_write": False,
                "workflow_action": False,
                "agent_reaction": False,
                "cache_update": False,
                "kg_update": False,
            },
        }

    event_rows = db.table("event_ledger").select("*").eq("event_id", event_id).limit(1).execute().data or []
    if not event_rows:
        return {
            "event": None,
            "workflow_jobs": [],
            "agent_reactions": [],
            "cache_updates": [],
            "kg": {"event_node": None, "nodes": [], "edges": []},
            "proof": {
                "eventledger_write": False,
                "workflow_action": False,
                "agent_reaction": False,
                "cache_update": False,
                "kg_update": False,
            },
        }

    event = event_rows[0]
    from src.workflow.workflow_jobs import engine as workflow_jobs_engine

    workflow_jobs = [job for job in workflow_jobs_engine.list_jobs() if str(job.get("event_id")) == str(event_id)]

    audit_rows = db.table(TABLE_AUDIT_LOGS).select("*").order("created_at", desc=True).limit(500).execute().data or []
    related_audit = [
        row
        for row in audit_rows
        if str((row.get("details") or {}).get("event_id") or "") == str(event_id)
    ]
    agent_reactions = [
        row
        for row in related_audit
        if row.get("event_type") in {"oeis_event_processed", "workflow_job_executed", "workflow_job_approved"}
    ]
    cache_updates = [
        row
        for row in related_audit
        if row.get("event_type") == "oeis_cache_invalidated"
    ]

    kg_snapshot = kg_graph.event_graph_snapshot(str(event_id))
    proof = {
        "eventledger_write": True,
        "workflow_action": len(workflow_jobs) > 0,
        "agent_reaction": len(agent_reactions) > 0,
        "cache_update": len(cache_updates) > 0,
        "kg_update": bool((kg_snapshot.get("nodes") or []) or (kg_snapshot.get("edges") or [])),
    }

    return {
        "event": event,
        "workflow_jobs": workflow_jobs,
        "agent_reactions": agent_reactions,
        "cache_updates": cache_updates,
        "kg": kg_snapshot,
        "proof": proof,
    }


async def process_operational_event(event_payload: dict[str, Any], actor_id: str | None = None) -> OeisResult:
    payload = dict(event_payload)
    payload["department"] = str(payload.get("department") or "").strip().lower()
    payload["event_type"] = str(payload.get("event_type") or "").strip().lower()

    if not payload.get("timestamp"):
        payload["timestamp"] = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    payload["created_by"] = payload.get("created_by") or actor_id
    payload.setdefault("status", "submitted")
    payload.setdefault("version", 1)

    schema = get_schema(payload["department"], payload["event_type"])
    schema_errors = validate_event_payload(schema, payload.get("payload") or {}) if schema else []
    payload["schema_errors"] = schema_errors if schema_errors else None

    version_hash = _compute_version_hash(payload)
    payload["version_hash"] = version_hash

    event_row = {
        "department": payload["department"],
        "event_type": payload["event_type"],
        "linked_project_id": payload.get("linked_project_id"),
        "linked_customer_id": payload.get("linked_customer_id"),
        "linked_supplier_id": payload.get("linked_supplier_id"),
        "payload": payload.get("payload") or {},
        "status": payload.get("status") or "submitted",
        "created_by": payload.get("created_by"),
        "approval_status": payload.get("approval_status"),
        "risk_score": payload.get("risk_score"),
        "version_hash": version_hash,
        "version": int(payload.get("version") or 1),
    }

    event_id = None
    try:
        inserted = db.table("event_ledger").insert(event_row).execute()
        rows = inserted.data or []
        if rows:
            event_id = str(rows[0].get("event_id"))
            event_row["event_id"] = event_id
    except Exception as exc:
        logger.warning("event_ledger insert failed; using local fallback err=%s", exc)
        fallback = dict(payload)
        fallback["event_id"] = version_hash
        _append_local_ledger(fallback)

    workflow_job_ids: list[str] = []
    triggers = _workflow_triggers_for_event(payload["department"], payload["event_type"], payload.get("payload") or {}, schema)
    for trigger in triggers:
        try:
            job_id = workflow_jobs_engine.enqueue_trigger(
                trigger=trigger,
                event_id=event_id or version_hash,
                payload=payload.get("payload") or {},
                department=payload["department"],
                event_type=payload["event_type"],
                escalation_role=(schema or {}).get("escalation_role") if isinstance(schema, dict) else None,
            )
            if job_id:
                workflow_job_ids.append(job_id)
        except Exception as exc:
            logger.warning("workflow trigger enqueue failed trigger=%s err=%s", trigger, exc)

    try:
        discovered = workflow_jobs_engine.discover_and_enqueue()
        if discovered > 0:
            workflow_job_ids.append(f"discovered:{discovered}")
    except Exception:
        pass

    agent_names = _agent_names_for_event(payload["department"], payload["event_type"])
    agent_runs = _run_agents(agent_names, actor_id=actor_id)

    invalidate_cache_tags(*_cache_tags_for_event(payload["department"], payload["event_type"]))
    try:
        audit_event(
            "oeis_cache_invalidated",
            {
                "event_id": event_id or version_hash,
                "tags": _cache_tags_for_event(payload["department"], payload["event_type"]),
            },
            actor_id=actor_id,
            event_class="operational_event",
            action="cache_invalidate",
            outcome="success",
            subject_type="event",
            subject_id=event_id or version_hash,
        )
    except Exception:
        pass

    kg_updates = _update_kg_for_event({**event_row, "event_id": event_id or version_hash})

    # Emit realtime notifications across shared channels
    channels = {
        "workflow_updates": {
            "event": "oeis_workflow_enqueued",
            "event_id": event_id or version_hash,
            "workflow_jobs": workflow_job_ids,
            "department": payload["department"],
            "event_type": payload["event_type"],
        },
        "alerts_updates": {
            "event": "oeis_event_ingested",
            "event_id": event_id or version_hash,
            "department": payload["department"],
            "event_type": payload["event_type"],
            "schema_valid": len(schema_errors) == 0,
        },
    }
    if payload["department"] in {"finance", "billing", "accounting"}:
        channels["finance_updates"] = {"event": "oeis_finance_event", "event_id": event_id or version_hash}
    if payload["department"] in {"inventory", "ops", "operations", "logistics"}:
        channels["inventory_updates"] = {"event": "oeis_inventory_event", "event_id": event_id or version_hash}
        channels["logistics_updates"] = {"event": "oeis_logistics_event", "event_id": event_id or version_hash}
    if payload["department"] in {"crm", "sales"}:
        channels["crm_updates"] = {"event": "oeis_crm_event", "event_id": event_id or version_hash}
    if payload["department"] in {"hr", "staff", "workforce"}:
        channels["staff_updates"] = {"event": "oeis_staff_event", "event_id": event_id or version_hash}

    for channel, frame in channels.items():
        try:
            await realtime_hub.broadcast(channel, frame)
        except Exception:
            pass

    try:
        audit_event(
            "oeis_event_processed",
            {
                "event_id": event_id or version_hash,
                "department": payload["department"],
                "event_type": payload["event_type"],
                "schema_valid": len(schema_errors) == 0,
                "workflow_jobs": workflow_job_ids,
                "agents": [r.get("agent") for r in agent_runs],
                "kg_updates": kg_updates,
            },
            actor_id=actor_id,
            event_class="operational_event",
            action="oeis_process",
            outcome="accepted",
            subject_type="event",
            subject_id=event_id or version_hash,
        )
    except Exception:
        pass

    return OeisResult(
        event_id=event_id,
        version_hash=version_hash,
        schema_valid=len(schema_errors) == 0,
        schema_errors=schema_errors,
        workflow_job_ids=workflow_job_ids,
        agent_runs=agent_runs,
        kg_updates=kg_updates,
    )
