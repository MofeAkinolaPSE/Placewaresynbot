from __future__ import annotations
from typing import Any, Callable, Dict, Iterable, List, Optional
import csv
from pathlib import Path
from src.agent_registry import get_agent
from src.utils.ttl_cache import SimpleTTLCache


def load_inventory_csv(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    rows: List[Dict[str, Any]] = []
    with p.open(newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            # normalize common numeric fields
            try:
                r['stock'] = int(r.get('stock') or 0)
            except Exception:
                r['stock'] = 0
            thresh = r.get('threshold') or r.get('reorder_threshold') or r.get('reorder')
            try:
                r['threshold'] = int(thresh) if thresh not in (None, '') else 0
            except Exception:
                r['threshold'] = 0
            rows.append(r)
    return rows


def make_inmemory_executor(rows: Iterable[Dict[str, Any]]) -> Callable[[Any], List[Dict[str, Any]]]:
    data = list(rows)

    def executor(spec: Any) -> List[Dict[str, Any]]:
        # A simple spec protocol: if dict with type=="inventory_all" return all rows
        if isinstance(spec, dict) and spec.get("type") == "inventory_all":
            return data
        # support simple filters: {'filter': {'product_id': 'X'}}
        if isinstance(spec, dict) and spec.get("filter"):
            f = spec.get("filter")
            out = []
            for r in data:
                ok = True
                for k, v in f.items():
                    if str(r.get(k)) != str(v):
                        ok = False
                        break
                if ok:
                    out.append(r)
            return out
        # default: return all
        return data

    return executor


def import_inventory_and_trigger(csv_path: str, agent_names: Optional[Iterable[str]] = None, workflow_engine: Optional[Any] = None, upsert_callable: Optional[Callable[[Dict[str, Any]], None]] = None, cache: Optional[Any] = None, auto_trigger: bool = True) -> Dict[str, Any]:
    """Import inventory CSV and trigger specified agents.

    - `csv_path`: local path to CSV
    - `agent_names`: iterable of agent names to run (defaults to ['inventory_intelligence'])
    - `workflow_engine`: optional WorkflowEngine instance to pass to agent context
    - `upsert_callable`: optional callable(row) to persist rows; if provided it will be called for each row
    - `cache`: optional cache instance (SimpleTTLCache recommended)
    - `auto_trigger`: pass to agent context to allow/disallow automatic workflow triggers

    Returns a dict mapping agent name to their Insight.__dict__ representation.
    """
    rows = load_inventory_csv(csv_path)
    if upsert_callable:
        for r in rows:
            try:
                upsert_callable(r)
            except Exception:
                # keep going; persist failures shouldn't stop import
                pass

    executor = make_inmemory_executor(rows)
    agent_names = list(agent_names) if agent_names else ["inventory_intelligence"]
    cache = cache or SimpleTTLCache()

    results: Dict[str, Any] = {}
    for name in agent_names:
        agent = get_agent(name, context={
            "db_executor": executor,
            "query_specs": [{"type": "inventory_all"}],
            "parallel_queries": False,
            "cache": cache,
            "cache_ttl_seconds": 300,
            "workflow_engine": workflow_engine,
            "auto_trigger_workflow": auto_trigger,
        })
        if agent is None:
            results[name] = {"error": "agent_not_registered"}
            continue
        insight = agent.run()
        # convert to serializable dict
        if hasattr(insight, "__dict__"):
            results[name] = insight.__dict__.copy()
        else:
            results[name] = str(insight)

    return results


__all__ = ["import_inventory_and_trigger", "load_inventory_csv", "make_inmemory_executor"]
