"""
Tests for GET /compliance/status and GET /compliance/sop.

These tests use a mock db so they:
  1. Verify the endpoints return 200 with correct structure.
  2. Catch the `.not_.in_()` AttributeError that broke active_recalls
     (if TableQuery doesn't support not_in the test will blow up immediately).
  3. Cover the SOP list endpoint (which was returning 500 due to missing table).
"""
from __future__ import annotations

import types
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _MockTableQuery:
    """Minimal fluent query stub — mirrors TableQuery API including not_in()."""

    def __init__(self, table: str, return_rows: list | None = None, count: int = 0):
        self._table = table
        self._return_rows = return_rows or []
        self._count = count

    # filter methods — all return self
    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def neq(self, *_a, **_kw):
        return self

    def not_in(self, *_a, **_kw):
        return self

    def in_(self, *_a, **_kw):
        return self

    def like(self, *_a, **_kw):
        return self

    def ilike(self, *_a, **_kw):
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def insert(self, _payload):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._return_rows, count=self._count)


class _MockDB:
    def table(self, name: str) -> _MockTableQuery:
        return _MockTableQuery(name, return_rows=[], count=0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    """TestClient with db mocked so no real Postgres connection is needed."""
    from app import app          # noqa: PLC0415
    import src.routers.compliance as comp_router

    mock_db = _MockDB()
    monkeypatch.setattr(comp_router, "db", mock_db)

    # Also patch audit_event to a no-op
    monkeypatch.setattr(comp_router, "audit_event", lambda *_a, **_kw: None)

    yield TestClient(app)


def _auth_headers(client: TestClient) -> dict:
    """Obtain a valid JWT from the /auth/login endpoint using default test creds."""
    resp = client.post("/auth/login", json={"email": "admin@placeware.ng", "password": "admin123"})
    if resp.status_code == 200:
        token = resp.json().get("access_token") or resp.json().get("token", "")
        if token:
            return {"Authorization": f"Bearer {token}"}
    # Fallback: create a signed token manually
    import os, time, jwt as pyjwt  # type: ignore[import]
    secret = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
    payload = {
        "sub": "test-admin",
        "user_id": "test-admin",
        "roles": ["admin"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComplianceStatus:
    def test_returns_200_with_score(self, client):
        headers = _auth_headers(client)
        resp = client.get("/compliance/status", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "overall_compliance_score" in body
        assert isinstance(body["overall_compliance_score"], (int, float))
        assert 0 <= body["overall_compliance_score"] <= 100

    def test_contains_expected_keys(self, client):
        headers = _auth_headers(client)
        resp = client.get("/compliance/status", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "overdue_audits",
            "open_deviations",
            "overdue_maintenance",
            "active_recalls",
            "missed_activities",
            "as_of",
        ):
            assert key in body, f"Missing key: {key}"

    def test_not_in_method_used_for_recalls(self, client, monkeypatch):
        """Regression test: active_recalls used .not_.in_() which raised AttributeError."""
        import src.routers.compliance as comp_router

        call_log: list[str] = []

        class _LoggingQuery(_MockTableQuery):
            def not_in(self, col, values):  # type: ignore[override]
                call_log.append(f"not_in:{col}")
                return self

        class _LoggingDB:
            def table(self, name: str) -> _LoggingQuery:
                return _LoggingQuery(name)

        monkeypatch.setattr(comp_router, "db", _LoggingDB())
        headers = _auth_headers(client)
        resp = client.get("/compliance/status", headers=headers)
        assert resp.status_code == 200
        assert any("not_in:status" in entry for entry in call_log), (
            "active_recalls query did not call .not_in() — the fix may have been reverted"
        )


class TestComplianceSopList:
    def test_sop_list_returns_200(self, client):
        headers = _auth_headers(client)
        resp = client.get("/compliance/sop", headers=headers)
        assert resp.status_code == 200, resp.text

    def test_sop_list_with_category_param(self, client):
        headers = _auth_headers(client)
        resp = client.get("/compliance/sop?category=storage", headers=headers)
        assert resp.status_code == 200, resp.text

    def test_sop_list_structure(self, client, monkeypatch):
        """SOP list should return a dict with a 'data' key."""
        import src.routers.compliance as comp_router

        class _SOPDb:
            def table(self, name: str) -> _MockTableQuery:
                if name == "sop_registry":
                    sample = [
                        {"sop_id": "SOP-QC-001", "title": "Quality Check", "category": "qc", "status": "active"},
                    ]
                    return _MockTableQuery(name, return_rows=sample, count=1)
                return _MockTableQuery(name)

        monkeypatch.setattr(comp_router, "db", _SOPDb())
        headers = _auth_headers(client)
        resp = client.get("/compliance/sop", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body, (
            f"Expected 'data' key in SOP list response, got: {body}"
        )
