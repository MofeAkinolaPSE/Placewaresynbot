from fastapi.testclient import TestClient
import sys
from pathlib import Path
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from src.constants import JWT_SECRET, HIGH_IMPACT_COST_THRESHOLD  # noqa: E402
from tests.assertions import assert_status  # noqa: E402

client = TestClient(app)


def make_admin_token():
    return jwt.encode({"roles": ["admin"], "sub": "admin-1"}, JWT_SECRET, algorithm="HS256")


def test_change_decision_transition_guard(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr("app.get_change_request", lambda _cid: {"id": "c-1", "status": "proposed", "impact_cost": 0, "impact_schedule_days": 0, "impact_scope": "minor"})

    r = client.post(
        "/controls/change/c-1/decision",
        json={"status": "approved", "approval_note": "skip review"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 409)
    assert "Transition not allowed" in r.json()["detail"]


def test_change_decision_requires_reason_for_high_impact(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr(
        "app.get_change_request",
        lambda _cid: {
            "id": "c-2",
            "status": "under_review",
            "impact_cost": HIGH_IMPACT_COST_THRESHOLD,
            "impact_schedule_days": 0,
            "impact_scope": "minor",
        },
    )

    r = client.post(
        "/controls/change/c-2/decision",
        json={"status": "approved", "approval_note": "approve"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 400)
    assert "approval_reason" in r.json()["detail"]


def test_change_decision_accepts_high_impact_with_reason(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr(
        "app.get_change_request",
        lambda _cid: {
            "id": "c-3",
            "status": "under_review",
            "impact_cost": HIGH_IMPACT_COST_THRESHOLD,
            "impact_schedule_days": 0,
            "impact_scope": "minor",
        },
    )
    monkeypatch.setattr(
        "app.decide_change_request",
        lambda **kwargs: {
            "id": kwargs["change_id"],
            "status": kwargs["status"],
            "approval_reason": kwargs["approval_reason"],
        },
    )
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/controls/change/c-3/decision",
        json={
            "status": "approved",
            "approval_note": "approved with controls",
            "approval_reason": "regulatory",
            "attestation_text": "I attest this project change decision is authorized and reviewed.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 200)
    assert r.json()["status"] == "approved"


def test_create_risk_requires_mitigation_for_elevated_score(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/controls/risk",
        json={
            "project_id": "p-1",
            "title": "Supplier disruption",
            "probability": 5,
            "impact": 3,
            "status": "open",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 400)
    assert "mitigation_plan" in r.json()["detail"]


def test_create_risk_requires_owner_for_high_score(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/controls/risk",
        json={
            "project_id": "p-1",
            "title": "Regulatory blocking risk",
            "probability": 5,
            "impact": 4,
            "status": "open",
            "mitigation_plan": "Daily regulator check-ins",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 400)
    assert "owner_id" in r.json()["detail"]


def test_scope_status_transition_guard_audits_policy(monkeypatch):
    token = make_admin_token()
    captured = {}

    monkeypatch.setattr("app.get_scope_item", lambda _id: {"id": _id, "status": "done"})

    def _audit(event_type, details, **kwargs):
        captured["event_type"] = event_type
        captured["details"] = details
        captured["kwargs"] = kwargs

    monkeypatch.setattr("app.audit_event", _audit)

    r = client.post(
        "/controls/scope/s-1/status",
        json={"status": "in_progress", "reason_code": "reopen"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert_status(r, 409)
    assert captured["event_type"] == "controls_transition_denied"
    assert captured["details"]["policy_code"] == "scope_transition_not_allowed"
    assert captured["details"]["rejection_reason"]


def test_cost_status_transition_success(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr("app.get_cost_item", lambda _id: {"id": _id, "status": "approved"})
    monkeypatch.setattr("app.update_cost_item_status", lambda **kwargs: {"id": kwargs["cost_item_id"], "status": kwargs["status"]})
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/controls/cost/cost-1/status",
        json={"status": "committed", "reason_code": "po_issued"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert_status(r, 200)
    assert r.json()["status"] == "committed"


def test_risk_close_requires_mitigation_and_owner(monkeypatch):
    token = make_admin_token()
    captured = []

    monkeypatch.setattr(
        "app.get_risk_item",
        lambda _id: {
            "id": _id,
            "status": "mitigating",
            "probability": 5,
            "impact": 4,
            "mitigation_plan": None,
            "owner_id": None,
        },
    )

    def _audit(event_type, details, **kwargs):
        captured.append({"event_type": event_type, "details": details, "kwargs": kwargs})

    monkeypatch.setattr("app.audit_event", _audit)

    r = client.post(
        "/controls/risk/r-1/status",
        json={"status": "closed", "reason_code": "accepted"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert_status(r, 400)
    assert "mitigation_plan" in r.json()["detail"]
    assert captured[0]["event_type"] == "controls_transition_denied"
    assert captured[0]["details"]["policy_code"] == "risk_close_requires_mitigation"


def test_controls_rollup_endpoint(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.get_controls_rollup",
        lambda project_id=None: {
            "project_id": project_id,
            "scope": {"status_counts": {"planned": 2}, "total": 2},
            "cost": {"status_counts": {"approved": 1}, "total": 1},
            "risk": {"status_counts": {"open": 1}, "total": 1, "high_risk_open_count": 1},
            "change": {"status_counts": {"under_review": 1}, "total": 1, "pending_approvals": 1},
        },
    )

    r = client.get("/controls/rollup?project_id=p-9", headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 200)
    j = r.json()["data"]
    assert j["project_id"] == "p-9"
    assert j["risk"]["high_risk_open_count"] == 1


def test_controls_audit_export_csv(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "created_at": "2026-02-13T00:00:00Z",
                "event_type": "controls_transition_denied",
                "event_class": "project_controls",
                "action": "status_transition",
                "outcome": "denied",
                "reason_code": "scope_transition_not_allowed",
                "actor_id": "admin-1",
                "subject_type": "scope_item",
                "subject_id": "s-1",
                "trace_id": "t-1",
                "details": {
                    "policy_code": "scope_transition_not_allowed",
                    "rejection_reason": "Requested scope status transition violates policy graph",
                },
            }
        ],
    )

    r = client.get(
        "/controls/audit/export?format=csv&subject_type=scope_item&limit=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 200)
    assert "text/csv" in (r.headers.get("content-type") or "")
    body = r.text
    assert "policy_code" in body
    assert "scope_transition_not_allowed" in body


def test_controls_audit_export_invalid_format(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.list_audit_logs_filtered", lambda **kwargs: [])
    r = client.get("/controls/audit/export?format=xml", headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 400)


def test_controls_audit_export_persists_signed_metadata(monkeypatch):
    token = make_admin_token()
    captured = {}

    monkeypatch.setattr("app.list_audit_logs_filtered", lambda **kwargs: [])

    def _audit(event_type, details, **kwargs):
        captured["event_type"] = event_type
        captured["details"] = details
        captured["kwargs"] = kwargs

    monkeypatch.setattr("app.audit_event", _audit)

    r = client.get(
        "/controls/audit/export?format=json&subject_type=change_request&limit=50",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert_status(r, 200)
    assert captured["event_type"] == "controls_audit_exported"
    assert captured["details"]["exported_by"] == "admin-1"
    assert captured["details"]["exported_at"]
    assert captured["details"]["filter_hash"]
    assert captured["kwargs"]["subject_type"] == "audit_export"
    assert captured["kwargs"]["reason_code"] == "compliance_export"
    assert captured["kwargs"]["signature_hash_ref"]
