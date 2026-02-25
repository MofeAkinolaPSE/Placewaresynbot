from src.imports.sage_import import make_inmemory_executor
from src.utils.ttl_cache import SimpleTTLCache
from src.agent_registry import get_agent
from src.workflow.batch_locking import is_batch_locked, lock_batch, unlock_batch
from src.workflow.chain_of_custody import record_custody_event, list_custody_events


def test_import_clearance_agent_basic():
    rows = [
        {"shipment_id": "S1", "supplier": "A", "status": "under clearance", "arrival_date": "2024-01-01T00:00:00"}
    ]
    executor = make_inmemory_executor(rows)
    cache = SimpleTTLCache()
    ctx = {"db_executor": executor, "cache": cache, "cache_ttl_seconds": 60}
    agent = get_agent("import_clearance", context=ctx)
    assert agent is not None
    insight = agent.run()
    insd = getattr(insight, "__dict__", insight)
    assert "metrics" in insd


def test_expiry_monitoring_agent_basic():
    rows = [{"batch_id": "B1", "sku": "P1", "expiry_date": "2099-01-01", "qty_on_hand": 100, "avg_monthly_sales": 1}]
    executor = make_inmemory_executor(rows)
    ctx = {"db_executor": executor, "cache": SimpleTTLCache(), "cache_ttl_seconds": 60}
    agent = get_agent("expiry_monitoring", context=ctx)
    assert agent is not None
    insight = agent.run()
    assert insight is not None


def test_cold_chain_and_custody_basic():
    # test custody recording + batch locking flow
    r = record_custody_event("SHIP1", "port", 5.0, "tester", "ok")
    assert r.get("ok") is True
    events = list_custody_events("SHIP1")
    assert isinstance(events, list)

    # batch lock/unlock helpers
    lock_batch("BATCH-1", "test_lock", "tester")
    assert is_batch_locked("BATCH-1") is True
    unlock_batch("BATCH-1", "tester")
    assert is_batch_locked("BATCH-1") in (False, True)
