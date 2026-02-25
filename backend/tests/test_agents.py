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
