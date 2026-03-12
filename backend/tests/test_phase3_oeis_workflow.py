from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from assertions import assert_status  # noqa: E402
from src.routers import operational_events, workflow_engine  # noqa: E402
from src.services.oeis import OeisResult  # noqa: E402


client = TestClient(app)


def test_events_ingest_returns_closed_loop_contract(monkeypatch):
    monkeypatch.setattr(
        operational_events,
        "verify_jwt",
        lambda _request: {"roles": ["staff"], "sub": "user-1"},
    )

    async def fake_process_operational_event(event_payload, actor_id=None):
        assert actor_id == "user-1"
        assert event_payload["department"] == "inventory"
        return OeisResult(
            event_id="evt-123",
            version_hash="hash-123",
            schema_valid=True,
            schema_errors=[],
            workflow_job_ids=["wf-1"],
            agent_runs=[{"agent": "inventory_intelligence", "status": "ok"}],
            kg_updates={"nodes": 2, "edges": 1},
        )

    monkeypatch.setattr(operational_events, "process_operational_event", fake_process_operational_event)

    payload = {
        "department": "inventory",
        "event_type": "stock_threshold_breach",
        "payload": {"sku": "SKU-1", "qty": 2, "threshold": 5},
    }
    response = client.post("/events", json=payload, headers={"Authorization": "Bearer dummy"})
    assert_status(response, 201)
    body = response.json()
    assert body["status"] == "accepted"
    assert body["event_id"] == "evt-123"
    assert body["version_hash"] == "hash-123"
    assert body["schema_valid"] is True
    assert body["workflow_jobs"] == ["wf-1"]
    assert body["kg_updates"] == {"nodes": 2, "edges": 1}


def test_events_ingest_requires_privileged_role(monkeypatch):
    monkeypatch.setattr(
        operational_events,
        "verify_jwt",
        lambda _request: {"roles": ["viewer"], "sub": "user-2"},
    )

    payload = {
        "department": "finance",
        "event_type": "credit_risk",
        "payload": {"customer_id": "c-1"},
    }
    response = client.post("/events", json=payload, headers={"Authorization": "Bearer dummy"})
    assert_status(response, 403)


def test_workflow_metrics_returns_bottleneck_snapshot(monkeypatch):
    monkeypatch.setattr(workflow_engine, "verify_jwt", lambda _request: {"roles": ["admin"]})
    monkeypatch.setattr(
        workflow_engine.engine,
        "bottleneck_metrics",
        lambda: {
            "total_jobs": 3,
            "waiting_jobs": 2,
            "overdue_waiting_jobs": 1,
            "by_department": {"inventory": 2},
            "by_trigger": {"inventory.create_replenishment": 2},
        },
    )

    response = client.get("/workflow/jobs/metrics", headers={"Authorization": "Bearer dummy"})
    assert_status(response, 200)
    body = response.json()
    assert body["total_jobs"] == 3
    assert body["overdue_waiting_jobs"] == 1


def test_workflow_escalation_requires_manager_role(monkeypatch):
    monkeypatch.setattr(workflow_engine, "verify_jwt", lambda _request: {"roles": ["staff"]})
    response = client.post("/workflow/jobs/escalate/run", headers={"Authorization": "Bearer dummy"})
    assert_status(response, 403)


def test_workflow_escalation_runs_for_management(monkeypatch):
    monkeypatch.setattr(workflow_engine, "verify_jwt", lambda _request: {"roles": ["management"]})
    monkeypatch.setattr(
        workflow_engine.engine,
        "run_escalation_pass",
        lambda: {
            "escalated": 2,
            "metrics": {
                "total_jobs": 5,
                "waiting_jobs": 3,
                "overdue_waiting_jobs": 2,
                "by_department": {"ops": 3},
                "by_trigger": {"event.ops.delay": 3},
            },
        },
    )

    response = client.post("/workflow/jobs/escalate/run", headers={"Authorization": "Bearer dummy"})
    assert_status(response, 200)
    body = response.json()
    assert body["escalated"] == 2
    assert body["metrics"]["overdue_waiting_jobs"] == 2