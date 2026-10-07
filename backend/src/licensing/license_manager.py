"""Reads the installed licence, verifies it, and decides whether the app is locked.

The licence file is re-read automatically (every REFRESH_SECONDS), so replacing it takes
effect without a restart or rebuild. Nothing here ever touches business data.

States:
    unconfigured    no public key built into this image yet -> enforcement off (logged loudly)
    valid           within the licence period
    grace           past expiry but inside the grace period -> still works, UI shows a warning
    expired         past the grace period                    -> LOCKED
    missing         no licence file                          -> LOCKED
    invalid         unreadable or bad signature              -> LOCKED
    clock_rollback  server clock moved backwards             -> LOCKED
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .license_format import LicenseFormatError, extract_token, license_window, load_public_key, parse_ts, verify_license
from .public_key import NEUROLAYER_LICENSE_PUBLIC_KEY

log = logging.getLogger("placeware.licensing")

DEFAULT_LICENSE_FILE = Path(__file__).resolve().parents[2] / ".license" / "system.dat"
REFRESH_SECONDS = 30
# How far the clock may step backwards before it counts as tampering (NTP corrections are seconds).
ROLLBACK_TOLERANCE = dt.timedelta(hours=6)
DEFAULT_SUPPORT = "NeuroLayer Support"


@dataclass(frozen=True)
class LicenseStatus:
    state: str
    locked: bool
    message: str
    lock_mode: str = "full"
    license_id: str | None = None
    licensee: str | None = None
    starts_on: str | None = None
    expires_on: str | None = None
    grace_ends_on: str | None = None
    days_remaining: int | None = None
    support_contact: str = DEFAULT_SUPPORT

    def public_dict(self) -> dict:
        return asdict(self)


def _db_sync_high_water(max_issued_at: dt.datetime, now: dt.datetime) -> dt.datetime | None:
    """Record `now` as the latest time seen and return the stored high-water mark.

    The mark only moves forward, except when a licence issued later than any seen before is
    installed: that resets it, so NeuroLayer can clear a false rollback lock by issuing a new
    licence. Returns None if the database is unavailable (the in-process check still runs).
    """
    try:
        import psycopg2
        from src.db import get_psycopg_dsn

        with psycopg2.connect(get_psycopg_dsn(), connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO license_state (id, max_issued_at, high_water, updated_at)
                VALUES (1, %(iss)s, %(now)s, now())
                ON CONFLICT (id) DO UPDATE SET
                    high_water = CASE WHEN EXCLUDED.max_issued_at > license_state.max_issued_at
                                      THEN EXCLUDED.high_water
                                      ELSE GREATEST(license_state.high_water, EXCLUDED.high_water) END,
                    max_issued_at = GREATEST(license_state.max_issued_at, EXCLUDED.max_issued_at),
                    updated_at = now()
                RETURNING high_water
                """,
                {"iss": max_issued_at, "now": now},
            )
            return cur.fetchone()[0]
    except Exception as exc:  # licence checks must never take the app down on a DB blip
        log.debug("licence state sync skipped: %s", exc)
        return None


class LicenseManager:
    def __init__(
        self,
        license_file: Path | str | None = None,
        public_key_b64: str = NEUROLAYER_LICENSE_PUBLIC_KEY,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
        sync_high_water: Callable[[dt.datetime, dt.datetime], dt.datetime | None] = _db_sync_high_water,
    ):
        self.license_file = Path(license_file or os.getenv("PLACEWARE_LICENSE_FILE") or DEFAULT_LICENSE_FILE)
        self._public_key = load_public_key(public_key_b64) if public_key_b64.strip() else None
        self._clock = clock
        self._sync_high_water = sync_high_water
        self._lock = threading.Lock()
        self._status: LicenseStatus | None = None
        self._checked_at = 0.0
        self._high_water: dt.datetime | None = None
        self._max_issued_at: dt.datetime | None = None

    def status(self, force: bool = False) -> LicenseStatus:
        if not force and self._status and time.monotonic() - self._checked_at < REFRESH_SECONDS:
            return self._status
        with self._lock:
            if force or not self._status or time.monotonic() - self._checked_at >= REFRESH_SECONDS:
                new = self._evaluate()
                if not self._status or (new.state, new.expires_on) != (self._status.state, self._status.expires_on):
                    (log.warning if new.locked or new.state in ("grace", "unconfigured") else log.info)(
                        "Licence state: %s - %s", new.state, new.message
                    )
                self._status, self._checked_at = new, time.monotonic()
        return self._status

    def _evaluate(self) -> LicenseStatus:
        if self._public_key is None:
            return LicenseStatus("unconfigured", False, "Licensing is not configured in this build (no public key).")
        try:
            text = self.license_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LicenseStatus("missing", True, "No licence is installed on this server.")
        except OSError as exc:
            log.error("Cannot read licence file %s: %s", self.license_file, exc)
            return LicenseStatus("invalid", True, "The installed licence could not be read.")
        try:
            payload = verify_license(extract_token(text), self._public_key)
        except LicenseFormatError as exc:
            log.error("Licence rejected: %s", exc)
            return LicenseStatus("invalid", True, "The installed licence could not be verified.")

        start, expiry, grace_end = license_window(payload)
        issued_at = parse_ts(payload["issued_at"])
        now = self._clock()
        today = now.date()
        info = dict(
            lock_mode=payload.get("lock_mode", "full"),
            license_id=payload["license_id"],
            licensee=payload["issued_to"],
            starts_on=start.isoformat(),
            expires_on=expiry.isoformat(),
            grace_ends_on=grace_end.isoformat(),
            days_remaining=(expiry - today).days,
            support_contact=payload.get("support_contact") or DEFAULT_SUPPORT,
        )

        if self._clock_rolled_back(now, issued_at):
            return LicenseStatus("clock_rollback", True, "The server clock appears to have been moved backwards.",
                                 **{**info, "lock_mode": "full"})
        if today < expiry:
            return LicenseStatus("valid", False, f"Licensed to {payload['issued_to']} until {expiry:%d %b %Y}.", **info)
        if today < grace_end:
            return LicenseStatus("grace", False,
                                 f"Subscription expired on {expiry:%d %b %Y}. Renew before {grace_end:%d %b %Y} "
                                 "to avoid interruption.", **info)
        return LicenseStatus("expired", True, f"Subscription expired on {expiry:%d %b %Y}.", **info)

    def _clock_rolled_back(self, now: dt.datetime, issued_at: dt.datetime) -> bool:
        # A clock earlier than the licence's own issue time is impossible on an honest server.
        if now < issued_at - dt.timedelta(days=1):
            return True
        if self._max_issued_at is None or issued_at > self._max_issued_at:
            self._max_issued_at, self._high_water = issued_at, now  # newer licence resets the mark
        stored = self._sync_high_water(self._max_issued_at, now)
        self._high_water = max(d for d in (self._high_water, stored, now) if d is not None)
        return now < self._high_water - ROLLBACK_TOLERANCE


license_manager = LicenseManager()
