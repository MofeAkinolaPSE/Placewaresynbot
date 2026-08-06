"""
test_sage_webhook_durability.py — Proves the receiving end honours the bridge's
                                  no-loss contract.

The bridge guarantees at-least-once delivery: it retries until it gets a 2xx,
and only then marks the event delivered and eventually purges it. That contract
puts a hard requirement on this end — **a 2xx must mean the record was actually
applied.**

It previously did not. The handler queued the apply as a FastAPI
``BackgroundTask``, which runs *after* the response is sent, and recorded the
``event_id`` as applied before the work happened:

    queue apply → record event_id → return 200 → (apply runs, maybe fails)

A failure then had nowhere to surface. The bridge had its 200, marked the event
sent, and would purge it; and the recorded ``event_id`` meant an operator replay
came back 409 "already applied". The invoice was unrecoverable through either
path — defeating the entire point of the durable outbox upstream.

These tests pin the corrected ordering. They are deliberately about the failure
path: the success path was never the problem.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from src.routers import sage_live  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def _invoice_envelope(event_id: str = "invoice-test-0001"):
    return {
        "source": "sage_bridge",
        "schema_version": 2,
        "event": "record_upserted",
        "event_id": event_id,
        "entity_type": "invoice",
        "sage_id": "9001",
        "data": {
            "sage_id": "9001",
            "customer_id": "CUST1",
            "date": "2026-01-15",
            "lines": [],
            "payment": {"total_amount": 100.0, "amount_paid": 0.0,
                        "amount_due": 100.0, "payment_status": "unpaid"},
            "_meta": {"source": "sdk", "completeness": "full"},
        },
    }


@pytest.fixture()
def clean_gate(monkeypatch):
    """No event is pre-applied, and record the IDs we mark as applied."""
    marked = []
    monkeypatch.setattr(sage_live, "_event_already_applied", lambda _eid: False)
    monkeypatch.setattr(
        sage_live, "_mark_event_applied",
        lambda eid, et, ev: marked.append(eid),
    )
    monkeypatch.setattr(sage_live, "WEBHOOK_SECRET", "")
    return marked


def test_failed_apply_returns_5xx_so_the_bridge_retries(clean_gate, monkeypatch):
    """
    The single most important property here.

    If the apply fails, the bridge must NOT receive a 2xx — otherwise it marks
    the event delivered and the invoice is gone.
    """
    async def boom(_envelope):
        raise RuntimeError("supabase unavailable")

    monkeypatch.setattr(
        "src.services.sage_sync_engine.apply_record_event", boom, raising=False
    )

    resp = client.post("/sage/webhook", json=_invoice_envelope())

    assert resp.status_code >= 500, (
        "A failed apply returned {} — the bridge would treat that as success "
        "and drop the invoice.".format(resp.status_code)
    )


def test_failed_apply_does_not_record_the_event_id(clean_gate, monkeypatch):
    """
    A failed apply must leave the event_id unrecorded.

    Recording it would make the bridge's retry come back 409 "already applied",
    closing the last recovery path for a record that was never written.
    """
    async def boom(_envelope):
        raise RuntimeError("supabase unavailable")

    monkeypatch.setattr(
        "src.services.sage_sync_engine.apply_record_event", boom, raising=False
    )

    client.post("/sage/webhook", json=_invoice_envelope())

    assert clean_gate == [], (
        "event_id was recorded despite the apply failing — a retry would now be "
        "409'd as a duplicate and the invoice lost."
    )


def test_apply_runs_before_the_response_is_sent(clean_gate, monkeypatch):
    """
    The apply must be awaited, not deferred to a background task.

    If it were still a BackgroundTask this flag would be unset at assert time,
    because background tasks run after the response.
    """
    applied = []

    async def record(envelope):
        applied.append(envelope.get("sage_id"))

    monkeypatch.setattr(
        "src.services.sage_sync_engine.apply_record_event", record, raising=False
    )

    resp = client.post("/sage/webhook", json=_invoice_envelope())

    assert resp.status_code == 200
    assert applied == ["9001"], "apply did not run before the response was sent"


def test_successful_apply_records_the_event_id(clean_gate, monkeypatch):
    """The dedupe gate must still close on success, or retries double-apply."""
    async def ok(_envelope):
        return None

    monkeypatch.setattr(
        "src.services.sage_sync_engine.apply_record_event", ok, raising=False
    )

    resp = client.post("/sage/webhook", json=_invoice_envelope("invoice-test-0002"))

    assert resp.status_code == 200
    assert clean_gate == ["invoice-test-0002"]


def test_duplicate_event_returns_409(monkeypatch):
    """
    An already-applied event must 409 so the bridge stops retrying.

    This is the "never duplicate" half — at-least-once delivery becomes
    at-most-once application.
    """
    monkeypatch.setattr(sage_live, "_event_already_applied", lambda _eid: True)
    monkeypatch.setattr(sage_live, "WEBHOOK_SECRET", "")

    resp = client.post("/sage/webhook", json=_invoice_envelope())

    assert resp.status_code == 409
    assert resp.json()["duplicate"] is True


def test_failed_delete_returns_5xx(clean_gate, monkeypatch):
    """
    Deletions carry the same contract as upserts.

    A swallowed failure here leaves a voided invoice live in SynBot, inflating
    AR with nothing to replay from.
    """
    async def boom(_envelope):
        raise RuntimeError("supabase unavailable")

    monkeypatch.setattr(
        "src.services.sage_sync_engine.apply_delete_event", boom, raising=False
    )

    envelope = _invoice_envelope("del-invoice-test-0003")
    envelope["event"] = "record_deleted"
    envelope["data"] = {"sage_id": "9001", "deleted": True}

    resp = client.post("/sage/webhook", json=envelope)

    assert resp.status_code >= 500
    assert clean_gate == []
