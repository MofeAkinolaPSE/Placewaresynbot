from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")
JOBS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "workflow_jobs.json")
TASKS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "staff_tasks.json")


class WorkflowJobsEngine:
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

    def _read_event_ledger_db(self, limit: int = 500) -> List[Dict[str, Any]]:
        try:
            from src.db import db

            resp = (
                db.table("event_ledger")
                .select("event_id,department,event_type,payload,approval_status,created_by,created_at")
                .order("created_at", desc=True)
                .limit(max(1, min(limit, 5000)))
                .execute()
            )
            return list(reversed(resp.data or []))
        except Exception:
            return []

    def _compute_escalation_due_at(self, now_iso: str, payload: Dict[str, Any], trigger: str | None = None) -> str | None:
        import datetime as _dt

        escalation_minutes = payload.get("escalation_minutes")
        if escalation_minutes is None:
            escalation_minutes = 120 if (trigger or "").startswith("compliance") else 240
        try:
            mins = int(escalation_minutes)
            if mins <= 0:
                return None
            base = _dt.datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
            due = base + _dt.timedelta(minutes=mins)
            return due.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return None

    def _escalation_role_for_job(self, department: str | None, payload: Dict[str, Any], explicit_role: str | None = None) -> str:
        if explicit_role:
            return explicit_role
        role = payload.get("escalation_role")
        if isinstance(role, str) and role.strip():
            return role.strip()
        dep = (department or "").strip().lower() or "ops"
        return f"role:management:{dep}"

    def discover_and_enqueue(self) -> int:
        ledger = self._read_event_ledger_db()
        if not ledger:
            ledger = self._read_ledger()
        jobs = self._load_jobs()
        existing_event_ids = {j.get("event_id") for j in jobs}
        created = 0
        for ev in ledger:
            ev_id = ev.get("event_id") or ev.get("version_hash")
            if not ev_id or ev_id in existing_event_ids:
                continue
            jobs.append(self._create_job_from_event(ev))
            existing_event_ids.add(ev_id)
            created += 1
        if created:
            self._write_jobs(jobs)
        return created

    def _create_job_from_event(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        ev_id = ev.get("event_id") or ev.get("version_hash")
        payload = ev.get("payload") or {}
        approval_req = bool(
            (isinstance(payload, dict) and payload.get("approval_required"))
            or ev.get("approval_status") == "pending"
        )

        created_at = ev.get("timestamp") or ev.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ")
        escalation_due_at = self._compute_escalation_due_at(created_at, payload)
        escalation_role = self._escalation_role_for_job(ev.get("department"), payload)

        job = {
            "job_id": str(uuid.uuid4()),
            "event_id": ev_id,
            "department": ev.get("department"),
            "event_type": ev.get("event_type"),
            "trigger": f"event.{ev.get('department')}.{ev.get('event_type')}",
            "created_at": created_at,
            "state": "pending" if approval_req else "submitted",
            "approval_required": approval_req,
            "approvals": [],
            "attempts": 0,
            "last_error": None,
            "payload": payload,
            "escalation_role": escalation_role,
            "escalation_due_at": escalation_due_at,
            "escalated": False,
            "escalated_at": None,
        }
        if approval_req:
            self._create_task_for_job(job)
        return job

    def enqueue_trigger(
        self,
        *,
        trigger: str,
        event_id: str,
        payload: Dict[str, Any],
        department: str,
        event_type: str,
        escalation_role: str | None = None,
    ) -> str:
        jobs = self._load_jobs()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        approval_req = bool(payload.get("approval_required") or payload.get("approval_status") == "pending")
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "trigger": trigger,
            "event_id": event_id,
            "department": department,
            "event_type": event_type,
            "created_at": now_iso,
            "state": "pending" if approval_req else "submitted",
            "approval_required": approval_req,
            "approvals": [],
            "attempts": 0,
            "last_error": None,
            "payload": payload,
            "escalation_role": self._escalation_role_for_job(department, payload, escalation_role),
            "escalation_due_at": self._compute_escalation_due_at(now_iso, payload, trigger=trigger),
            "escalated": False,
            "escalated_at": None,
        }
        if approval_req:
            self._create_task_for_job(job)
        jobs.append(job)
        self._write_jobs(jobs)
        return job_id

    def _create_task_for_job(self, job: Dict[str, Any]) -> None:
        tasks = []
        try:
            if os.path.exists(TASKS_PATH):
                with open(TASKS_PATH, "r", encoding="utf-8") as fh:
                    tasks = json.load(fh)
        except Exception:
            tasks = []
        tasks.append(
            {
                "task_id": f"wf-{job.get('job_id')}",
                "title": f"Approve {job.get('event_type')} ({job.get('department')})",
                "description": "Workflow approval required",
                "assigned_to": job.get("escalation_role") or f"role:manager:{job.get('department')}",
                "status": "open",
                "due_date": job.get("escalation_due_at"),
            }
        )
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
        for job in jobs:
            if job.get("job_id") == job_id:
                return job
        return None

    def approve_job(self, job_id: str, approver: str) -> bool:
        jobs = self._load_jobs()
        for job in jobs:
            if job.get("job_id") != job_id:
                continue
            if not job.get("approval_required"):
                return False
            job.setdefault("approvals", []).append({"approver": approver, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")})
            job["state"] = "approved"
            self._write_jobs(jobs)
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

    def reject_job(self, job_id: str, rejecter: str) -> bool:
        jobs = self._load_jobs()
        for job in jobs:
            if job.get("job_id") != job_id:
                continue
            if job.get("state") not in ("pending", "submitted", "approved"):
                return False
            job.setdefault("rejections", []).append({"rejecter": rejecter, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")})
            job["state"] = "rejected"
            self._write_jobs(jobs)
            try:
                from src.db import audit_event

                audit_event(
                    "workflow_job_rejected",
                    {"job_id": job_id, "rejecter": rejecter},
                    actor_id=rejecter,
                    event_class="workflow",
                    action="reject",
                    outcome="rejected",
                    subject_type="workflow_job",
                    subject_id=job_id,
                )
            except Exception:
                pass
            return True
        return False

    def _escalate_overdue_jobs(self) -> int:
        import datetime as _dt

        jobs = self._load_jobs()
        changed = False
        escalated_count = 0
        now = _dt.datetime.utcnow()

        for job in jobs:
            if job.get("state") not in ("pending", "submitted"):
                continue
            if job.get("escalated"):
                continue
            due_at = job.get("escalation_due_at")
            if not due_at:
                continue
            try:
                due = _dt.datetime.fromisoformat(str(due_at).replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue
            if due <= now:
                job["escalated"] = True
                job["escalated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                escalated_count += 1
                changed = True

        if changed:
            self._write_jobs(jobs)
        return escalated_count

    def bottleneck_metrics(self) -> Dict[str, Any]:
        import datetime as _dt

        jobs = self._load_jobs()
        waiting = [j for j in jobs if j.get("state") in ("pending", "submitted")]
        now = _dt.datetime.utcnow()

        overdue = 0
        by_department: Dict[str, int] = {}
        by_trigger: Dict[str, int] = {}
        for job in waiting:
            dept = str(job.get("department") or "unknown")
            by_department[dept] = by_department.get(dept, 0) + 1
            trigger = str(job.get("trigger") or "unknown")
            by_trigger[trigger] = by_trigger.get(trigger, 0) + 1

            due_at = job.get("escalation_due_at")
            if due_at:
                try:
                    due = _dt.datetime.fromisoformat(str(due_at).replace("Z", "+00:00")).replace(tzinfo=None)
                    if due <= now:
                        overdue += 1
                except Exception:
                    pass

        return {
            "total_jobs": len(jobs),
            "waiting_jobs": len(waiting),
            "overdue_waiting_jobs": overdue,
            "by_department": by_department,
            "by_trigger": by_trigger,
        }

    def run_escalation_pass(self) -> Dict[str, Any]:
        escalated = self._escalate_overdue_jobs()
        return {
            "escalated": escalated,
            "metrics": self.bottleneck_metrics(),
        }

    def _process_job(self, job: Dict[str, Any]) -> bool:
        try:
            job["attempts"] = job.get("attempts", 0) + 1
            time.sleep(0.01)
            job["state"] = "executed"
            job["executed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            job["last_error"] = None
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
        except Exception as exc:
            job["last_error"] = str(exc)
            return False

    async def run_processor(self, interval_seconds: int = 5):
        while True:
            try:
                self.discover_and_enqueue()
                self._escalate_overdue_jobs()
                jobs = self._load_jobs()
                changed = False
                for job in jobs:
                    if job.get("state") in ("submitted", "approved"):
                        changed = self._process_job(job) or changed
                if changed:
                    self._write_jobs(jobs)
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)


engine = WorkflowJobsEngine()
