"""
test_end_to_end.py — Sender against a real HTTP server that misbehaves.

test_sync_guarantees.py proves the outbox's storage semantics. This file proves
the *delivery* half: that a SynBot which is down, slow, or flapping results in
retry-until-success rather than loss, and that recovery needs no operator action.

A real threaded HTTP server is used rather than a mock so the httpx client,
timeouts, status handling and retry loop are all genuinely exercised.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BRIDGE_API_KEY", "test-key-that-is-long-enough-1234")
os.environ.setdefault("SAGE_MOCK", "true")


class FakeSynBot:
    """Controllable SynBot stand-in."""

    def __init__(self):
        self.received: list = []
        self.status_code = 200
        self.fail_count = 0          # fail this many requests, then succeed
        self.seen_event_ids: set = set()
        self.dedupe = False
        self._server = None
        self._thread = None
        self.port = 0

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body)
                except ValueError:
                    payload = {}

                if outer.fail_count > 0:
                    outer.fail_count -= 1
                    self.send_response(503)
                    self.end_headers()
                    return

                eid = payload.get("event_id", "")
                if outer.dedupe and eid in outer.seen_event_ids:
                    self.send_response(409)      # already applied
                    self.end_headers()
                    return

                outer.seen_event_ids.add(eid)
                outer.received.append(payload)
                self.send_response(outer.status_code)
                self.end_headers()
                self.wfile.write(b'{"received":true}')

            def log_message(self, *args):
                pass                              # keep test output clean

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return "http://127.0.0.1:{}/sage/webhook".format(self.port)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


@pytest.fixture(autouse=True)
def isolate_env():
    """
    Snapshot and restore os.environ around every test in this module.

    _fresh_sender() overrides RETRY_BASE_SECONDS and friends to keep these
    tests fast. Without this fixture those overrides leak into other modules
    and, for example, make the retry-window assertion in
    test_sync_guarantees.py measure the test's 0.1s base instead of the real
    configured default.
    """
    import config
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)
    config.get_settings.cache_clear()


@pytest.fixture()
def synbot():
    s = FakeSynBot()
    s.start()
    yield s
    s.stop()


def _fresh_sender(tmp_path, synbot, **overrides):
    """Build an isolated outbox + sender pointed at the fake SynBot."""
    import config
    import outbox as outbox_mod
    import sender as sender_mod

    config.get_settings.cache_clear()
    os.environ["SYNBOT_WEBHOOK_URL"] = "http://127.0.0.1:{}/sage/webhook".format(synbot.port)
    os.environ["OUTBOX_DB_PATH"] = str(tmp_path / "e2e.db")
    os.environ["RETRY_BASE_SECONDS"] = "0.1"       # keep the test fast
    os.environ["SENDER_POLL_SECONDS"] = "1"
    for k, v in overrides.items():
        os.environ[k] = str(v)

    ob = outbox_mod.reset_outbox_for_tests(str(tmp_path / "e2e.db"))
    sender = sender_mod.OutboxSender()
    return ob, sender


def _wait_for(predicate, timeout=20.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _ev(eid, sage_id="1"):
    return {
        "event_id": eid,
        "entity_type": "invoice",
        "sage_id": sage_id,
        "payload": {"event_id": eid, "entity_type": "invoice",
                    "sage_id": sage_id, "data": {"sage_id": sage_id}},
    }


# ── Happy path ───────────────────────────────────────────────────────────────

def test_event_is_delivered(tmp_path, synbot):
    ob, sender = _fresh_sender(tmp_path, synbot)
    ob.enqueue_batch([_ev("e1")])
    sender.start()
    try:
        assert _wait_for(lambda: len(synbot.received) == 1), "event never delivered"
        assert _wait_for(lambda: ob.stats()["sent"] == 1)
    finally:
        sender.stop()
    assert synbot.received[0]["event_id"] == "e1"


# ── Failure and recovery ─────────────────────────────────────────────────────

def test_transient_failure_is_retried_until_success(tmp_path, synbot):
    """SynBot 503s three times, then accepts. Nothing is lost."""
    ob, sender = _fresh_sender(tmp_path, synbot)
    synbot.fail_count = 3
    ob.enqueue_batch([_ev("e1")])
    sender.start()
    try:
        assert _wait_for(lambda: len(synbot.received) == 1, timeout=30), \
            "event was not retried to success"
        assert _wait_for(lambda: ob.stats()["sent"] == 1)
    finally:
        sender.stop()
    assert ob.stats()["failed"] == 0


def test_synbot_down_then_up_loses_nothing(tmp_path, synbot):
    """
    The exact scenario the original lost data in: SynBot unreachable at the
    moment of the change, reachable later. Every event must still arrive.
    """
    ob, sender = _fresh_sender(tmp_path, synbot)
    synbot.stop()                                   # SynBot is down

    ob.enqueue_batch([_ev("e1", "1"), _ev("e2", "2"), _ev("e3", "3")])
    sender.start()
    try:
        time.sleep(2)                               # attempts fail
        assert ob.stats()["sent"] == 0
        assert ob.stats()["pending"] == 3, "events dropped while SynBot was down"

        synbot.start_on_port = True
        # Bring SynBot back on the same port.
        import http.server, threading as th
        outer = synbot

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.received.append(json.loads(self.rfile.read(n)))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", outer.port), H)
        th.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            assert _wait_for(lambda: len(outer.received) == 3, timeout=40), \
                "events not delivered after SynBot recovered"
            assert _wait_for(lambda: ob.stats()["sent"] == 3, timeout=10)
        finally:
            srv.shutdown()
            srv.server_close()
    finally:
        sender.stop()


def test_permanent_client_error_parks_immediately(tmp_path, synbot):
    """
    A 403 (bad webhook key) cannot be fixed by retrying, so it parks at once
    instead of burning the full retry window — but is still RETAINED.
    """
    ob, sender = _fresh_sender(tmp_path, synbot)
    synbot.status_code = 403
    ob.enqueue_batch([_ev("e1")])
    sender.start()
    try:
        assert _wait_for(lambda: ob.stats()["failed"] == 1, timeout=15)
    finally:
        sender.stop()
    assert ob.stats()["sent"] == 0
    row = ob._conn().execute(
        "SELECT attempts, last_error FROM outbox WHERE event_id='e1'"
    ).fetchone()
    assert row["attempts"] <= 1, "permanent error should not be retried"
    assert "403" in row["last_error"]


def test_409_duplicate_is_treated_as_success(tmp_path, synbot):
    """
    SynBot answering 409 means 'already applied'. The bridge must accept that
    as done rather than retrying forever.
    """
    ob, sender = _fresh_sender(tmp_path, synbot)
    synbot.dedupe = True
    synbot.seen_event_ids.add("e1")                 # pretend it was applied
    ob.enqueue_batch([_ev("e1")])
    sender.start()
    try:
        assert _wait_for(lambda: ob.stats()["sent"] == 1, timeout=15)
    finally:
        sender.stop()
    assert ob.stats()["failed"] == 0


def test_restart_mid_queue_delivers_remainder(tmp_path, synbot):
    """Killing the sender mid-queue must leave the rest pending, not lost."""
    ob, sender = _fresh_sender(tmp_path, synbot)
    ob.enqueue_batch([_ev("e{}".format(i), str(i)) for i in range(10)])

    sender.start()
    time.sleep(0.5)
    sender.stop()                                    # abrupt stop

    delivered_before = len(synbot.received)
    assert delivered_before < 10 or ob.stats()["pending"] == 0

    import sender as sender_mod
    sender2 = sender_mod.OutboxSender()              # simulate service restart
    sender2.start()
    try:
        assert _wait_for(lambda: ob.stats()["sent"] == 10, timeout=30), \
            "remaining events not delivered after restart"
    finally:
        sender2.stop()

    ids = {r["event_id"] for r in synbot.received}
    assert ids == {"e{}".format(i) for i in range(10)}, "some events never arrived"
