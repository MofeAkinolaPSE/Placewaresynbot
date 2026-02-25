import os
import json
import uuid
import time
import asyncio
from typing import Dict, Any, List
from typing import Optional

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")
JOBS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "workflow_jobs.json")
TASKS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "staff_tasks.json")


class WorkflowEngine:
    STATES = ("draft", "submitted", "pending", "approved", "executed", "closed")

    def __init__(self):
        self._ensure_files()

    def _ensure_files(self):
        parent = os.path.dirname(JOBS_PATH)
        if not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(JOBS_PATH):
            with open(JOBS_PATH, "w", encoding="utf-8") as fh:
                json.dump([], fh)

    def _load_jobs(self) -> List[Dict[str, Any]]:
        try:
            with open(JOBS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return []

    def _write_jobs(self, jobs: List[Dict[str, Any]]):
        with open(JOBS_PATH, "w", encoding="utf-8") as fh:
            json.dump(jobs, fh, default=str, indent=2)

    def _read_ledger(self) -> List[Dict[str, Any]]:
        items = []
        if not os.path.exists(LEDGER_PATH):
            return items
        with open(LEDGER_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        return items

    def discover_and_enqueue(self) -> int:
        """Scan ledger for events and create workflow jobs for new events."""
        ledger = self._read_ledger()
        jobs = self._load_jobs()
        existing_event_ids = {j.get("event_id") for j in jobs}
        created = 0
        for ev in ledger:
            ev_id = ev.get("event_id") or ev.get("version_hash")
            if not ev_id:
                continue
            if ev_id in existing_event_ids:
                continue
            job = self._create_job_from_event(ev)
            jobs.append(job)
            existing_event_ids.add(ev_id)
            created += 1
        if created:
            self._write_jobs(jobs)
        return created

    def _create_job_from_event(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        ev_id = ev.get("event_id") or ev.get("version_hash")
        approval_req = False
        # Simple heuristic: if event payload contains approval_required True or approval_status == 'pending'
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and payload.get("approval_required"):
            approval_req = True
        if ev.get("approval_status") == "pending":
            approval_req = True

        job = {
            "job_id": str(uuid.uuid4()),
            "event_id": ev_id,
            "department": ev.get("department"),
            "event_type": ev.get("event_type"),
            "created_at": ev.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "state": "pending" if approval_req else "submitted",
            "approval_required": approval_req,
            "approvals": [],
            "attempts": 0,
            "last_error": None,
            "payload": payload,
        }
        # create a follow-up task for approvals if needed
        if approval_req:
            try:
                self._create_task_for_job(job)
            except Exception:
                pass
        return job

    def _create_task_for_job(self, job: Dict[str, Any]) -> None:
        # create a lightweight follow-up task to be shown on staff dashboards
        tasks = []
        try:
            if os.path.exists(TASKS_PATH):
                with open(TASKS_PATH, "r", encoding="utf-8") as fh:
                    tasks = json.load(fh)
        except Exception:
            tasks = []
        t = {
            "task_id": f"wf-{job.get('job_id')}",
            "title": f"Approve {job.get('event_type')} ({job.get('department')})",
            "description": "Workflow approval required",
            "assigned_to": f"role:manager:{job.get('department')}",
            "status": "open",
            "due_date": None,
        }
        tasks.append(t)
        try:
            parent = os.path.dirname(TASKS_PATH)
            if not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            with open(TASKS_PATH, "w", encoding="utf-8") as fh:
                json.dump(tasks, fh, indent=2)
        except Exception:
            pass

    def list_jobs(self) -> List[Dict[str, Any]]:
        return self._load_jobs()

    def get_job(self, job_id: str) -> Dict[str, Any] | None:
        jobs = self._load_jobs()
        for j in jobs:
            if j.get("job_id") == job_id:
                return j
        return None

    def approve_job(self, job_id: str, approver: str) -> bool:
        jobs = self._load_jobs()
        for j in jobs:
            if j.get("job_id") == job_id:
                if not j.get("approval_required"):
                    return False
                j.setdefault("approvals", []).append({"approver": approver, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")})
                j["state"] = "approved"
                self._write_jobs(jobs)
                # audit
                try:
                    from src.db import audit_event

                    audit_event(
                        "workflow_job_approved",
                        {"job_id": job_id, "approver": approver},
                        actor_id=approver,
                        event_class="workflow",
                        action="approve",
                        outcome="approved",
                        subject_type="workflow_job",
                        subject_id=job_id,
                    )
                except Exception:
                    pass
                return True
        return False

    def _process_job(self, job: Dict[str, Any]) -> bool:
        # Placeholder for the real workflow tasks: call services, update DB, trigger agents
        try:
            job["attempts"] = job.get("attempts", 0) + 1
            # Simulate execution
            time.sleep(0.01)
            job["state"] = "executed"
            job["executed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            job["last_error"] = None
            # audit
            try:
                from src.db import audit_event

                audit_event(
                    "workflow_job_executed",
                    {"job_id": job.get("job_id"), "event_id": job.get("event_id")},
                    actor_id=None,
                    event_class="workflow",
                    action="execute",
                    outcome="success",
                    subject_type="workflow_job",
                    subject_id=job.get("job_id"),
                )
            except Exception:
                pass
            return True
        except Exception as e:
            job["last_error"] = str(e)
            return False

    async def run_processor(self, interval_seconds: int = 5):
        """Background processor: discover, process non-approved jobs when ready."""
        while True:
            try:
                self.discover_and_enqueue()
                jobs = self._load_jobs()
                changed = False
                for j in jobs:
                    if j.get("state") in ("submitted", "approved"):
                        ok = self._process_job(j)
                        changed = changed or ok
                if changed:
                    self._write_jobs(jobs)
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)


# Singleton engine
engine = WorkflowEngine()
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import traceback
from src.logging.agent_logger import get_logger


logger = get_logger("workflow.engine")


@dataclass
class WorkflowContext:
    payload: Dict[str, Any]
    env: Dict[str, Any] = field(default_factory=dict)


class WorkflowEngine:
    """Tiny workflow engine to register triggers and run action sequences.

    - `register(trigger, steps)` registers a workflow where `steps` is a list
      of callables/actions that accept a WorkflowContext and return dict results.
    - `run(trigger, payload)` executes the steps sequentially and returns
      aggregated results.
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
                    # Action-like
                    res = step.execute({**ctx.payload, **ctx.env})
                else:
                    res = step(ctx)
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(f"workflow '{trigger}' step {idx} failed: {exc}\n{tb}")
                results["steps"].append({"index": idx, "error": str(exc)})
                results.setdefault("errors", []).append({"index": idx, "error": str(exc)})
                # stop on failure
                break
            results["steps"].append({"index": idx, "result": res})

        return results


__all__ = ["WorkflowEngine", "WorkflowContext"]
