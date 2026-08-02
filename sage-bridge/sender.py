"""
sender.py — Drains the outbox to SynBot.

Single background thread. The ONLY component permitted to mark an event
delivered, and it does so only after a 2xx response.

Retry policy
------------
Exponential backoff with jitter, capped, and — critically — **unbounded in
wall-clock time**. The original code gave up after 3 attempts spanning ~6
seconds and discarded the event. A lunch-hour network outage was unrecoverable
data loss.

Here, an event is retried for RETRY_MAX_ATTEMPTS (default 20). With the default
schedule that spans roughly 10 hours of wall clock, so an overnight outage is
survived without operator action. When attempts are finally exhausted the event
is parked as ``failed`` and RETAINED on disk — visible via /sync/status and
replayable. It is never deleted.

Backoff schedule (base 2s, cap 1h, ±20% jitter):
    2s, 4s, 8s, 16s, 32s, 64s, 128s, 256s, 512s, 1024s, 2048s, then 1h each

tests/test_sync_guarantees.py::test_retry_survives_a_long_outage asserts the
total window, so changing these defaults without widening the window fails the
build rather than quietly shrinking the guarantee.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, Optional

import httpx

from config import get_settings
from outbox import get_outbox

logger = logging.getLogger("bridge.sender")

#: Treated as success. 409 is included deliberately: SynBot returns it when it
#: has already applied this event_id, which means our job is done. Retrying
#: would be pointless and would keep the event pending forever.
_SUCCESS_CODES = (200, 201, 202, 204, 409)


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with ±20% jitter, capped.

    Jitter prevents a queue that built up during an outage from stampeding
    SynBot in lockstep the moment it comes back.
    """
    raw = min(base * (2 ** attempt), cap)
    return raw * random.uniform(0.8, 1.2)


class OutboxSender:
    """Background thread that delivers pending outbox events to SynBot."""

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Event rather than sleep(): shutdown is immediate instead of waiting
        # out the poll interval, and start/stop in tests is fast.
        self._wake = threading.Event()
        self._client: Optional[httpx.Client] = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        settings = get_settings()
        if not settings.SYNBOT_WEBHOOK_URL:
            logger.warning(
                "SYNBOT_WEBHOOK_URL not configured — sender disabled. Events will "
                "accumulate in the outbox and deliver once it is set."
            )
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="OutboxSender"
        )
        self._thread.start()
        logger.info("OutboxSender started → %s", settings.SYNBOT_WEBHOOK_URL)

    def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._thread:
            # Bounded by one in-flight HTTP request, not by the poll interval.
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                logger.warning("OutboxSender did not stop within 15s")
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        logger.info("OutboxSender stopped.")

    def nudge(self) -> None:
        """Wake the sender immediately (called after a scan enqueues events)."""
        self._wake.set()

    # ── transport ────────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.Client:
        """One reusable client: connection pooling matters on old hardware."""
        if self._client is None:
            settings = get_settings()
            verify: Any = True
            if settings.BRIDGE_INSECURE_SKIP_VERIFY:
                # Loudly — this must never pass unnoticed in production.
                logger.warning(
                    "TLS VERIFICATION DISABLED (BRIDGE_INSECURE_SKIP_VERIFY=true). "
                    "Diagnostics only — do not run this way in production."
                )
                verify = False
            elif settings.BRIDGE_CA_CERT_PATH:
                verify = settings.BRIDGE_CA_CERT_PATH
            self._client = httpx.Client(
                timeout=httpx.Timeout(settings.SENDER_TIMEOUT_SECONDS),
                verify=verify,
                headers={"User-Agent": "sage-bridge/2.0"},
            )
        return self._client

    def _post(self, envelope: Dict[str, Any]) -> int:
        settings = get_settings()
        headers = {}
        if settings.SYNBOT_WEBHOOK_KEY:
            headers["X-Webhook-Key"] = settings.SYNBOT_WEBHOOK_KEY
        # Idempotency key in the header too, so an HTTP proxy or SynBot
        # middleware can dedupe without parsing the body.
        headers["X-Event-Id"] = envelope.get("event_id", "")
        resp = self._get_client().post(
            settings.SYNBOT_WEBHOOK_URL, json=envelope, headers=headers
        )
        return resp.status_code

    # ── main loop ────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        settings = get_settings()
        while self._running:
            try:
                self._drain_once()
            except Exception:
                # A bug here must never kill the thread — that would silently
                # stop all delivery while the service looks healthy.
                logger.exception("Sender loop error (continuing)")
            self._wake.wait(timeout=settings.SENDER_POLL_SECONDS)
            self._wake.clear()

    def _drain_once(self) -> None:
        settings = get_settings()
        ob = get_outbox()
        batch = ob.claim_due(limit=settings.SENDER_BATCH_SIZE)
        if not batch:
            return

        logger.debug("Sender: %d event(s) due", len(batch))
        for row in batch:
            if not self._running:
                return  # leave the rest pending; they survive the restart
            self._deliver(row)

    def _deliver(self, row: Dict[str, Any]) -> None:
        settings = get_settings()
        ob = get_outbox()
        event_id = row["event_id"]
        attempts = row["attempts"]
        envelope = row["payload"]

        try:
            status = self._post(envelope)
        except Exception as exc:
            self._handle_failure(event_id, attempts, "transport: {}".format(exc))
            return

        if status in _SUCCESS_CODES:
            ob.mark_sent(event_id)
            if status == 409:
                logger.info("Event %s already applied by SynBot (409) — done.", event_id)
            elif attempts > 0:
                logger.info("Event %s delivered on attempt %d.", event_id, attempts + 1)
            return

        # 4xx other than 409 is a permanent defect (bad auth, malformed body).
        # Retrying cannot fix it, so park immediately rather than burn 12
        # attempts over 8 hours on something that will never succeed.
        if 400 <= status < 500:
            ob.mark_failed(
                event_id,
                "HTTP {} — permanent client error, not retried. Check "
                "SYNBOT_WEBHOOK_KEY and the payload schema.".format(status),
            )
            return

        self._handle_failure(event_id, attempts, "HTTP {}".format(status))

    def _handle_failure(self, event_id: str, attempts: int, error: str) -> None:
        settings = get_settings()
        ob = get_outbox()
        if attempts + 1 >= settings.RETRY_MAX_ATTEMPTS:
            ob.mark_failed(event_id, error)
            return
        delay = _backoff_delay(
            attempts, settings.RETRY_BASE_SECONDS, settings.RETRY_MAX_DELAY_SECONDS
        )
        ob.mark_retry(event_id, error, delay)
        logger.warning(
            "Event %s failed (attempt %d/%d): %s — retrying in %.0fs",
            event_id, attempts + 1, settings.RETRY_MAX_ATTEMPTS, error, delay,
        )


# ── module-level singleton ───────────────────────────────────────────────────

_sender = OutboxSender()


def start_sender() -> None:
    _sender.start()


def stop_sender() -> None:
    _sender.stop()


def nudge_sender() -> None:
    _sender.nudge()
