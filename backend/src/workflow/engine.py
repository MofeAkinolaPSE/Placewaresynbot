from __future__ import annotations

import traceback
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.logging.agent_logger import get_logger

logger = get_logger("workflow.engine")
LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")


@dataclass
class WorkflowContext:
    payload: Dict[str, Any]
    env: Dict[str, Any] = field(default_factory=dict)


class WorkflowEngine:
    """Trigger-driven workflow engine.

    - `register(trigger, steps)` stores a list of callable steps.
    - `run(trigger, payload)` executes steps sequentially.
    - `enqueue(trigger, payload)` executes immediately and writes audit trail.
    """

    def __init__(self) -> None:
        self._workflows: Dict[str, List[Callable[[WorkflowContext], Dict[str, Any]]]] = {}

    def register(self, trigger: str, steps: List[Callable[[WorkflowContext], Dict[str, Any]]]) -> None:
        self._workflows[trigger] = steps
        logger.info(f"registered workflow '{trigger}' with {len(steps)} steps")

    def run(self, trigger: str, payload: Dict[str, Any], env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        steps = self._workflows.get(trigger)
        if not steps:
            logger.warning(f"no workflow registered for trigger '{trigger}'")
            return {"error": "no_workflow"}

        ctx = WorkflowContext(payload=payload, env=env or {})
        results: Dict[str, Any] = {"steps": []}

        for idx, step in enumerate(steps):
            try:
                if hasattr(step, "execute"):
                    res = step.execute({**ctx.payload, **ctx.env})
                else:
                    res = step(ctx)
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(f"workflow '{trigger}' step {idx} failed: {exc}\n{tb}")
                results["steps"].append({"index": idx, "error": str(exc)})
                results.setdefault("errors", []).append({"index": idx, "error": str(exc)})
                break
            results["steps"].append({"index": idx, "result": res})

        return results

    def enqueue(self, trigger: str, payload: Dict[str, Any]) -> str:
        import time
        import uuid

        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "trigger": trigger,
            "payload": payload,
            "state": "queued",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "attempts": 0,
        }

        if trigger in self._workflows:
            logger.info(f"Executing queued workflow '{trigger}' with job_id={job_id}")
            result = self.run(trigger, payload)
            job["state"] = "executed" if "error" not in result else "failed"
            job["result"] = result
        else:
            logger.info(f"Queued workflow '{trigger}' with job_id={job_id} (no handler registered)")
            job["state"] = "queued_no_handler"

        try:
            from src.db import audit_event

            audit_event(
                "workflow_job_enqueued",
                {"job_id": job_id, "trigger": trigger, "payload": payload},
                actor_id=None,
                event_class="workflow",
                action="enqueue",
                outcome=job["state"],
                subject_type="workflow_job",
                subject_id=job_id,
            )
        except Exception:
            pass

        return job_id


__all__ = ["WorkflowEngine", "WorkflowContext"]
