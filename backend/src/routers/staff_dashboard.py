from fastapi import APIRouter, HTTPException, Request, Depends
from src.schemas.staff_dashboard import StaffDashboard, ActivityItem, PendingApproval, TaskItem, KPIWidget, Badge, AssignedProjectItem
from src.middleware import verify_jwt, require_role
from typing import List
import os, json, logging
import datetime as dt
from src.db import db

router = APIRouter()
logger = logging.getLogger(__name__)

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")
TASKS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "staff_tasks.json")


def _read_ledger_items():
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


def _read_tasks():
    if not os.path.exists(TASKS_PATH):
        return []
    try:
        with open(TASKS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _write_tasks(tasks: list):
    parent = os.path.dirname(TASKS_PATH)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(TASKS_PATH, "w", encoding="utf-8") as fh:
        json.dump(tasks, fh, indent=2)


@router.get("/staff/{user_id}/dashboard", response_model=StaffDashboard)
async def get_staff_dashboard(request: Request, user_id: str):
    # Auth: allow owner or admin/manager
    payload = verify_jwt(request)
    sub = payload.get("sub") or payload.get("user_id")
    roles = set(payload.get("roles") or [])
    if not (sub == user_id or "admin" in roles or "manager" in roles or "management" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role to access dashboard")
    # Build activity feed from ledger (most recent 25)
    ledger = _read_ledger_items()
    activities = []
    pending = []
    for ev in reversed(ledger[-500:]):
        # match created_by or linked_customer_id as quick heuristics
        created_by = ev.get("created_by")
        if created_by == user_id:
            activities.append(ActivityItem(
                event_id=ev.get("event_id"),
                timestamp=ev.get("timestamp"),
                department=ev.get("department"),
                event_type=ev.get("event_type"),
                summary=(ev.get("payload") and ev.get("payload").get("summary")) or ev.get("event_type"),
                payload=ev.get("payload") or {},
            ))
        # collect pending approvals relevant to this user (simple heuristic: department match)
        if ev.get("approval_status") == "pending" and ev.get("department") and created_by != user_id:
            # lightweight; real logic should consult workflow definitions/roles
            pending.append(PendingApproval(
                event_id=ev.get("event_id"),
                event_type=ev.get("event_type"),
                created_by=created_by,
                timestamp=ev.get("timestamp"),
                reason=(ev.get("payload") or {}).get("reason") if isinstance(ev.get("payload"), dict) else None,
            ))

    activities = activities[:25]

    # Tasks assigned to user — merge JSON file + Supabase placeware_tasks
    raw_tasks = _read_tasks()
    tasks = []
    seen_task_ids: set = set()
    for t in raw_tasks:
        if str(t.get("assigned_to")) == str(user_id):
            tid = t.get("task_id")
            if tid:
                seen_task_ids.add(str(tid))
            tasks.append(TaskItem(
                task_id=tid or f"json-{len(tasks)}",
                title=t.get("title"),
                description=t.get("description"),
                assigned_to=t.get("assigned_to"),
                status=t.get("status"),
                due_date=t.get("due_date"),
            ))

    # Pull tasks from Supabase placeware_tasks table
    try:
        supabase_tasks = (
            db.table("placeware_tasks")
            .select("id,title,description,assigned_to,status,priority,due_date")
            .eq("assigned_to", user_id)
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        ).data or []
        for t in supabase_tasks:
            tid = str(t.get("id") or "")
            if tid in seen_task_ids:
                continue  # de-dupe
            seen_task_ids.add(tid)
            tasks.append(TaskItem(
                task_id=tid,
                title=t.get("title") or "Untitled",
                description=t.get("description"),
                assigned_to=t.get("assigned_to"),
                status=t.get("status") or "pending",
                priority=t.get("priority"),
                due_date=str(t.get("due_date")) if t.get("due_date") else None,
            ))
    except Exception as exc:
        logger.warning(f"Could not query placeware_tasks for user {user_id}: {exc}")

    assigned_projects: List[AssignedProjectItem] = []
    try:
        project_rows = (
            db.table("placeware_projects")
            .select("id,name,status,workflow_stage,activity_type,supplier_name,quality_check_status,nafdac_sampling_status,updated_at")
            .eq("assigned_staff_id", user_id)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
        ).data or []
        for row in project_rows:
            assigned_projects.append(
                AssignedProjectItem(
                    project_id=str(row.get("id") or ""),
                    name=str(row.get("name") or "Untitled Project"),
                    status=str(row.get("status") or "unknown"),
                    workflow_stage=row.get("workflow_stage"),
                    activity_type=row.get("activity_type"),
                    supplier_name=row.get("supplier_name"),
                    quality_check_status=row.get("quality_check_status"),
                    nafdac_sampling_status=row.get("nafdac_sampling_status"),
                    updated_at=row.get("updated_at"),
                )
            )
    except Exception:
        assigned_projects = []

    # KPIs (example minimal set)
    kpis: List[KPIWidget] = []
    kpis.append(KPIWidget(key="tasks_open", label="Open Tasks", value=sum(1 for t in tasks if t.status != "done")))
    kpis.append(KPIWidget(key="approvals_pending", label="Pending Approvals", value=len(pending)))
    kpis.append(KPIWidget(key="projects_assigned_open", label="Open Assigned Projects", value=sum(1 for p in assigned_projects if p.status not in {"completed", "cancelled"})))

    # Badges (very small rule set)
    badges: List[Badge] = []
    if len([t for t in tasks if t.status == "done"]) >= 10:
        badges.append(Badge(id="task_master", name="Task Master", description="Completed 10+ tasks"))

    dashboard = StaffDashboard(
        user_id=user_id,
        activities=activities,
        pending_approvals=pending[:10],
        tasks=tasks,
        assigned_projects=assigned_projects,
        kpis=kpis,
        badges=badges,
    )

    return dashboard


@router.post("/staff/{user_id}/tasks", status_code=201)
async def create_task(request: Request, user_id: str, task: dict):
    # Auth: only creator or admin/manager can create tasks for a user
    payload = verify_jwt(request)
    sub = payload.get("sub") or payload.get("user_id")
    roles = set(payload.get("roles") or [])
    if not (sub == user_id or "admin" in roles or "manager" in roles or "management" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role to create task")
    tasks = _read_tasks()
    new = {
        "task_id": task.get("task_id") or f"task-{int(dt.datetime.utcnow().timestamp())}",
        "title": task.get("title"),
        "description": task.get("description"),
        "assigned_to": user_id,
        "status": task.get("status") or "open",
        "due_date": task.get("due_date"),
    }
    tasks.append(new)
    _write_tasks(tasks)
    return {"status": "created", "task": new}


@router.put("/staff/{user_id}/tasks/{task_id}")
async def update_task(request: Request, user_id: str, task_id: str, patch: dict):
    payload = verify_jwt(request)
    sub = payload.get("sub") or payload.get("user_id")
    roles = set(payload.get("roles") or [])
    tasks = _read_tasks()
    found = False
    for t in tasks:
        if t.get("task_id") == task_id and str(t.get("assigned_to")) == str(user_id):
            # allow owner or admin/manager
            if not (sub == user_id or "admin" in roles or "manager" in roles or "management" in roles):
                raise HTTPException(status_code=403, detail="Insufficient role to update task")
            t.update(patch)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Task not found")
    _write_tasks(tasks)
    return {"status": "updated", "task": t}


@router.delete("/staff/{user_id}/tasks/{task_id}")
async def delete_task(request: Request, user_id: str, task_id: str):
    payload = verify_jwt(request)
    sub = payload.get("sub") or payload.get("user_id")
    roles = set(payload.get("roles") or [])
    tasks = _read_tasks()
    new_tasks = []
    deleted = None
    for t in tasks:
        if t.get("task_id") == task_id and str(t.get("assigned_to")) == str(user_id):
            if not (sub == user_id or "admin" in roles or "manager" in roles or "management" in roles):
                raise HTTPException(status_code=403, detail="Insufficient role to delete task")
            deleted = t
            continue
        new_tasks.append(t)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    _write_tasks(new_tasks)
    return {"status": "deleted", "task": deleted}
