"""
test_sync_guarantees.py — Proves the no-loss / no-duplicate guarantees.

These are the tests that matter. Each maps to a requirement:

    "Never duplicate a sync"        -> test_dedupe_*
    "Never silently drop one"       -> test_no_loss_*
    "Recovery after interruption"   -> test_crash_*
    "Retry logic"                   -> test_retry_*

Runs entirely against fakes — no Sage, no Windows, no network — so it is
runnable on any dev machine and in CI.

    python -m pytest tests/ -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Config validation runs at import; give it a valid key before importing.
os.environ.setdefault("BRIDGE_API_KEY", "test-key-that-is-long-enough-1234")
os.environ.setdefault("SAGE_MOCK", "true")

import events as ev                      # noqa: E402
from outbox import FAILED, PENDING, SENT, Outbox  # noqa: E402


@pytest.fixture()
def ob(tmp_path):
    """A fresh outbox backed by a real on-disk SQLite file."""
    return Outbox(str(tmp_path / "test_outbox.db"))


def _event(eid: str, sage_id: str = "1"):
    return {
        "event_id": eid,
        "entity_type": "invoice",
        "sage_id": sage_id,
        "payload": {"event_id": eid, "data": {"sage_id": sage_id}},
    }


# ── Deterministic identity ───────────────────────────────────────────────────

def test_event_id_is_deterministic():
    """Same invoice, same content -> same ID. This is what enables dedupe."""
    rec = {"sage_id": "1001", "total": 500.0, "lines": [{"item": "A", "qty": 2}]}
    assert ev.make_event_id("invoice", "1001", rec) == \
           ev.make_event_id("invoice", "1001", rec)


def test_event_id_changes_when_content_changes():
    """An edited invoice must produce a NEW id or the edit never propagates."""
    a = {"sage_id": "1001", "total": 500.0}
    b = {"sage_id": "1001", "total": 750.0}
    assert ev.make_event_id("invoice", "1001", a) != \
           ev.make_event_id("invoice", "1001", b)


def test_event_id_ignores_volatile_fields():
    """extracted_at changes on every read; it must not look like an edit."""
    a = {"sage_id": "1", "total": 5.0, "extracted_at": "2026-01-01T00:00:00Z"}
    b = {"sage_id": "1", "total": 5.0, "extracted_at": "2026-06-01T12:34:56Z"}
    assert ev.make_event_id("invoice", "1", a) == ev.make_event_id("invoice", "1", b)


# ── No duplicates ────────────────────────────────────────────────────────────

def test_dedupe_reenqueue_is_noop(ob):
    """Re-enqueuing the same event_id must not create a second row."""
    assert ob.enqueue_batch([_event("e1")]) == 1
    assert ob.enqueue_batch([_event("e1")]) == 0
    assert ob.stats()["pending"] == 1


def test_dedupe_rescan_after_crash_produces_same_ids(ob):
    """
    A rescan after a crash regenerates IDs that were already delivered, so the
    receiver deduplicates them instead of double-applying.
    """
    rec = {"sage_id": "2001", "total": 100.0}
    first = ev.make_event_id("invoice", "2001", rec)
    ob.enqueue_batch([{"event_id": first, "entity_type": "invoice",
                       "sage_id": "2001", "payload": {}}])
    ob.mark_sent(first)
    # Simulate a rescan of the same unchanged row.
    second = ev.make_event_id("invoice", "2001", rec)
    assert second == first
    assert ob.enqueue_batch([{"event_id": second, "entity_type": "invoice",
                              "sage_id": "2001", "payload": {}}]) == 0


# ── No silent loss ───────────────────────────────────────────────────────────

def test_no_loss_watermark_and_events_are_atomic(ob):
    """The watermark must never advance past events that were not stored."""
    ob.enqueue_batch([_event("e1", "1"), _event("e2", "2")],
                     watermark_name="cursor", watermark_value="2")
    assert ob.get_watermark("cursor") == "2"
    assert ob.stats()["pending"] == 2


def test_no_loss_failed_enqueue_leaves_watermark_untouched(ob):
    """
    If the batch cannot be written, the watermark must not move — otherwise the
    next scan starts past invoices that were never queued.
    """
    ob.set_watermark("cursor", "5")
    bad = [{"event_id": "ok", "entity_type": "invoice", "sage_id": "6",
            "payload": {}},
           {"entity_type": "invoice"}]          # missing event_id -> KeyError
    with pytest.raises(Exception):
        ob.enqueue_batch(bad, watermark_name="cursor", watermark_value="9")
    assert ob.get_watermark("cursor") == "5", "watermark advanced despite failure"
    assert ob.stats()["pending"] == 0, "partial batch was committed"


def test_no_loss_exhausted_retries_are_retained_not_deleted(ob):
    """
    'Never SILENTLY drop' — an event that exhausts retries stays on disk,
    visibly failed, and is replayable. The original discarded it entirely.
    """
    ob.enqueue_batch([_event("e1")])
    ob.mark_failed("e1", "synbot unreachable")
    assert ob.stats()["failed"] == 1
    assert ob.requeue_failed() == 1
    assert ob.stats()["pending"] == 1


def test_no_loss_purge_never_removes_pending_or_failed(ob):
    """Housekeeping must not be able to delete undelivered work."""
    ob.enqueue_batch([_event("p1"), _event("f1"), _event("s1")])
    ob.mark_failed("f1", "err")
    ob.mark_sent("s1")
    # Backdate the sent event so it is purge-eligible.
    ob._conn().execute(
        "UPDATE outbox SET sent_at=? WHERE event_id=?", (time.time() - 99 * 86400, "s1")
    )
    ob.purge_sent(older_than_days=30)
    stats = ob.stats()
    assert stats["pending"] == 1 and stats["failed"] == 1
    assert stats["sent"] == 0


# ── Crash recovery ───────────────────────────────────────────────────────────

def test_crash_pending_events_survive_process_restart(tmp_path):
    """
    The core recovery guarantee: events written before a crash are still there
    afterwards. The original held state in RAM and lost everything on restart.
    """
    db = str(tmp_path / "crash.db")
    ob1 = Outbox(db)
    ob1.enqueue_batch([_event("e1"), _event("e2")],
                      watermark_name="cursor", watermark_value="2")
    ob1.close()                                   # simulate abrupt termination

    ob2 = Outbox(db)                              # fresh process
    assert ob2.stats()["pending"] == 2
    assert ob2.get_watermark("cursor") == "2"
    assert len(ob2.claim_due()) == 2


def test_crash_between_enqueue_and_send_redelivers(tmp_path):
    """An event queued but not yet delivered is retried, not lost."""
    db = str(tmp_path / "midflight.db")
    ob1 = Outbox(db)
    ob1.enqueue_batch([_event("inflight")])
    ob1.close()                                   # crash before mark_sent

    ob2 = Outbox(db)
    due = ob2.claim_due()
    assert [d["event_id"] for d in due] == ["inflight"]


# ── Retry behaviour ──────────────────────────────────────────────────────────

def test_retry_backoff_gates_next_attempt(ob):
    """A retried event must not be re-claimed until its backoff elapses."""
    ob.enqueue_batch([_event("e1")])
    ob.mark_retry("e1", "connection refused", delay_seconds=60)
    assert ob.claim_due() == []


def test_retry_becomes_due_after_backoff(ob):
    ob.enqueue_batch([_event("e1")])
    ob.mark_retry("e1", "connection refused", delay_seconds=-1)   # already due
    assert len(ob.claim_due()) == 1


def test_retry_survives_a_long_outage(ob):
    """
    The configured retry window must span a real overnight outage, not the ~6
    seconds the original allowed before discarding the event.

    Reads the ACTUAL configured defaults rather than hardcoded numbers, so
    shrinking them in config.py fails here instead of quietly weakening the
    no-loss guarantee.
    """
    from config import get_settings
    from sender import _backoff_delay

    s = get_settings()
    total = sum(
        _backoff_delay(i, s.RETRY_BASE_SECONDS, s.RETRY_MAX_DELAY_SECONDS)
        for i in range(s.RETRY_MAX_ATTEMPTS)
    )
    assert total > 8 * 3600, (
        "retry window is only {:.1f}h — too short to survive an overnight "
        "outage".format(total / 3600)
    )


def test_corrupt_payload_is_parked_not_crashed(ob):
    """A bad row must not take down the sender loop for every other event."""
    ob.enqueue_batch([_event("good")])
    ob._conn().execute(
        "INSERT INTO outbox (event_id, entity_type, payload, status, attempts, "
        "next_attempt, created_at) VALUES (?,?,?,?,0,0,?)",
        ("bad", "invoice", "{not json", PENDING, time.time()),
    )
    due = ob.claim_due()
    assert [d["event_id"] for d in due] == ["good"]
    assert ob.stats()["failed"] == 1


# ── Ordering / scan safety ───────────────────────────────────────────────────

def test_claim_due_returns_oldest_first(ob):
    for i in range(5):
        ob.enqueue_batch([_event("e{}".format(i))])
        time.sleep(0.01)
    ids = [d["event_id"] for d in ob.claim_due()]
    assert ids == sorted(ids, key=lambda x: int(x[1:]))
