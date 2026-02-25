"""Script to import `sage_mock_data/inventory.csv` and trigger agents/workflows.

Run from repository root:

    python -m backend.scripts.import_and_trigger
"""
from __future__ import annotations
import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "src"
sys.path.insert(0, str(SRC))

from src.imports.sage_import import import_inventory_and_trigger
from src.workflow.engine import WorkflowEngine
from src.workflow.replenishment_workflow import register_replenishment_workflow


def main() -> None:
    csv_path = ROOT / "sage_mock_data" / "inventory.csv"
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        raise SystemExit(2)

    # create workflow engine and register replenishment workflow
    engine = WorkflowEngine()
    register_replenishment_workflow(engine)

    results = import_inventory_and_trigger(str(csv_path), agent_names=["inventory_intelligence"], workflow_engine=engine)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
