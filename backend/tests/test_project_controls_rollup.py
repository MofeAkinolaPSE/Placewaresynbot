import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import db as db_module  # noqa: E402


class _Resp:
    def __init__(self, data):
        self.data = data


class _RpcExec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Resp(self._data)


def test_get_controls_rollup_prefers_rpc(monkeypatch):
    class FakeSupabase:
        def rpc(self, _name, _params):
            return _RpcExec({
                "project_id": None,
                "scope": {"status_counts": {"planned": 1}, "total": 1},
                "cost": {"status_counts": {}, "total": 0},
                "risk": {"status_counts": {}, "total": 0, "high_risk_open_count": 0},
                "change": {"status_counts": {}, "total": 0, "pending_approvals": 0},
            })

    monkeypatch.setattr(db_module, "supabase", FakeSupabase())
    out = db_module.get_controls_rollup()
    assert out["scope"]["total"] == 1
    assert out["project_id"] is None


def test_get_controls_rollup_falls_back_when_rpc_fails(monkeypatch):
    class TableQuery:
        def __init__(self, rows):
            self.rows = rows

        def select(self, _fields):
            return self

        def eq(self, _k, _v):
            return self

        def execute(self):
            return _Resp(self.rows)

    class FakeSupabase:
        def rpc(self, _name, _params):
            raise RuntimeError("rpc unavailable")

        def table(self, name):
            if name == "placeware_scope_items":
                return TableQuery([{"status": "planned"}, {"status": "done"}])
            if name == "placeware_cost_items":
                return TableQuery([{"status": "approved"}])
            if name == "placeware_risk_register":
                return TableQuery([
                    {"status": "open", "probability": 5, "impact": 4},
                    {"status": "closed", "probability": 2, "impact": 2},
                ])
            if name == "placeware_change_requests":
                return TableQuery([{"status": "proposed"}, {"status": "under_review"}, {"status": "approved"}])
            return TableQuery([])

    monkeypatch.setattr(db_module, "supabase", FakeSupabase())
    out = db_module.get_controls_rollup(project_id="p-1")
    assert out["project_id"] == "p-1"
    assert out["scope"]["total"] == 2
    assert out["risk"]["high_risk_open_count"] == 1
    assert out["change"]["pending_approvals"] == 2
