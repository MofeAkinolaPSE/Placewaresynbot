"""Run a quick local harness for `InventoryIntelligenceAgent` using sage_mock_data.

Run from repository root:

    python -m backend.scripts.run_inventory_agent

This loads `sage_mock_data/inventory.csv` and runs the agent, printing JSON.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
import csv

# Ensure `src` is importable when running as module
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "src"
sys.path.insert(0, str(SRC))

from src.utils.ttl_cache import SimpleTTLCache
from src.agent_registry import get_agent
from src.logging.agent_logger import get_logger
from src.metrics.observability import MetricsCollector


logger = get_logger("run_inventory_agent")


def csv_inventory_executor(spec: dict) -> list[dict]:
    """A tiny executor that loads `sage_mock_data/inventory.csv` and
    returns rows as dicts. `spec` is ignored other than allowing
    different filter types in future.
    """
    data_dir = ROOT / "sage_mock_data"
    csv_path = data_dir / "inventory.csv"
    rows: list[dict] = []
    if not csv_path.exists():
        raise FileNotFoundError(f"inventory CSV not found at {csv_path}")
    with csv_path.open(newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            # Normalize numeric fields
            try:
                r['stock'] = int(r.get('stock') or 0)
            except Exception:
                r['stock'] = 0
            # try multiple threshold column names
            thresh = r.get('threshold') or r.get('reorder_threshold') or r.get('reorder')
            try:
                r['threshold'] = int(thresh) if thresh not in (None, '') else 0
            except Exception:
                r['threshold'] = 0
            rows.append(r)
    return rows


def main() -> None:
    cache = SimpleTTLCache()
    metrics = MetricsCollector()

    context = {
        "db_executor": csv_inventory_executor,
        "query_specs": [{"type": "inventory_all"}],
        "parallel_queries": False,
        "cache": cache,
        "cache_ttl_seconds": 120,
        "metrics": metrics,
    }

    agent = get_agent("inventory_intelligence", context=context)
    if agent is None:
        logger.error("Inventory agent not registered")
        sys.exit(2)

    insight = agent.run()

    # If insight is a dataclass-like object, serialize sensibly
    out = {}
    if hasattr(insight, "__dict__"):
        out = insight.__dict__.copy()
        # ensure supporting_refs are serializable
        out["supporting_refs"] = list(out.get("supporting_refs", []))
    else:
        out = str(insight)

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
