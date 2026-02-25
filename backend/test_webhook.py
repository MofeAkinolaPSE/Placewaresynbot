import os
import json
import hmac
import hashlib
from fastapi.testclient import TestClient

# Ensure webhook secret is set before importing the app
os.environ["WEBHOOK_SECRET"] = "test-secret"

from app import app
import src.db as db
from src.constants import TABLE_TRACKING

client = TestClient(app)

# Fake supabase query object
class FakeQuery:
    def __init__(self, table_name, rows=None):
        self.table_name = table_name
        self._rows = rows or []
    def select(self, *args, **kwargs):
        return self
    def eq(self, *args, **kwargs):
        return self
    def limit(self, *args, **kwargs):
        return self
    def order(self, *args, **kwargs):
        return self
    def execute(self):
        class Resp:
            def __init__(self, data):
                self.data = data
        return Resp(self._rows)
    def update(self, payload):
        # simulate update exec
        return self

class FakeSupabase:
    def __init__(self, tracking_exists=True):
        self.tracking_exists = tracking_exists
    def table(self, name):
        if name == TABLE_TRACKING:
            if self.tracking_exists:
                return FakeQuery(name, rows=[{"id": "00000000-0000-0000-0000-000000000001"}])
            return FakeQuery(name, rows=[])
        return FakeQuery(name, rows=[])


def sign_payload(secret: str, payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode(), serialized, hashlib.sha256).hexdigest()


def test_webhook_valid_signature_and_idempotency(monkeypatch):
    secret = os.environ["WEBHOOK_SECRET"]
    payload = {
        "tracking_id": "00000000-0000-0000-0000-000000000001",
        "status": "packed",
        "eta": "2026-02-25T12:00:00Z",
        "idempotency_key": "test-key-1",
    }
    sig = sign_payload(secret, payload)
    payload_with_sig = dict(payload)
    payload_with_sig["signature"] = sig

    # Monkeypatch DB helpers and supabase
    monkeypatch.setattr(db, "is_webhook_idempotent", lambda k: False)
    monkeypatch.setattr(db, "record_webhook_idempotency", lambda *a, **k: True)
    monkeypatch.setattr(db, "supabase", FakeSupabase(tracking_exists=True))

    r = client.post("/webhook/tracking", json=payload_with_sig)
    assert r.status_code == 200
    assert r.json()["status"] == "updated"

    # Now simulate a duplicate by making is_webhook_idempotent return True
    monkeypatch.setattr(db, "is_webhook_idempotent", lambda k: True)
    r2 = client.post("/webhook/tracking", json=payload_with_sig)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


def test_webhook_invalid_signature(monkeypatch):
    payload = {
        "tracking_id": "00000000-0000-0000-0000-000000000002",
        "status": "packed",
        "eta": "2026-02-25T12:00:00Z",
        "idempotency_key": "test-key-2",
        "signature": "bad-signature",
    }
    # Ensure supabase doesn't get called by making tracking exist
    monkeypatch.setattr(db, "supabase", FakeSupabase(tracking_exists=True))
    r = client.post("/webhook/tracking", json=payload)
    assert r.status_code == 401

