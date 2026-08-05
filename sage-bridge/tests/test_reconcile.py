"""
test_reconcile.py — Proves void/delete detection and, more importantly, that
                    it refuses to emit deletes when it cannot trust its input.

The forward scan walks a watermark upward and structurally cannot see a deleted
row, so an invoice voided in Sage used to stay active in SynBot forever. The
reconciliation sweep closes that gap.

But a sweep that emits deletes is destructive downstream, and the input it
depends on — a full enumeration of ARTRANS over a flaky ODBC link on old
hardware — is exactly the kind of thing that fails halfway. Most of the tests
below are therefore about the sweep declining to act:

    test_reconcile_detects_*     -> the gap is actually closed
    test_reconcile_aborts_*      -> a bad read never looks like mass deletion

Runs against fakes; no Sage, no Windows, no network.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BRIDGE_API_KEY", "test-key-that-is-long-enough-1234")
os.environ.setdefault("SAGE_MOCK", "true")

import events as ev                       # noqa: E402
import outbox as outbox_mod               # noqa: E402
import watcher as watcher_mod             # noqa: E402
from outbox import PENDING, Outbox        # noqa: E402


@pytest.fixture()
def ob(tmp_path, monkeypatch):
    """A fresh outbox wired in as the process-wide singleton."""
    box = Outbox(str(tmp_path / "reconcile.db"))
    monkeypatch.setattr(outbox_mod, "_outbox", box)
    monkeypatch.setattr(watcher_mod, "get_outbox", lambda: box)
    return box


@pytest.fixture()
def w(monkeypatch):
    """A watcher with the sender nudge stubbed out."""
    monkeypatch.setattr(watcher_mod, "nudge_sender", lambda: None)
    return watcher_mod.SageDataWatcher()


def _fake_scan(pages):
    """
    Build a scan_after replacement returning ``pages`` keyed by cursor.

    ``pages`` is a list of row-lists delivered in order; an entry that is an
    Exception instance is raised instead, simulating a mid-enumeration failure.
    """
    state = {"i": 0}

    def scan_after(table_key, key_column, after_value, limit=200):
        i = state["i"]
        state["i"] += 1
        if i >= len(pages):
            return []
        page = pages[i]
        if isinstance(page, Exception):
            raise page
        return page

    return scan_after


def _rows(*ids):
    return [{"transno": str(i)} for i in ids]


# ── The gap is actually closed ───────────────────────────────────────────────

#: A single deletion out of this many stays under the 10% bulk-delete ceiling,
#: which is what a realistic void looks like. Tests that deliberately trip the
#: ceiling use a small set instead.
_KNOWN = [str(i) for i in range(1, 21)]


def test_reconcile_detects_a_deleted_invoice(ob, w, monkeypatch):
    """An invoice we know about that Sage no longer returns -> delete event."""
    ob.record_seen("invoice", _KNOWN)
    # Sage now returns everything except invoice 2, which was voided.
    survivors = [i for i in _KNOWN if i != "2"]
    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([_rows(*survivors)]))

    result = w.reconcile()

    assert result["status"] == "ok"
    assert result["deleted"] == 1

    pending = ob.claim_due(limit=10)
    assert len(pending) == 1
    assert pending[0]["payload"]["event"] == "record_deleted"
    assert pending[0]["payload"]["sage_id"] == "2"


def test_deleted_invoice_is_tombstoned_and_not_re_emitted(ob, w, monkeypatch):
    """A second sweep must not fire a second delete for the same invoice."""
    ob.record_seen("invoice", _KNOWN)
    survivors = [i for i in _KNOWN if i != "2"]

    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([_rows(*survivors)]))
    assert w.reconcile()["deleted"] == 1

    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([_rows(*survivors)]))
    assert w.reconcile()["deleted"] == 0
    assert "2" not in ob.live_ids("invoice")


def test_delete_event_id_is_deterministic():
    """
    Redelivery must dedupe rather than fire a second delete.

    Unlike an upsert the ID carries no content fingerprint — a deletion has no
    content — so it must be stable on (entity_type, sage_id) alone.
    """
    a = ev.build_delete_envelope("invoice", "1001")
    b = ev.build_delete_envelope("invoice", "1001")
    assert a["event_id"] == b["event_id"]
    assert a["event_id"] != ev.build_delete_envelope("invoice", "1002")["event_id"]


def test_reappearing_invoice_clears_its_tombstone(ob, w, monkeypatch):
    """An un-voided / restored invoice must be tracked as live again."""
    ob.record_seen("invoice", _KNOWN)
    survivors = [i for i in _KNOWN if i != "2"]
    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([_rows(*survivors)]))
    w.reconcile()
    assert "2" not in ob.live_ids("invoice")

    ob.record_seen("invoice", ["2"])
    assert "2" in ob.live_ids("invoice")


# ── A bad read never looks like mass deletion ────────────────────────────────

def test_reconcile_aborts_on_enumeration_failure(ob, w, monkeypatch):
    """
    A mid-enumeration ODBC error must emit NOTHING.

    A half-read table is indistinguishable from "everything after this point was
    deleted". Emitting those deletes would void live invoices downstream.
    """
    ob.record_seen("invoice", [str(i) for i in range(1, 21)])
    monkeypatch.setattr(
        watcher_mod.odbc, "scan_after",
        _fake_scan([_rows(1, 2, 3), RuntimeError("ODBC link dropped")]),
    )
    # Force multi-page: page size must be <= the first page's length.
    monkeypatch.setattr(
        watcher_mod, "get_settings",
        _settings_with(WATCHER_SCAN_PAGE_SIZE=3),
    )

    result = w.reconcile()

    assert result["status"] == "aborted"
    assert result["deleted"] == 0
    assert ob.claim_due(limit=10) == []


def test_reconcile_aborts_when_sage_returns_nothing(ob, w, monkeypatch):
    """
    Zero rows while we know of many is a connectivity fault, not deletion.

    Without this guard, a DSN that authenticates but returns an empty result set
    would void the customer's entire invoice history in one sweep.
    """
    ob.record_seen("invoice", ["1", "2", "3"])
    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([[]]))

    result = w.reconcile()

    assert result["status"] == "aborted"
    assert result["deleted"] == 0
    assert ob.claim_due(limit=10) == []


def test_reconcile_aborts_above_bulk_delete_ceiling(ob, w, monkeypatch):
    """
    A mass disappearance is a swapped company file, not real voids.

    Real voids trickle in ones and twos. Losing most of the table at once means
    something structural changed, and a human should look before SynBot acts.
    """
    ob.record_seen("invoice", [str(i) for i in range(1, 11)])
    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([_rows(1)]))

    result = w.reconcile()

    assert result["status"] == "aborted"
    assert result["reason"] == "bulk delete ceiling exceeded"
    assert result["would_delete"] == 9
    assert ob.claim_due(limit=10) == []


def test_ceiling_can_be_raised_deliberately(ob, w, monkeypatch):
    """The ceiling is a safety catch, not a hard cap — operators can override."""
    ob.record_seen("invoice", [str(i) for i in range(1, 11)])
    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([_rows(1)]))
    monkeypatch.setattr(
        watcher_mod, "get_settings",
        _settings_with(RECONCILE_MAX_DELETE_RATIO=0.95),
    )

    result = w.reconcile()

    assert result["status"] == "ok"
    assert result["deleted"] == 9


def test_reconcile_paginates_in_database_order_not_string_order(ob, w, monkeypatch):
    """
    Multi-page enumeration must follow the DB's ordering, not Python's.

    scan_after emits ORDER BY <key>, so the page's last row is the true
    high-water mark. Using max() applies *string* ordering on top, which
    disagrees with a numeric key as soon as IDs cross a digit boundary —
    max(["9","10"]) is "9". The cursor then goes backwards, the next page
    repeats, enumeration halts early, and every invoice past the first page
    looks deleted.
    """
    known = [str(i) for i in range(1, 31)]
    ob.record_seen("invoice", known)

    seen_cursors = []

    def scan_after(table_key, key_column, after_value, limit=200):
        # Numeric ordering, as a real database with an integer key does.
        seen_cursors.append(after_value)
        start = 0 if after_value is None else int(after_value)
        remaining = [i for i in range(1, 31) if i > start]
        return [{"transno": str(i)} for i in remaining[:limit]]

    monkeypatch.setattr(watcher_mod.odbc, "scan_after", scan_after)
    monkeypatch.setattr(
        watcher_mod, "get_settings", _settings_with(WATCHER_SCAN_PAGE_SIZE=10),
    )

    result = w.reconcile()

    # All 30 present, so nothing is missing and nothing is deleted.
    assert result["status"] == "ok", "enumeration did not complete: {}".format(result)
    assert result["present"] == 30
    assert result["deleted"] == 0
    # Cursor must advance monotonically: None -> "10" -> "20" -> "30".
    assert seen_cursors[:4] == [None, "10", "20", "30"], seen_cursors


def test_reconcile_with_nothing_known_is_a_noop(ob, w, monkeypatch):
    """A fresh install must not emit deletes before it has synced anything."""
    monkeypatch.setattr(watcher_mod.odbc, "scan_after", _fake_scan([[]]))
    result = w.reconcile()
    assert result["status"] == "skipped"
    assert result["deleted"] == 0


# ── Watcher liveness ─────────────────────────────────────────────────────────

def test_watcher_health_reports_not_running_before_start(w):
    """
    A watcher that never started must not report healthy.

    This is the failure mode the health endpoint exists for: a bad company path
    leaves the thread unstarted, the outbox stays empty, and that is otherwise
    indistinguishable from "no new invoices today".
    """
    state = w.health()
    assert state["healthy"] is False
    assert state["thread_alive"] is False


def test_watcher_health_surfaces_start_error(w, monkeypatch):
    """A bad company path must be reported, not just logged once at boot."""
    monkeypatch.setattr(
        watcher_mod, "get_settings",
        _settings_with(SAGE_MOCK=False, SAGE_COMPANY_PATH=r"C:\does\not\exist"),
    )
    w.start()

    state = w.health()
    assert state["healthy"] is False
    assert "does not exist" in state["start_error"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _settings_with(**overrides):
    """Return a get_settings() replacement with fields overridden."""
    from config import get_settings as real_get_settings

    def get_settings():
        base = real_get_settings()
        clone = base.model_copy()
        for key, value in overrides.items():
            object.__setattr__(clone, key, value)
        return clone

    return get_settings
