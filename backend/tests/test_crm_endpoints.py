import json
import datetime
import types
import pytest
from fastapi.testclient import TestClient


def make_supabase_stub():
    class TableStub:
        def __init__(self, name):
            self.name = name
            self._payload = None

        def insert(self, payload):
            self._payload = payload
            return self

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def range(self, *args, **kwargs):
            return self

        def update(self, payload):
            self._payload = {**(self._payload or {}), **payload}
            return self

        def upsert(self, payload):
            self._payload = payload
            return self

        def execute(self):
            # simple deterministic returns based on table name
            if self.name == 'leads' and self._payload is not None:
                out = dict(self._payload)
                out['id'] = 1
                return types.SimpleNamespace(data=[out])
            if self.name == 'opportunities' and self._payload is not None:
                out = dict(self._payload)
                out['id'] = 10
                return types.SimpleNamespace(data=[out])
            if self.name == 'event_ledger' and self._payload is not None:
                return types.SimpleNamespace(data=[{'event_id': 'evt-1', 'created_at': datetime.datetime.utcnow().isoformat() + 'Z'}])
            # generic list
            return types.SimpleNamespace(data=[self._payload] if self._payload else [])

    class SupabaseStub:
        def table(self, name):
            return TableStub(name)

    return SupabaseStub()


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    # Mock supabase client used in src.db
    import src.db as db

    monkeypatch.setattr(db, 'db', make_supabase_stub())

    # Mock JWT decode to always return a valid crm role
    import src.middleware as mw

    def fake_decode(token, required_role=None):
        return {'sub': 'test-user', 'roles': ['crm', 'user']}

    monkeypatch.setattr(mw, 'decode_jwt_token', fake_decode)
    yield


def test_create_lead_creates_event_and_returns_lead():
    from backend.app import app

    client = TestClient(app)
    payload = {'source': 'web', 'industry': 'pharma', 'metadata': {'source': 'web'}}
    headers = {'Authorization': 'Bearer faketoken'}
    r = client.post('/crm/leads', json=payload, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data.get('id') == 1
    assert data.get('industry') == 'pharma'


def test_create_opportunity_creates_event_and_returns_opp():
    from backend.app import app

    client = TestClient(app)
    payload = {'title': 'New Deal', 'customer_id': 5, 'value': 1000}
    headers = {'Authorization': 'Bearer faketoken'}
    r = client.post('/crm/opportunities', json=payload, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data.get('id') == 10
    assert data.get('title') == 'New Deal'
