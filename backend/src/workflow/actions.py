from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
from src.logging.agent_logger import get_logger


class Action:
    """Base action interface for workflow steps.

    Implementations should override `execute(context)` and may return
    a dict with results or raise an exception on failure.
    """

    name: str = "base_action"

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()


@dataclass
class CreateReplenishmentAction(Action):
    name: str = "create_replenishment"

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        logger = get_logger("CreateReplenishmentAction")
        # Expect context to contain `items` (list of dicts with product_id, qty)
        items = context.get("items") or []
        if not items:
            logger.info("no items to replenish")
            return {"created": 0}

        # In production this would create DB records or call an external procurement service.
        # Here we simulate creation and return a simple payload.
        created = []
        for it in items:
            created.append({"product_id": it.get("product_id"), "qty": it.get("qty"), "status": "created"})

        logger.info(f"created {len(created)} replenishment requests")
        return {"created": len(created), "requests": created}


__all__ = ["Action", "CreateReplenishmentAction"]
