"""
outbox.py — Durable store-and-forward queue backed by stdlib sqlite3.

The problem this solves
-----------------------
The original watcher did this::

    self._mtimes[filename] = mtime      # watermark advanced
    ...
    _push_webhook(entity_type)          # delivery attempted, may fail

If the push failed, the event was logged and dropped — but the watermark had
already moved, so no later poll re-detected the change. SynBot being down for
30 seconds meant permanent, silent loss. And because the watermark lived only
in RAM, a reboot re-seeded from current mtimes and discarded everything that
happened while the service was down.

The fix is ordinary transactional messaging: write the event to durable storage
FIRST, advance the watermark in the SAME transaction, and only mark the event
delivered after SynBot has acknowledged it. A crash at any point leaves the
event pending, so it is retried rather than lost.

Guarantees
----------
* **At-least-once delivery.** An event is removed from the pending set only
  after a 2xx from SynBot. Crash, reboot, or network loss at any point leaves
  it pending and it is retried.
* **Exactly-once effect.** Every event carries a deterministic ``event_id``
  (see events.py). SynBot rejects a repeat of an ``event_id`` it has already
  applied, so at-least-once delivery yields at-most-once application.
* **Crash-safe watermark.** The scan watermark is stored in the same SQLite
  file and advanced in the same transaction that enqueues the events. It can
  never run ahead of the events it represents.

Why SQLite
----------
It is in the Python standard library (nothing to install on a locked-down
Win7 box), it is a single file that is trivial to back up or inspect, and it
gives real fsync-backed durability. Footprint is a few hundred KB.

Concurrency
-----------
One writer thread (the scanner) and one reader thread (the sender), plus
occasional reads from the HTTP layer for /sync/status. Each thread gets its own
connection via threading.local — sqlite3 connections are not shareable across
threads. WAL mode lets the reader work while the writer commits.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bridge.outbox")

# Delivery states
PENDING = "pending"
SENT = "sent"
FAILED = "failed"          # exceeded max attempts; retained for inspection

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    event_id      TEXT PRIMARY KEY,      -- deterministic; see events.py
    entity_type   TEXT NOT NULL,
    sage_id       TEXT,
    payload       TEXT NOT NULL,         -- JSON
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    next_attempt  REAL NOT NULL DEFAULT 0,   -- unix ts; backoff gate
    last_error    TEXT,
    created_at    REAL NOT NULL,
    sent_at       REAL
);

-- Drives the sender's "what's due now" query.
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox (status, next_attempt);

-- Crash-safe scan watermarks, one row per scan cursor.
CREATE TABLE IF NOT EXISTS watermark (
    name       TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class Outbox:
    """Durable event queue. Thread-safe via per-thread connections."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    # ── connection handling ──────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Return this thread's connection, creating it on first use."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._db_path,
                timeout=30,            # wait rather than raise on a locked db
                isolation_level=None,  # explicit BEGIN/COMMIT
            )
            conn.row_factory = sqlite3.Row
            # WAL: reader (sender) and writer (scanner) do not block each other.
            conn.execute("PRAGMA journal_mode=WAL")
            # FULL rather than NORMAL: this queue is the durability guarantee.
            # A power cut on old desktop hardware must not lose committed events.
            conn.execute("PRAGMA synchronous=FULL")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(_SCHEMA)
        logger.info("Outbox ready at %s", self._db_path)

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── enqueue ──────────────────────────────────────────────────────────────

    def enqueue_batch(
        self,
        events: List[Dict[str, Any]],
        watermark_name: Optional[str] = None,
        watermark_value: Optional[str] = None,
    ) -> int:
        """
        Atomically persist ``events`` and advance a watermark.

        This is THE critical operation. Events and watermark commit together, so
        the watermark can never advance past events that were not stored. A
        crash mid-call rolls back both.

        Each event dict needs: event_id, entity_type, payload; sage_id optional.

        Re-enqueuing an existing event_id is ignored (INSERT OR IGNORE) — a
        rescan after a crash is harmless rather than a source of duplicates.

        Returns the number of genuinely new rows inserted.
        """
        conn = self._conn()
        now = time.time()
        inserted = 0
        conn.execute("BEGIN IMMEDIATE")
        try:
            for ev in events:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO outbox "
                    "(event_id, entity_type, sage_id, payload, status, "
                    " attempts, next_attempt, created_at) "
                    "VALUES (?,?,?,?,?,0,?,?)",
                    (
                        ev["event_id"],
                        ev["entity_type"],
                        ev.get("sage_id"),
                        json.dumps(ev["payload"], default=str),
                        PENDING,
                        now,
                        now,
                    ),
                )
                inserted += cur.rowcount or 0

            if watermark_name is not None and watermark_value is not None:
                conn.execute(
                    "INSERT INTO watermark (name, value, updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value, "
                    "updated_at=excluded.updated_at",
                    (watermark_name, watermark_value, now),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("enqueue_batch failed — rolled back, nothing lost")
            raise

        if inserted:
            logger.info("Outbox: enqueued %d new event(s)", inserted)
        return inserted

    # ── watermark ────────────────────────────────────────────────────────────

    def get_watermark(self, name: str, default: str = "") -> str:
        row = self._conn().execute(
            "SELECT value FROM watermark WHERE name=?", (name,)
        ).fetchone()
        return row["value"] if row else default

    def set_watermark(self, name: str, value: str) -> None:
        """Set a watermark on its own. Prefer enqueue_batch() for scan cursors."""
        self._conn().execute(
            "INSERT INTO watermark (name, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (name, value, time.time()),
        )

    # ── delivery ─────────────────────────────────────────────────────────────

    def claim_due(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Return pending events whose backoff has elapsed, oldest first.

        Does not lock rows: exactly one sender thread runs, and at-least-once
        delivery plus event_id dedupe on the SynBot side makes an accidental
        double-send harmless.
        """
        rows = self._conn().execute(
            "SELECT * FROM outbox WHERE status=? AND next_attempt<=? "
            "ORDER BY created_at LIMIT ?",
            (PENDING, time.time(), limit),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d["payload"])
            except (ValueError, TypeError):
                # Corrupt payload: park it rather than crash the sender loop.
                logger.error("Corrupt payload for %s — marking failed", d["event_id"])
                self.mark_failed(d["event_id"], "corrupt payload JSON")
                continue
            out.append(d)
        return out

    def mark_sent(self, event_id: str) -> None:
        """Called ONLY after SynBot returns 2xx."""
        self._conn().execute(
            "UPDATE outbox SET status=?, sent_at=?, last_error=NULL WHERE event_id=?",
            (SENT, time.time(), event_id),
        )

    def mark_retry(self, event_id: str, error: str, delay_seconds: float) -> None:
        """Record a failed attempt and gate the next one behind ``delay_seconds``."""
        self._conn().execute(
            "UPDATE outbox SET attempts=attempts+1, next_attempt=?, last_error=? "
            "WHERE event_id=?",
            (time.time() + delay_seconds, error[:500], event_id),
        )

    def mark_failed(self, event_id: str, error: str) -> None:
        """
        Give up on an event after max attempts.

        The row is RETAINED with status='failed' — never deleted. This is the
        difference between "dropped" and "silently dropped": the event is still
        on disk, surfaced by /sync/status, and replayable with requeue_failed().
        """
        self._conn().execute(
            "UPDATE outbox SET status=?, last_error=? WHERE event_id=?",
            (FAILED, error[:500], event_id),
        )
        logger.error(
            "Outbox: event %s exhausted retries and is parked as FAILED. "
            "It is retained on disk and can be replayed via "
            "POST /sync/outbox/replay. Error: %s",
            event_id, error[:200],
        )

    def requeue_failed(self) -> int:
        """Move all failed events back to pending. Returns how many."""
        cur = self._conn().execute(
            "UPDATE outbox SET status=?, attempts=0, next_attempt=0 WHERE status=?",
            (PENDING, FAILED),
        )
        n = cur.rowcount or 0
        if n:
            logger.info("Outbox: requeued %d failed event(s)", n)
        return n

    # ── housekeeping / observability ─────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        conn = self._conn()
        counts = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM outbox GROUP BY status"
            ).fetchall()
        }
        oldest = conn.execute(
            "SELECT MIN(created_at) AS t FROM outbox WHERE status=?", (PENDING,)
        ).fetchone()["t"]
        return {
            "pending": counts.get(PENDING, 0),
            "sent": counts.get(SENT, 0),
            "failed": counts.get(FAILED, 0),
            "oldest_pending_age_seconds": (
                round(time.time() - oldest, 1) if oldest else None
            ),
        }

    def purge_sent(self, older_than_days: int = 30) -> int:
        """
        Delete delivered events older than N days to bound file growth.

        Only status='sent' rows are eligible. Pending and failed rows are never
        purged regardless of age — losing those is exactly what this module
        exists to prevent.
        """
        cutoff = time.time() - (older_than_days * 86400)
        cur = self._conn().execute(
            "DELETE FROM outbox WHERE status=? AND sent_at IS NOT NULL AND sent_at<?",
            (SENT, cutoff),
        )
        n = cur.rowcount or 0
        if n:
            self._conn().execute("VACUUM")
            logger.info("Outbox: purged %d sent event(s) older than %dd", n, older_than_days)
        return n


# ── module-level singleton ───────────────────────────────────────────────────

_outbox: Optional[Outbox] = None
_init_lock = threading.Lock()


def get_outbox() -> Outbox:
    """Return the process-wide Outbox, creating it on first call."""
    global _outbox
    if _outbox is None:
        with _init_lock:
            if _outbox is None:
                from config import get_settings
                _outbox = Outbox(get_settings().OUTBOX_DB_PATH)
    return _outbox


def reset_outbox_for_tests(db_path: str) -> Outbox:
    """Point the singleton at a fresh database. Test-support only."""
    global _outbox
    _outbox = Outbox(db_path)
    return _outbox
