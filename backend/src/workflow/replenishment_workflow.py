from __future__ import annotations
from typing import Dict, Any
from src.workflow.engine import WorkflowEngine
from src.workflow.actions import CreateReplenishmentAction
from src.logging.agent_logger import get_logger

logger = get_logger("replenishment.workflow")


def register_replenishment_workflow(engine: WorkflowEngine) -> None:
    """Register a simple workflow that creates replenishment when low-stock payload is received.

    Expected payload structure:
      {"items": [{"product_id": "X", "qty": 10}, ...]}
    """
    action = CreateReplenishmentAction()

    def step_prepare(ctx: Dict[str, Any]) -> Dict[str, Any]:
        # validate and normalize
        items = ctx.get("items") or []
        normalized = []
        for i in items:
            normalized.append({"product_id": str(i.get("product_id")), "qty": int(i.get("qty") or 0)})
        return {"items": normalized}

    engine.register("replenishment.create", [step_prepare, action])
    logger.info("replenishment.create workflow registered")
