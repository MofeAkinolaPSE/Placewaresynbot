"""One worker runs the background jobs.

The backend runs several uvicorn workers (UVICORN_WORKERS) so 30-50 laptops are served in
parallel. Every worker runs the startup hooks, but the schedulers and monitors they start
(weekly report emails, backups, escalations, KPI watchdog, agents...) must run once, not once per
worker. The first worker to take a Postgres advisory lock is the leader and starts them; the lock
lives on a connection held open for the life of that worker. If the leader dies, its connection
closes, the lock frees, and the worker uvicorn starts in its place becomes the leader.

Set BACKGROUND_JOBS=0 to start no background jobs in this container at all.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import psycopg2

logger = logging.getLogger(__name__)

_LOCK_KEY = 7_204_311  # any constant; identifies "Placeware background jobs"
_lock = threading.Lock()
_decided: Optional[bool] = None
_conn = None  # kept open: closing it releases the lock


def is_leader() -> bool:
    global _decided, _conn
    if _decided is not None:
        return _decided
    with _lock:
        if _decided is not None:
            return _decided
        if os.getenv("BACKGROUND_JOBS", "1").lower() in ("0", "false", "no"):
            _decided = False
            return _decided
        try:
            from src.db import get_psycopg_dsn
            conn = psycopg2.connect(get_psycopg_dsn(), connect_timeout=5)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
                got = bool(cur.fetchone()[0])
            if got:
                _conn = conn
            else:
                conn.close()
            _decided = got
        except Exception as exc:
            # Can't reach the lock (e.g. no Postgres in a test): behave like a single worker.
            logger.warning("leader: advisory lock unavailable (%s); running background jobs here", exc)
            _decided = True
        logger.info("leader: pid %s %s background jobs", os.getpid(), "runs" if _decided else "skips")
        return _decided
