import types
import pytest


def make_supabase_stub():
    class TableStub:
        def __init__(self, name):
            self.name = name
            self._payload = None

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def upsert(self, payload):
            self._payload = payload
            return self

        def update(self, payload):
            self._payload = payload
            return self

        def execute(self):
            if self.name == 'placeware_kpis':
                return types.SimpleNamespace(data=[{'metric':'pipeline.value','value':10000},{'metric':'revenue.last_90d','value':8000}])
            if self.name == 'customers':
                return types.SimpleNamespace(data=[{'id': 1}, {'id': 2}])
            return types.SimpleNamespace(data=[])

    class SupabaseStub:
        def table(self, name):
            return TableStub(name)

    return SupabaseStub()


@pytest.fixture(autouse=True)
def mock_supabase(monkeypatch):
    import src.db as db
    monkeypatch.setattr(db, 'db', make_supabase_stub())
    yield


def test_financial_agent_compute_forecast():
    from src.agents.financial_agent import FinancialAgent
    a = FinancialAgent()
    kpis = [{'metric':'pipeline.value','value':10000},{'metric':'revenue.last_90d','value':8000}]
    f = a.compute_forecast(kpis)
    assert 'metric' in f and f['metric'] == 'financial.forecast'
    assert f['value'] > 0


def test_crm_scoring_agent_compute_score():
    from src.agents.crm_scoring_agent import CRMScoringAgent
    a = CRMScoringAgent()
    score = a.compute_score(1, [{'type':'activity'},{'type':'activity'}], [{'metric':'risk.customer.1','value':5}])
    assert 0 <= score <= 100
from src.imports.sage_import import make_inmemory_executor
from src.utils.ttl_cache import SimpleTTLCache
from src.workflow.engine import WorkflowEngine
from src.workflow.replenishment_workflow import register_replenishment_workflow
from src.agent_registry import get_agent


def test_inventory_agent_triggers_workflow():
    # create a single low-stock row
    rows = [
        {"product_id": "P-001", "stock": 2, "threshold": 10, "reorder_qty": 20},
    ]
    executor = make_inmemory_executor(rows)
    cache = SimpleTTLCache()

    engine = WorkflowEngine()
    register_replenishment_workflow(engine)

    ctx = {
        "db_executor": executor,
        "query_specs": [{"type": "inventory_all"}],
        "parallel_queries": False,
        "cache": cache,
        "cache_ttl_seconds": 60,
        "workflow_engine": engine,
        "auto_trigger_workflow": True,
    }

    agent = get_agent("inventory_intelligence", context=ctx)
    assert agent is not None
    insight = agent.run()
    # ensure insight structure present
    insd = getattr(insight, "__dict__", insight)
    assert "metrics" in insd
    # ensure workflow was attempted
    em = insd.get("execution_metadata") or {}
    assert em.get("workflow_triggered") is True
