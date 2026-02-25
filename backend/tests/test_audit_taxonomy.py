import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import db as db_module  # noqa: E402


def test_derive_audit_taxonomy_auth_failure():
    details = {"reason": "bad_password", "email": "user@example.com"}
    out = db_module._derive_audit_taxonomy("auth_login_failed", details)
    assert out["event_class"] == "security"
    assert out["outcome"] == "failed"
    assert out["reason_code"] == "bad_password"


def test_derive_audit_taxonomy_user_subject_resolution():
    details = {"admin": "admin-1", "target_user_id": "user-22"}
    out = db_module._derive_audit_taxonomy("user_status_changed", details)
    assert out["event_class"] == "identity"
    assert out["actor_id"] == "admin-1"
    assert out["subject_type"] == "user"
    assert out["subject_id"] == "user-22"


def test_audit_event_inserts_taxonomy_payload(monkeypatch):
    captured = {}

    class FakeExec:
        def execute(self):
            return type("Resp", (), {"data": [{"ok": True}]})()

    class FakeTable:
        def insert(self, payload):
            captured["payload"] = payload
            return FakeExec()

    class FakeSupabase:
        def table(self, _name):
            return FakeTable()

    monkeypatch.setattr(db_module, "supabase", FakeSupabase())
    db_module.audit_event(
        "auth_refresh_failed",
        {"reason": "expired", "user_id": "u-1"},
        trace_id="trace-xyz",
    )
    payload = captured["payload"]
    assert payload["event_type"] == "auth_refresh_failed"
    assert payload["event_class"] == "security"
    assert payload["outcome"] == "failed"
    assert payload["reason_code"] == "expired"
    assert payload["actor_id"] == "u-1"
    assert payload["trace_id"] == "trace-xyz"


def test_compute_signature_hash_ref_is_deterministic():
    details = {"intent_id": "i-1", "approved": True}
    h1 = db_module._compute_signature_hash_ref(
        event_type="intent_approval",
        actor_id="admin-1",
        subject_type="intent",
        subject_id="i-1",
        approval_reason="finance_threshold_override",
        attestation_text="I attest this approval is authorized.",
        details=details,
    )
    h2 = db_module._compute_signature_hash_ref(
        event_type="intent_approval",
        actor_id="admin-1",
        subject_type="intent",
        subject_id="i-1",
        approval_reason="finance_threshold_override",
        attestation_text="I attest this approval is authorized.",
        details=details,
    )
    assert h1 == h2
    assert len(h1) == 64


def test_audit_event_includes_esignature_fields(monkeypatch):
    captured = {}

    class FakeExec:
        def execute(self):
            return type("Resp", (), {"data": [{"ok": True}]})()

    class FakeTable:
        def insert(self, payload):
            captured["payload"] = payload
            return FakeExec()

    class FakeSupabase:
        def table(self, _name):
            return FakeTable()

    monkeypatch.setattr(db_module, "supabase", FakeSupabase())
    db_module.audit_event(
        "intent_approval",
        {"intent_id": "intent-9", "approved": True},
        actor_id="admin-9",
        subject_type="intent",
        subject_id="intent-9",
        approval_reason="manual_override",
        attestation_text="I attest this workflow approval decision is authorized and reviewed.",
    )
    payload = captured["payload"]
    assert payload["approval_reason"] == "manual_override"
    assert payload["attestation_text"]
    assert payload["signature_hash_ref"]
