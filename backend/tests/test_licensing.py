"""Licence enforcement: signing, state machine, clock rollback, and the request guard."""
import datetime as dt
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.licensing import license_guard
from src.licensing.license_format import add_months, public_key_b64, sign_license
from src.licensing.license_manager import LicenseManager

KEY = Ed25519PrivateKey.generate()
PUB = public_key_b64(KEY)
UTC = dt.timezone.utc


def _payload(**over):
    p = {"license_id": "PW-T1", "issued_to": "Test Client", "start_date": "2026-10-05", "duration_months": 1,
         "grace_period_days": 7, "lock_mode": "full", "issued_at": "2026-10-05T09:00:00Z"}
    p.update(over)
    return p


class Clock:
    def __init__(self, when):
        self.now = when

    def __call__(self):
        return self.now


def _manager(tmp_path, token=None, when=dt.datetime(2026, 10, 20, tzinfo=UTC), pub=PUB, store=None):
    f = tmp_path / "system.dat"
    if token is not None:
        f.write_text(f"# comment line\n{token}\n", encoding="utf-8")
    clock = Clock(when)
    m = LicenseManager(f, public_key_b64=pub, clock=clock, sync_high_water=store or (lambda iss, now: None))
    return m, clock, f


def test_add_months_clamps_month_end():
    assert add_months(dt.date(2026, 10, 5), 1) == dt.date(2026, 11, 5)
    assert add_months(dt.date(2026, 10, 5), 3) == dt.date(2027, 1, 5)
    assert add_months(dt.date(2027, 1, 31), 1) == dt.date(2027, 2, 28)


@pytest.mark.parametrize("day,state,locked", [
    (dt.datetime(2026, 11, 4, 23, tzinfo=UTC), "valid", False),
    (dt.datetime(2026, 11, 5, 1, tzinfo=UTC), "grace", False),
    (dt.datetime(2026, 11, 11, 23, tzinfo=UTC), "grace", False),
    (dt.datetime(2026, 11, 12, 1, tzinfo=UTC), "expired", True),
])
def test_state_over_time(tmp_path, day, state, locked):
    m, _, _ = _manager(tmp_path, sign_license(_payload(), KEY), when=day)
    s = m.status(force=True)
    assert (s.state, s.locked, s.expires_on, s.grace_ends_on) == (state, locked, "2026-11-05", "2026-11-12")


def test_missing_and_unconfigured(tmp_path):
    assert LicenseManager(tmp_path / "nope.dat", public_key_b64=PUB).status(force=True).state == "missing"
    s = LicenseManager(tmp_path / "nope.dat", public_key_b64="").status(force=True)
    assert (s.state, s.locked) == ("unconfigured", False)


def test_edited_licence_is_rejected(tmp_path):
    token = sign_license(_payload(), KEY)
    prefix, body, sig = token.split(".")
    import base64
    raw = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    raw["duration_months"] = 48
    forged = base64.urlsafe_b64encode(json.dumps(raw).encode()).rstrip(b"=").decode()
    m, _, _ = _manager(tmp_path, f"{prefix}.{forged}.{sig}")
    assert m.status(force=True).state == "invalid"


def test_licence_signed_by_another_key_is_rejected(tmp_path):
    m, _, _ = _manager(tmp_path, sign_license(_payload(), Ed25519PrivateKey.generate()))
    assert m.status(force=True).state == "invalid"


def test_clock_before_issue_date_locks(tmp_path):
    m, _, _ = _manager(tmp_path, sign_license(_payload(), KEY), when=dt.datetime(2026, 10, 1, tzinfo=UTC))
    assert m.status(force=True).state == "clock_rollback"


def test_clock_rollback_detected_and_cleared_by_newer_licence(tmp_path):
    m, clock, f = _manager(tmp_path, sign_license(_payload(), KEY), when=dt.datetime(2026, 11, 20, tzinfo=UTC))
    assert m.status(force=True).state == "expired"
    clock.now = dt.datetime(2026, 10, 25, tzinfo=UTC)  # someone winds the clock back
    assert m.status(force=True).state == "clock_rollback"
    # NeuroLayer issues a fresh licence -> the high-water mark resets
    f.write_text(sign_license(_payload(license_id="PW-T2", issued_at="2026-10-24T00:00:00Z"), KEY), encoding="utf-8")
    assert m.status(force=True).state == "valid"


def test_rollback_survives_restart_via_store(tmp_path):
    db = {}

    def store(iss, now):  # mimics the SQL upsert in _db_sync_high_water
        if not db or iss > db["iss"]:
            db.update(iss=iss, hw=now)
        else:
            db["hw"] = max(db["hw"], now)
        return db["hw"]

    token = sign_license(_payload(), KEY)
    _manager(tmp_path, token, when=dt.datetime(2026, 11, 20, tzinfo=UTC), store=store)[0].status(force=True)
    fresh, _, _ = _manager(tmp_path, token, when=dt.datetime(2026, 10, 25, tzinfo=UTC), store=store)
    assert fresh.status(force=True).state == "clock_rollback"


def _client(monkeypatch, manager):
    monkeypatch.setattr(license_guard, "license_manager", manager)
    app = FastAPI()
    app.include_router(license_guard.router)
    app.get("/inventory/items")(lambda: {"ok": True})
    app.post("/inventory/items")(lambda: {"ok": True})
    app.get("/health")(lambda: {"ok": True})
    app.add_middleware(license_guard.LicenseGuardMiddleware)
    return TestClient(app)


def test_guard_blocks_when_expired_but_keeps_essentials_open(tmp_path, monkeypatch):
    m, _, _ = _manager(tmp_path, sign_license(_payload(), KEY), when=dt.datetime(2026, 12, 1, tzinfo=UTC))
    c = _client(monkeypatch, m)
    r = c.post("/inventory/items")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "LICENSE_EXPIRED"
    assert c.get("/inventory/items").status_code == 403
    assert c.get("/health").status_code == 200
    st = c.get("/license/status").json()
    assert st["state"] == "expired" and "signature" not in json.dumps(st)


def test_guard_read_only_mode_allows_reads(tmp_path, monkeypatch):
    m, _, _ = _manager(tmp_path, sign_license(_payload(lock_mode="read_only"), KEY),
                       when=dt.datetime(2026, 12, 1, tzinfo=UTC))
    c = _client(monkeypatch, m)
    assert c.get("/inventory/items").status_code == 200
    assert c.post("/inventory/items").status_code == 403


def test_guard_passes_everything_when_valid(tmp_path, monkeypatch):
    m, _, _ = _manager(tmp_path, sign_license(_payload(), KEY))
    c = _client(monkeypatch, m)
    assert c.post("/inventory/items").status_code == 200
