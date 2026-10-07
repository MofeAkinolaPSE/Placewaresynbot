"""Staff Workspace: each team member's home in ACE.

One place to start the day and do the work - not a page of company metrics:

  My Day      what needs me today: my tasks and reminders, requests waiting on me,
              operational items for my role, the work clock.
  My Work     tasks, reminders and notes I keep for myself or was given
              (to do / in progress / waiting / done), each with a checklist and history.
  Inbox       requests to me or my department, answers to mine, mentions, assignments.
  Team        who is here (online + on the clock), what they are carrying, and
              message / ask / assign in place.
  Progress    my own outcomes - what I finished, on time, requests handled, hours.

Everything a person does is recorded once and read everywhere: completing a task
moves the Progress numbers, clocking out writes the timesheet HR sees, a request
lands in the other person's Inbox, an operational item taken as a task closes
itself when the record is dealt with in its module.

Identity is the login (placeware_users). The HR profile (placeware_staff) is linked
by user_id and created on first use, so everyone set up on User Access is on the
team and in HR.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from src.fin.db import ex, q, q1, tx

TZ = ZoneInfo("Africa/Lagos")

DEPARTMENTS = ["Finance", "Sales", "Frontdesk", "Operations", "Procurement", "Logistics", "Quality", "HR", "Management", "Admin"]
# the login roles that make someone part of a department (for department requests and defaults)
DEPT_ROLES: Dict[str, set] = {
    "Finance": {"finance"}, "Sales": {"sales", "crm"}, "Frontdesk": {"frontdesk"}, "Operations": {"ops", "operations"},
    "Procurement": {"procurement"}, "Logistics": {"logistics", "rider"}, "Quality": {"quality_assurance", "qa"},
    "HR": {"hr"}, "Management": {"management", "manager"}, "Admin": {"admin"},
}
MANAGER_ROLES = {"admin", "management", "manager", "hr"}
OPEN_STATUSES = ("pending", "in_progress", "waiting", "blocked")
TRANSITIONS = {
    "pending": {"in_progress", "waiting", "completed", "cancelled"},
    "in_progress": {"pending", "waiting", "completed", "cancelled"},
    "waiting": {"in_progress", "pending", "completed", "cancelled"},
    "blocked": {"in_progress", "pending", "completed", "cancelled"},
    "completed": {"pending"},     # reopen
    "cancelled": {"pending"},
}
STATUS_LABEL = {"pending": "to do", "in_progress": "in progress", "waiting": "waiting", "completed": "done",
                "cancelled": "cancelled", "blocked": "blocked"}


class WorkspaceError(ValueError):
    """A request that cannot be carried out as asked (409)."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def today() -> dt.date:
    return now().astimezone(TZ).date()


def week_start(d: Optional[dt.date] = None) -> dt.date:
    d = d or today()
    return d - dt.timedelta(days=d.weekday())


def local_midnight(d: dt.date) -> dt.datetime:
    return dt.datetime.combine(d, dt.time(), TZ)


def _is_uuid(v: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", str(v or "")))


def _me(user: Dict[str, Any]) -> str:
    sub = str(user.get("sub") or "")
    if not _is_uuid(sub):
        raise PermissionError("Sign in with a staff account to use the workspace")
    return sub


def _roles(user: Dict[str, Any]) -> set:
    return {str(r).lower() for r in (user.get("roles") or [])}


def _dt(v: Any) -> Optional[dt.datetime]:
    """Parse a date or datetime from the browser. A bare date means end of that working day."""
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=TZ)
    s = str(v).strip()
    if len(s) == 10:
        return dt.datetime.combine(dt.date.fromisoformat(s), dt.time(17, 0), TZ)
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def name_from_email(email: str) -> str:
    local = (email or "").split("@")[0]
    parts = [p for p in re.split(r"[._-]+", local) if p and not p.isdigit()]
    return " ".join(p.capitalize() for p in parts) if parts else (email or "Team member")


def dept_for_roles(roles: Iterable[str]) -> str:
    rs = {str(r).lower() for r in roles or []}
    for dept in ("Finance", "Sales", "Frontdesk", "Quality", "HR", "Procurement", "Logistics", "Operations", "Management", "Admin"):
        if rs & DEPT_ROLES[dept]:
            return dept
    return "Operations"


def fmt_hours(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60}h {m % 60:02d}m"


def journal(conn, user_id: str, kind: str, summary: str, entity_type: Optional[str] = None, entity_id: Optional[str] = None) -> None:
    ex(conn, """INSERT INTO staff_work_events (user_id, kind, summary, entity_type, entity_id) VALUES (%s, %s, %s, %s, %s)""",
       (user_id, kind, summary[:300], entity_type, entity_id))


def notify(conn, user_ids: Iterable[Optional[str]], kind: str, level: str, title: str, body: Optional[str] = None,
           link_type: Optional[str] = None, link_id: Optional[str] = None, actor: Optional[str] = None) -> int:
    n = 0
    for uid in {str(u) for u in user_ids if u and _is_uuid(u)}:
        if actor and uid == str(actor):
            continue
        ex(conn, """INSERT INTO staff_notifications (user_id, kind, level, title, body, link_type, link_id, actor)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
           (uid, kind, level, title[:300], (body or "")[:1000] or None, link_type, link_id, actor))
        n += 1
    return n


# ---------------------------------------------------------------------------
# People (login + HR profile)
# ---------------------------------------------------------------------------

_PEOPLE_SQL = """
    SELECT u.id::text AS user_id, u.email, u.roles, u.is_active, u.created_at AS joined_at,
           s.staff_id::text AS staff_id, s.full_name, s.department AS staff_department, s.role AS job_title, s.phone,
           s.branch, s.status AS staff_status, s.weekly_hours, s.start_date
    FROM placeware_users u LEFT JOIN placeware_staff s ON s.user_id = u.id
    UNION ALL
    SELECT NULL, s.email, NULL, NULL, s.created_at, s.staff_id::text, s.full_name, s.department, s.role, s.phone,
           s.branch, s.status, s.weekly_hours, s.start_date
    FROM placeware_staff s WHERE s.user_id IS NULL
"""


def _person(r: Dict[str, Any]) -> Dict[str, Any]:
    roles = list(r.get("roles") or [])
    has_login = r["user_id"] is not None
    email = r.get("email") or ""
    placeholder = email.endswith("@placeholder.local")
    return {
        "key": r["user_id"] or f"staff:{r['staff_id']}",
        "user_id": r["user_id"], "staff_id": r["staff_id"], "has_login": has_login,
        "name": r.get("full_name") or name_from_email(email),
        "email": None if placeholder else email,
        "roles": roles,
        "department": r.get("staff_department") or (dept_for_roles(roles) if has_login else "Operations"),
        "job_title": r.get("job_title"), "phone": r.get("phone"), "branch": r.get("branch"),
        "weekly_hours": float(r["weekly_hours"]) if r.get("weekly_hours") is not None else 40.0,
        "start_date": r.get("start_date"),
        "active": bool(r["is_active"]) if has_login else (r.get("staff_status") or "active") == "active",
        "profile": r["staff_id"] is not None,
        "joined_at": r.get("joined_at"),
    }


def people(conn, include_inactive: bool = False) -> List[Dict[str, Any]]:
    out = [_person(r) for r in q(conn, _PEOPLE_SQL)]
    if not include_inactive:
        out = [p for p in out if p["active"]]
    return sorted(out, key=lambda p: p["name"].lower())


def person_map(conn) -> Dict[str, Dict[str, Any]]:
    return {p["key"]: p for p in people(conn, include_inactive=True)}


def ensure_profile(conn, user_id: str) -> str:
    """The HR profile for a login - linked by email if HR already added them, created otherwise."""
    r = q1(conn, "SELECT staff_id::text AS staff_id FROM placeware_staff WHERE user_id=%s", (user_id,))
    if r:
        return r["staff_id"]
    u = q1(conn, "SELECT email, roles FROM placeware_users WHERE id=%s", (user_id,))
    if not u:
        raise LookupError("User not found")
    r = q1(conn, """UPDATE placeware_staff SET user_id=%s, updated_at=now() WHERE lower(email)=lower(%s) AND user_id IS NULL
                    RETURNING staff_id::text AS staff_id""", (user_id, u["email"]))
    if r:
        return r["staff_id"]
    r = q1(conn, """INSERT INTO placeware_staff (full_name, email, department, status, user_id)
                    VALUES (%s, %s, %s, 'active', %s) RETURNING staff_id::text AS staff_id""",
           (name_from_email(u["email"]), u["email"].lower(), dept_for_roles(u["roles"]), user_id))
    return r["staff_id"]


def online_ids() -> set:
    try:
        from src.services.presence_service import get_online_users
        return {str(u["user_id"]) for u in get_online_users()}
    except Exception:
        return set()


def _names(conn, ids: Iterable[Any]) -> Dict[str, str]:
    pm = person_map(conn)
    return {str(i): (pm[str(i)]["name"] if str(i) in pm else "Someone") for i in ids if i}


def _dept_members(conn, dept: str) -> List[str]:
    return [p["user_id"] for p in people(conn) if p["user_id"] and p["department"] == dept]


# ---------------------------------------------------------------------------
# Time clock -> timesheets
# ---------------------------------------------------------------------------

def _session_row(conn, user_id: str, lock: bool = False) -> Optional[Dict[str, Any]]:
    return q1(conn, f"""SELECT id::text AS id, user_id::text AS user_id, started_at, break_seconds, break_started_at, breaks,
                               department, note FROM staff_time_sessions WHERE user_id=%s AND ended_at IS NULL
                        {'FOR UPDATE' if lock else ''}""", (user_id,))


def _worked_seconds(s: Dict[str, Any], at: Optional[dt.datetime] = None) -> float:
    at = at or now()
    brk = s["break_seconds"] + ((at - s["break_started_at"]).total_seconds() if s.get("break_started_at") else 0)
    return max(0.0, (at - s["started_at"]).total_seconds() - brk)


def clock_view(conn, user_id: str) -> Dict[str, Any]:
    s = _session_row(conn, user_id)
    t0 = local_midnight(today())
    saved_today = q1(conn, """SELECT COALESCE(SUM(hours_worked),0) AS h FROM placeware_timesheets
                              WHERE user_id=%s AND date=%s AND status<>'rejected'""", (user_id, today()))["h"]
    ws = week_start()
    saved_week = q1(conn, """SELECT COALESCE(SUM(hours_worked),0) AS h FROM placeware_timesheets
                             WHERE user_id=%s AND date BETWEEN %s AND %s AND status<>'rejected'""",
                    (user_id, ws, ws + dt.timedelta(days=6)))["h"]
    live = 0.0
    live_today = 0.0
    if s:
        live = _worked_seconds(s)
        # only the part of a running clock that falls today counts towards today
        live_today = live if s["started_at"] >= t0 else max(0.0, live - _worked_seconds(s, t0))
    return {
        "status": "off" if not s else ("break" if s["break_started_at"] else "working"),
        "session": None if not s else {
            "id": s["id"], "started_at": s["started_at"], "break_started_at": s["break_started_at"],
            "break_seconds": s["break_seconds"] + (int((now() - s["break_started_at"]).total_seconds()) if s["break_started_at"] else 0),
            "breaks": s["breaks"], "department": s["department"], "note": s["note"],
            "worked_seconds": int(live), "running_hours": round((now() - s["started_at"]).total_seconds() / 3600, 2),
        },
        "today_seconds": int(float(saved_today) * 3600 + live_today),
        "week_seconds": int(float(saved_week) * 3600 + live),
        "server_time": now(),
    }


def clock_start(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        staff_id = ensure_profile(conn, me)
        if _session_row(conn, me, lock=True):
            raise WorkspaceError("You are already clocked in")
        # Always the HR profile's department - the clock is filed under the person, not a choice made at clock-in.
        dept = q1(conn, "SELECT department FROM placeware_staff WHERE staff_id=%s", (staff_id,))["department"]
        ex(conn, """INSERT INTO staff_time_sessions (user_id, staff_id, department, note) VALUES (%s, %s, %s, %s)""",
           (me, staff_id, dept, (data.get("note") or "").strip() or None))
        journal(conn, me, "clock_in", "Started work")
        return clock_view(conn, me)


def clock_break(user: Dict[str, Any], resume: bool = False) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        s = _session_row(conn, me, lock=True)
        if not s:
            raise WorkspaceError("You are not clocked in")
        if resume:
            if not s["break_started_at"]:
                raise WorkspaceError("You are not on a break")
            ex(conn, """UPDATE staff_time_sessions SET break_seconds = break_seconds + EXTRACT(EPOCH FROM now()-break_started_at)::int,
                               break_started_at=NULL WHERE id=%s""", (s["id"],))
            journal(conn, me, "resume", "Back from break")
        else:
            if s["break_started_at"]:
                raise WorkspaceError("You are already on a break")
            ex(conn, "UPDATE staff_time_sessions SET break_started_at=now(), breaks=breaks+1 WHERE id=%s", (s["id"],))
            journal(conn, me, "break", "Took a break")
        return clock_view(conn, me)


def _split_by_day(start: dt.datetime, end: dt.datetime, worked: float) -> List[tuple]:
    """(local date, hours) for a session, split at local midnight; breaks shared out pro rata."""
    gross = (end - start).total_seconds()
    parts, cur = [], start
    while cur < end:
        nxt = min(end, local_midnight(cur.astimezone(TZ).date() + dt.timedelta(days=1)))
        parts.append((cur.astimezone(TZ).date(), (nxt - cur).total_seconds()))
        cur = nxt
    ratio = worked / gross if gross else 0
    return [(d, round(sec * ratio / 3600, 2)) for d, sec in parts if round(sec * ratio / 3600, 2) > 0]


def clock_stop(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Clock out: close the session and write it to the timesheet HR reviews."""
    me = _me(user)
    with tx() as conn:
        s = _session_row(conn, me, lock=True)
        if not s:
            raise WorkspaceError("You are not clocked in")
        end = _dt(data.get("ended_at")) or now()
        if end > now() + dt.timedelta(minutes=1) or end <= s["started_at"]:
            raise WorkspaceError("The finish time must be after you started and not in the future")
        if (end - s["started_at"]) > dt.timedelta(hours=16) and not data.get("ended_at"):
            raise WorkspaceError("NEEDS_END_TIME: This clock has been running for more than 16 hours. "
                                 "Enter the time you actually finished.")
        if s["break_started_at"]:
            s["break_seconds"] += max(0, int((end - s["break_started_at"]).total_seconds()))
            s["break_started_at"] = None
        worked = _worked_seconds(s, end)
        note = (data.get("note") or s["note"] or "").strip() or None
        staff_id = ensure_profile(conn, me)
        ids = []
        for d, hours in _split_by_day(s["started_at"], end, worked):
            r = q1(conn, """INSERT INTO placeware_timesheets (staff_id, user_id, date, hours_worked, department, activity_note,
                                                              recorded_by, source, session_id, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'clock', %s, 'submitted') RETURNING id""",
                   (staff_id, me, d, min(hours, 24), s["department"] or "Operations", note, me, s["id"]))
            ids.append(r["id"])
        ex(conn, """UPDATE staff_time_sessions SET ended_at=%s, break_seconds=%s, break_started_at=NULL, note=%s, timesheet_id=%s
                    WHERE id=%s""", (end, s["break_seconds"], note, ids[0] if ids else None, s["id"]))
        journal(conn, me, "clock_out", f"Finished work · {fmt_hours(worked)} recorded" if ids else "Finished work (under a minute, nothing recorded)")
        view = clock_view(conn, me)
        view["recorded_hours"] = round(worked / 3600, 2) if ids else 0
        view["timesheet_ids"] = ids
        return view


def my_time(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    ws = week_start()
    with tx() as conn:
        view = clock_view(conn, me)
        rows = q(conn, """SELECT id, date, hours_worked, department, activity_note, source, status, review_note
                          FROM placeware_timesheets WHERE user_id=%s AND date >= %s ORDER BY date DESC, id DESC""",
                 (me, ws - dt.timedelta(days=28)))
        sessions = q(conn, """SELECT id::text AS id, started_at, ended_at, break_seconds, breaks, note FROM staff_time_sessions
                              WHERE user_id=%s ORDER BY started_at DESC LIMIT 15""", (me,))
    days = []
    for i in range(7):
        d = ws + dt.timedelta(days=i)
        h = sum(float(r["hours_worked"]) for r in rows if r["date"] == d and r["status"] != "rejected")
        if d == today() and view["session"]:
            h += view["today_seconds"] / 3600 - sum(float(r["hours_worked"]) for r in rows if r["date"] == d and r["status"] != "rejected")
        days.append({"date": d, "hours": round(h, 2), "today": d == today()})
    weeks = []
    for w in range(4, -1, -1):
        s0 = ws - dt.timedelta(days=7 * w)
        weeks.append({"week": s0, "hours": round(sum(float(r["hours_worked"]) for r in rows
                                                      if s0 <= r["date"] <= s0 + dt.timedelta(days=6) and r["status"] != "rejected"), 2)})
    weeks[-1]["hours"] = round(view["week_seconds"] / 3600, 2)
    for s in sessions:
        end = s["ended_at"] or now()
        s["worked_seconds"] = int(max(0, (end - s["started_at"]).total_seconds() - s["break_seconds"]))
    return {**view, "days": days, "weeks": weeks, "entries": rows[:40], "sessions": sessions}


# ---------------------------------------------------------------------------
# Tasks, reminders and notes
# ---------------------------------------------------------------------------

_TASK_COLS = """t.id::text AS id, t.title, t.description, t.kind, t.status, t.priority, t.due_date, t.reminder_at,
    t.assigned_to::text AS assigned_to, t.created_by::text AS created_by, t.source, t.source_ref, t.department,
    t.entity_type, t.entity_id, t.entity_label, t.link, t.checklist, t.waiting_on, t.started_at, t.completed_at,
    t.completed_by::text AS completed_by, t.created_at, t.updated_at, t.request_id::text AS request_id,
    t.recurrence, t.recurrence_until, t.series_id::text AS series_id, t.escalation_level, t.escalated_to, t.escalated_at,
    (SELECT COUNT(*) FROM staff_task_activity a WHERE a.task_id=t.id AND a.kind='comment') AS comments"""


def _decorate(rows: List[Dict[str, Any]], names: Dict[str, str]) -> List[Dict[str, Any]]:
    t0, t1 = local_midnight(today()), local_midnight(today() + dt.timedelta(days=1))
    for r in rows:
        when = r["due_date"] or r["reminder_at"]
        r["when"] = when
        open_ = r["status"] in OPEN_STATUSES
        r["overdue"] = bool(open_ and when and when < now())   # past its due time, not just its day
        r["due_today"] = bool(open_ and when and t0 <= when < t1)
        r["assigned_to_name"] = names.get(r["assigned_to"]) if r["assigned_to"] else None
        r["created_by_name"] = names.get(r["created_by"]) if r["created_by"] else None
        if "recurrence" in r:
            from src.services.workspace_automation import describe
            r["recurrence_label"] = describe(r["recurrence"])
            # escalated beyond the owner's own reminder
            r["escalated"] = bool(open_ and r.get("escalated_to") in ("giver", "management"))
        cl = r["checklist"] if isinstance(r["checklist"], list) else []
        r["checklist"] = cl
        r["checklist_done"] = sum(1 for c in cl if c.get("done"))
    return rows


def _task(conn, task_id: str) -> Dict[str, Any]:
    t = q1(conn, f"SELECT {_TASK_COLS} FROM placeware_tasks t WHERE t.id=%s::uuid", (task_id,)) if _is_uuid(task_id) else None
    if not t:
        raise LookupError("Task not found")
    return t


def _can_see(user: Dict[str, Any], t: Dict[str, Any]) -> bool:
    me = str(user.get("sub"))
    return me in (t["assigned_to"], t["created_by"]) or bool(_roles(user) & MANAGER_ROLES)


def _activity(conn, task_id: str, actor: Optional[str], kind: str, body: Optional[str] = None) -> None:
    ex(conn, "INSERT INTO staff_task_activity (task_id, actor, kind, body) VALUES (%s, %s, %s, %s)", (task_id, actor, kind, body))


def list_tasks(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        mine = q(conn, f"""SELECT {_TASK_COLS} FROM placeware_tasks t
                           WHERE (t.assigned_to=%s OR (t.assigned_to IS NULL AND t.created_by=%s))
                             AND (t.status IN %s OR (t.status='completed' AND t.completed_at > now() - interval '30 days'))
                           ORDER BY t.completed_at DESC NULLS FIRST, COALESCE(t.due_date, t.reminder_at) NULLS LAST, t.created_at DESC""",
                 (me, me, OPEN_STATUSES))
        delegated = q(conn, f"""SELECT {_TASK_COLS} FROM placeware_tasks t
                                WHERE t.created_by=%s AND t.assigned_to IS NOT NULL AND t.assigned_to<>%s
                                  AND (t.status IN %s OR t.completed_at > now() - interval '7 days')
                                ORDER BY t.created_at DESC""", (me, me, OPEN_STATUSES))
        names = _names(conn, [r["assigned_to"] for r in mine + delegated] + [r["created_by"] for r in mine + delegated])
    mine = _decorate(mine, names)
    return {"open": [t for t in mine if t["status"] in OPEN_STATUSES],
            "completed": [t for t in mine if t["status"] == "completed"],
            "delegated": _decorate(delegated, names)}


def _checklist(v: Any) -> List[Dict[str, Any]]:
    out = []
    for c in v or []:
        if isinstance(c, str) and c.strip():
            out.append({"text": c.strip()[:200], "done": False})
        elif isinstance(c, dict) and str(c.get("text") or "").strip():
            out.append({"text": str(c["text"]).strip()[:200], "done": bool(c.get("done"))})
    return out


def create_task(user: Dict[str, Any], data: Dict[str, Any], conn=None, source: Optional[str] = None) -> Dict[str, Any]:
    me = _me(user)
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Say what needs to be done")
    kind = data.get("kind") or "task"
    if kind not in ("task", "reminder", "note"):
        raise ValueError("Unknown kind")
    assignee = data.get("assigned_to") or me
    if not _is_uuid(assignee):
        raise ValueError("Choose who the task is for")
    priority = data.get("priority") or "medium"
    if priority not in ("low", "medium", "high", "critical"):
        raise ValueError("Unknown priority")
    due = _dt(data.get("due_at") or data.get("due_date"))
    remind = _dt(data.get("reminder_at")) or (due if kind == "reminder" else None)
    src = source or ("assigned" if assignee != me else "manual")
    from src.services.workspace_automation import describe, validate_rule
    rule = validate_rule(data.get("recurrence"))
    if rule and kind == "note":
        raise ValueError("Notes do not repeat - make it a task or a reminder")
    if rule and not (due or remind):
        raise ValueError("A repeating task needs a first date")
    until = dt.date.fromisoformat(str(data["recurrence_until"])[:10]) if data.get("recurrence_until") else None

    def run(c):
        if not q1(c, "SELECT 1 FROM placeware_users WHERE id=%s AND is_active", (assignee,)):
            raise ValueError("That person is not an active user")
        dept = data.get("department") or next((p["department"] for p in people(c) if p["user_id"] == assignee), None)
        t = q1(c, """INSERT INTO placeware_tasks (title, description, kind, status, priority, due_date, reminder_at, assigned_to,
                                                   created_by, source, source_ref, department, entity_type, entity_id, entity_label,
                                                   link, checklist, request_id)
                     VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                     RETURNING id::text AS id""",
                 (title[:300], (data.get("description") or "").strip() or None, kind, priority, due, remind, assignee, me, src,
                  data.get("source_ref"), dept, data.get("entity_type"), data.get("entity_id"), data.get("entity_label"),
                  data.get("link"), json.dumps(_checklist(data.get("checklist"))), data.get("request_id")))
        if rule:
            ex(c, "UPDATE placeware_tasks SET recurrence=%s, recurrence_until=%s, series_id=id WHERE id=%s::uuid", (rule, until, t["id"]))
        _activity(c, t["id"], me, "created", {"note": "Note added", "reminder": "Reminder set"}.get(kind, "Task created")
                  + (f" · repeats {describe(rule)}" if rule else ""))
        if assignee != me:
            who = _names(c, [me])[me]
            _activity(c, t["id"], me, "assigned", f"Assigned to {_names(c, [assignee])[assignee]}")
            notify(c, [assignee], "assigned", "action", f"{who} gave you a task: {title[:120]}",
                   (data.get("description") or "")[:300], "task", t["id"], me)
        journal(c, me, "task_created", f"{'Assigned' if assignee != me else 'Added'} {kind}: {title[:120]}", "task", t["id"])
        return _decorate([_task(c, t["id"])], _names(c, [assignee, me]))[0]

    if conn is not None:
        return run(conn)
    with tx() as c:
        return run(c)


def get_task(user: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    with tx() as conn:
        t = _task(conn, task_id)
        if not _can_see(user, t):
            raise PermissionError("This task belongs to someone else")
        act = q(conn, """SELECT id, actor::text AS actor, kind, body, created_at FROM staff_task_activity
                         WHERE task_id=%s::uuid ORDER BY created_at, id""", (task_id,))
        req = q(conn, """SELECT id::text AS id, subject, kind, status, to_user::text AS to_user, to_department, response, created_at
                         FROM staff_requests WHERE task_id=%s::uuid OR work_task_id=%s::uuid ORDER BY created_at""", (task_id, task_id))
        names = _names(conn, [a["actor"] for a in act] + [t["assigned_to"], t["created_by"]] + [r["to_user"] for r in req])
    for a in act:
        a["actor_name"] = names.get(a["actor"]) if a["actor"] else "ACE"
    for r in req:
        r["to"] = names.get(r["to_user"]) if r["to_user"] else f"{r['to_department']} team"
    t = _decorate([t], names)[0]
    return {**t, "activity": act, "requests": req, "transitions": sorted(TRANSITIONS.get(t["status"], set()))}


def update_task(user: Dict[str, Any], task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        t = _task(conn, task_id)
        if not _can_see(user, t):
            raise PermissionError("This task belongs to someone else")
        sets, vals, notes = [], [], []
        for f in ("title", "description", "priority", "department"):
            if f in data and data[f] != t[f]:
                if f == "title" and not str(data[f] or "").strip():
                    raise ValueError("A task needs a title")
                if f == "priority" and data[f] not in ("low", "medium", "high", "critical"):
                    raise ValueError("Unknown priority")
                sets.append(f"{f}=%s"); vals.append(data[f]); notes.append(f)
        if "due_at" in data:
            sets.append("due_date=%s"); vals.append(_dt(data["due_at"]))
            notes.append("due date")
            if t["kind"] == "reminder":
                sets.append("reminder_at=%s"); vals.append(_dt(data["due_at"]))
            # a new due date starts the escalation chain again
            sets.append("escalation_level=0"); sets.append("escalated_to=NULL")
        if "recurrence" in data:
            from src.services.workspace_automation import describe, validate_rule
            rule = validate_rule(data["recurrence"])
            if rule and not (t["due_date"] or t["reminder_at"] or data.get("due_at")):
                raise ValueError("Give the task a date before making it repeat")
            sets.append("recurrence=%s"); vals.append(rule)
            sets.append("series_id=COALESCE(series_id, id)")
            _activity(conn, task_id, me, "recurrence", f"Repeats {describe(rule)}" if rule else "Stopped repeating")
        if "recurrence_until" in data:
            sets.append("recurrence_until=%s")
            vals.append(dt.date.fromisoformat(str(data["recurrence_until"])[:10]) if data["recurrence_until"] else None)
        if "checklist" in data:
            new = _checklist(data["checklist"])
            done_now = [c["text"] for c in new if c["done"] and not any(o.get("text") == c["text"] and o.get("done") for o in t["checklist"] or [])]
            sets.append("checklist=%s::jsonb"); vals.append(json.dumps(new))
            for d in done_now:
                _activity(conn, task_id, me, "checklist", f"Ticked: {d}")
        if data.get("assigned_to") and data["assigned_to"] != t["assigned_to"]:
            if not _is_uuid(data["assigned_to"]) or not q1(conn, "SELECT 1 FROM placeware_users WHERE id=%s AND is_active", (data["assigned_to"],)):
                raise ValueError("That person is not an active user")
            sets.append("assigned_to=%s"); vals.append(data["assigned_to"])
            nm = _names(conn, [data["assigned_to"], me])
            _activity(conn, task_id, me, "assigned", f"Handed to {nm[data['assigned_to']]}")
            notify(conn, [data["assigned_to"]], "assigned", "action", f"{nm[me]} handed you a task: {t['title'][:120]}",
                   None, "task", task_id, me)
        if sets:
            ex(conn, f"UPDATE placeware_tasks SET {', '.join(sets)}, updated_at=now() WHERE id=%s::uuid", (*vals, task_id))
            if notes:
                _activity(conn, task_id, me, "updated", "Changed " + ", ".join(dict.fromkeys(notes)))
    return get_task(user, task_id)


def set_status(user: Dict[str, Any], task_id: str, status: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    me = _me(user)
    data = data or {}
    with tx() as conn:
        t = _task(conn, task_id)
        if not _can_see(user, t):
            raise PermissionError("This task belongs to someone else")
        _apply_status(conn, t, status, me, data.get("note"), data.get("waiting_on"))
    return get_task(user, task_id)


def _apply_status(conn, t: Dict[str, Any], status: str, actor: str, note: Optional[str] = None,
                  waiting_on: Optional[str] = None, system: bool = False) -> None:
    cur = t["status"]
    if status == cur:
        return
    if status not in TRANSITIONS.get(cur, set()):
        raise WorkspaceError(f"A task that is {STATUS_LABEL.get(cur, cur)} cannot be moved to {STATUS_LABEL.get(status, status)}")
    if status == "waiting" and not (waiting_on or "").strip():
        raise ValueError("Say who or what you are waiting for")
    ex(conn, """UPDATE placeware_tasks SET status=%s, updated_at=now(),
                       started_at = CASE WHEN %s='in_progress' THEN COALESCE(started_at, now()) ELSE started_at END,
                       completed_at = CASE WHEN %s='completed' THEN now() WHEN %s IN ('pending','in_progress') THEN NULL ELSE completed_at END,
                       completed_by = CASE WHEN %s='completed' THEN %s WHEN %s IN ('pending','in_progress') THEN NULL ELSE completed_by END,
                       waiting_on = CASE WHEN %s='waiting' THEN %s ELSE NULL END
                WHERE id=%s::uuid""",
       (status, status, status, status, status, t["assigned_to"] if system else actor, status, status, waiting_on, t["id"]))
    label = {"in_progress": "Started", "waiting": f"Waiting on {waiting_on}", "completed": "Completed",
             "cancelled": "Cancelled", "pending": "Reopened" if cur in ("completed", "cancelled") else "Back to to-do"}[status]
    _activity(conn, t["id"], None if system else actor, "resolved" if system else "status", label + (f" - {note}" if note else ""))
    if status == "pending" and cur in ("completed", "cancelled"):
        ex(conn, "UPDATE placeware_tasks SET escalation_level=0, escalated_to=NULL WHERE id=%s::uuid", (t["id"],))
    if status in ("completed", "cancelled"):
        # a repeating task: finishing or skipping this one schedules the next
        from src.services.workspace_automation import schedule_next
        schedule_next(conn, t, actor)
    owner = t["assigned_to"] or t["created_by"]
    if status == "completed":
        journal(conn, owner, "task_completed", f"Completed: {t['title'][:150]}", "task", t["id"])
        if t["created_by"] and t["created_by"] != owner:
            who = _names(conn, [owner])[owner]
            notify(conn, [t["created_by"]], "completed", "info", f"{who} completed: {t['title'][:120]}", note, "task", t["id"], actor)
        if t["request_id"]:
            r = q1(conn, "SELECT id::text AS id, from_user::text AS from_user, status FROM staff_requests WHERE id=%s::uuid", (t["request_id"],))
            if r and r["status"] not in ("responded", "closed", "declined"):
                ex(conn, """UPDATE staff_requests SET status='responded', response=COALESCE(%s, 'Done'), responded_by=%s,
                                   responded_at=now(), updated_at=now() WHERE id=%s::uuid""", (note, owner, r["id"]))
                notify(conn, [r["from_user"]], "response", "action", f"Done: {t['title'][:120]}", note, "request", r["id"], owner)
    elif status == "in_progress" and not system:
        journal(conn, actor, "task_started", f"Started: {t['title'][:150]}", "task", t["id"])


def comment(user: Dict[str, Any], task_id: str, body: str) -> Dict[str, Any]:
    me = _me(user)
    body = (body or "").strip()
    if not body:
        raise ValueError("Write a comment")
    with tx() as conn:
        t = _task(conn, task_id)
        if not _can_see(user, t):
            raise PermissionError("This task belongs to someone else")
        _activity(conn, task_id, me, "comment", body[:2000])
        who = _names(conn, [me])[me]
        others = {t["assigned_to"], t["created_by"]} - {me, None}
        notify(conn, others, "comment", "social", f"{who} commented on: {t['title'][:100]}", body[:300], "task", task_id, me)
        mentioned = _mentions(conn, body) - others
        notify(conn, mentioned, "mention", "social", f"{who} mentioned you on: {t['title'][:100]}", body[:300], "task", task_id, me)
    return get_task(user, task_id)


def _mentions(conn, text: str) -> set:
    tags = {m.lower() for m in re.findall(r"@([A-Za-z][\w.-]{1,40})", text or "")}
    if not tags:
        return set()
    out = set()
    for p in people(conn):
        if not p["user_id"]:
            continue
        first = p["name"].split()[0].lower()
        local = (p["email"] or "").split("@")[0].lower()
        if first in tags or local in tags or p["name"].replace(" ", "").lower() in tags:
            out.add(p["user_id"])
    return out


# ---------------------------------------------------------------------------
# Operational items: business conditions that need a person, by role
# ---------------------------------------------------------------------------
# Each rule reads a module's live records and returns the items that need someone.
# Nothing is created until a person takes one ("Take it" -> a task linked to the
# record). A taken task closes itself once the record is dealt with in its module,
# so the work is counted where it was actually done.

OPS_ROLES = {"admin", "management", "ops", "operations", "procurement"}
QUALITY_ROLES = {"admin", "quality_assurance", "qa", "ops", "operations", "management"}
FINANCE_ROLES = {"admin", "finance", "management"}
HR_ROLES = {"admin", "hr"}
_CACHE: Dict[str, tuple] = {}
_CACHE_TTL = 60


def _cached(key: str, fn: Callable[[], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.monotonic(), val)
    return val


def _item(id_: Any, title: str, detail: str = "", due: Optional[dt.date] = None, overdue: bool = False,
          link: str = "", entity_type: str = "") -> Dict[str, Any]:
    return {"id": str(id_), "title": title, "detail": detail, "due": due, "overdue": overdue, "link": link,
            "entity_type": entity_type}


def _r_stock_approve(user) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """SELECT r.id::text AS id, COALESCE(fp.name, r.sku) AS name, r.requested_qty, r.created_at
                          FROM replenishment_requests r LEFT JOIN fin_products fp ON fp.sku=r.sku
                          WHERE r.status IN ('recommended','approved') ORDER BY r.created_at""")
    return [_item(r["id"], f"Stock order to place: {r['name']}", f"{float(r['requested_qty']):g} units requested",
                  link="/operations/purchase-orders?tab=orders", entity_type="stock_order") for r in rows]


def _r_deliveries(user) -> List[Dict[str, Any]]:
    t = today()
    with tx() as conn:
        rows = q(conn, """SELECT r.id::text AS id, COALESCE(fp.name, r.sku) AS name, r.requested_qty, r.expected_date, s.name AS supplier
                          FROM replenishment_requests r LEFT JOIN fin_products fp ON fp.sku=r.sku LEFT JOIN suppliers s ON s.id=r.supplier_id
                          WHERE r.status='ordered' AND r.expected_date IS NOT NULL AND r.expected_date <= %s
                          ORDER BY r.expected_date""", (t + dt.timedelta(days=2),))
    return [_item(r["id"], f"{'Overdue delivery' if r['expected_date'] < t else 'Delivery due'}: {r['name']}",
                  f"{float(r['requested_qty']):g} units from {r['supplier'] or 'supplier'}", r["expected_date"],
                  r["expected_date"] < t, "/operations/purchase-orders?tab=orders", "stock_order") for r in rows]


_QUALITY_KINDS = {"batch": "Batch to release", "recall": "Open recall", "audit": "Audit", "maintenance": "Maintenance",
                  "deviation": "Deviation to close", "capa": "CAPA action", "activity": "Compliance activity"}


def _r_quality(user) -> List[Dict[str, Any]]:
    from src.services.quality_hub import calendar_feed
    t = today()
    feed = calendar_feed(t, t + dt.timedelta(days=7), include_expiry=False)
    return [_item(f"{i['kind']}:{i['id']}", i["title"], i["subtitle"], i["date"], i["overdue"], i["link"], i["kind"])
            for i in feed["items"] if i["kind"] in _QUALITY_KINDS and not i["done"]]


def _r_expired(user) -> List[Dict[str, Any]]:
    from src.services.quality_hub import lots_in_stock
    t = today()
    fam: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"qty": 0.0, "value": 0.0, "lots": set()})
    with tx() as conn:
        for l in lots_in_stock(conn):
            if l["expiry_date"] and l["expiry_date"] < t and (l["batch_status"] or "AVAILABLE") == "AVAILABLE":
                g = fam[l["family"]]
                g["qty"] += float(l["qty"] or 0); g["value"] += float(l["value"] or 0); g["lots"].add(l["batch_number"] or l["sku"])
    return [_item(f, f"Expired stock still sellable: {f}", f"{g['qty']:g} units · ₦{g['value']:,.0f} · lots {', '.join(sorted(g['lots']))[:80]}",
                  overdue=True, link="/quality-control?tab=expiry", entity_type="product")
            for f, g in sorted(fam.items(), key=lambda kv: -kv[1]["value"])]


def _r_bills_due(user) -> List[Dict[str, Any]]:
    from src.fin.readmodel import ap_rows
    t = today()
    out = []
    for r in ap_rows():
        if r["balance"] > 0 and r["due_date"] and t <= r["due_date"] <= t + dt.timedelta(days=7):
            out.append(_item(f"{r['supplier_id']}:{r['doc_number']}", f"Supplier payment due: {r['name'] or 'supplier'}",
                             f"{r['doc_number']} · ₦{r['balance']:,.0f}", r["due_date"], False,
                             "/finance/books#/finance/books/payables", "bill"))
    return sorted(out, key=lambda i: i["due"])


def _r_crm_reminders(user) -> List[Dict[str, Any]]:
    from src.services import crm_hub
    try:
        rem = crm_hub.reminders(user, "mine")
    except Exception:
        return []
    t = today()
    out = []
    for r in (rem.get("overdue") or []) + (rem.get("today") or []):
        due = r.get("due_at")
        d = due.astimezone(TZ).date() if isinstance(due, dt.datetime) else None
        out.append(_item(r["id"], f"Customer follow-up: {r.get('customer_name') or r.get('lead_name') or r.get('title') or 'follow-up'}",
                         r.get("title") or r.get("note") or r.get("reminder_type") or "", d, bool(d and d < t),
                         "/crm/sales?tab=reminders", "crm_reminder"))
    return out


def _r_stale_deals(user) -> List[Dict[str, Any]]:
    me = str(user.get("sub"))
    with tx() as conn:
        rows = q(conn, """SELECT id, company_name, expected_value, COALESCE(last_contacted_at, stage_changed_at, created_at) AS last
                          FROM leads WHERE assigned_rep::text=%s AND stage='proposal'
                            AND COALESCE(last_contacted_at, stage_changed_at, created_at) < now() - interval '7 days'
                          ORDER BY expected_value DESC NULLS LAST""", (me,))
    return [_item(r["id"], f"Proposal going cold: {r['company_name']}",
                  f"No contact for {(now() - r['last']).days} days · ₦{float(r['expected_value'] or 0):,.0f}",
                  link="/crm/sales", entity_type="deal") for r in rows]


def _r_timesheets(user) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """SELECT COALESCE(user_id::text, 'staff:' || staff_id::text) AS who, COUNT(*) AS n, SUM(hours_worked) AS h,
                                 MIN(date) AS since
                          FROM placeware_timesheets WHERE status='submitted' AND date >= %s GROUP BY 1""",
                 (today() - dt.timedelta(days=21),))
        pm = person_map(conn)
    return [_item(r["who"], f"Timesheets to approve: {pm.get(r['who'], {}).get('name', 'staff member')}",
                  f"{r['n']} entr{'y' if r['n'] == 1 else 'ies'} · {float(r['h']):g}h since {r['since']:%d %b}",
                  link="/hr?tab=timesheets", entity_type="timesheet") for r in rows]


def _r_long_clocks(user) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """SELECT id::text AS id, user_id::text AS user_id, started_at FROM staff_time_sessions
                          WHERE ended_at IS NULL AND started_at < now() - interval '12 hours'""")
        pm = person_map(conn)
    return [_item(r["id"], f"Still clocked in: {pm.get(r['user_id'], {}).get('name', 'staff member')}",
                  f"Since {r['started_at'].astimezone(TZ):%a %d %b %H:%M} - probably forgot to clock out",
                  overdue=True, link="/hr", entity_type="time_session") for r in rows]


# key, label, department, level, roles (None = everyone; the rule itself is personal), personal (never cached)
RULES: List[Dict[str, Any]] = [
    {"key": "stock.to_order", "label": "Stock orders to place", "dept": "Procurement", "level": "action", "roles": OPS_ROLES, "fn": _r_stock_approve},
    {"key": "stock.deliveries", "label": "Deliveries due", "dept": "Operations", "level": "action", "roles": OPS_ROLES | QUALITY_ROLES, "fn": _r_deliveries},
    {"key": "quality.due", "label": "Quality & compliance due", "dept": "Quality", "level": "action", "roles": QUALITY_ROLES, "fn": _r_quality},
    {"key": "stock.expired", "label": "Expired stock still sellable", "dept": "Quality", "level": "critical", "roles": QUALITY_ROLES | FINANCE_ROLES, "fn": _r_expired},
    {"key": "finance.bills_due", "label": "Supplier payments due this week", "dept": "Finance", "level": "action", "roles": FINANCE_ROLES, "fn": _r_bills_due},
    {"key": "crm.follow_ups", "label": "Customer follow-ups due", "dept": "Sales", "level": "action", "roles": None, "fn": _r_crm_reminders, "personal": True},
    {"key": "crm.cold_deals", "label": "Proposals going cold", "dept": "Sales", "level": "info", "roles": None, "fn": _r_stale_deals, "personal": True},
    {"key": "hr.timesheets", "label": "Timesheets to approve", "dept": "HR", "level": "action", "roles": HR_ROLES, "fn": _r_timesheets},
    {"key": "hr.long_clocks", "label": "Clocks left running", "dept": "HR", "level": "action", "roles": HR_ROLES, "fn": _r_long_clocks},
]
RULE_BY_KEY = {r["key"]: r for r in RULES}


def _rules_for(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    rs = _roles(user)
    return [r for r in RULES if r["roles"] is None or rs & r["roles"]]


def _run_rule(rule: Dict[str, Any], user: Dict[str, Any], fresh: bool = False) -> List[Dict[str, Any]]:
    try:
        if rule.get("personal"):
            return rule["fn"](user)
        if fresh:
            _CACHE.pop(rule["key"], None)
        return _cached(rule["key"], lambda: rule["fn"](user))
    except Exception as exc:  # one module being unavailable must not take the workspace down
        import logging
        logging.getLogger(__name__).warning("workspace rule %s failed: %s", rule["key"], exc)
        return []


def signals(user: Dict[str, Any]) -> Dict[str, Any]:
    """Operational items for this person's roles, with who (if anyone) has taken each one."""
    me = _me(user)
    groups = []
    current: Dict[str, set] = {}
    for rule in _rules_for(user):
        items = _run_rule(rule, user)
        current[rule["key"]] = {i["id"] for i in items}
        if items:
            groups.append({"key": rule["key"], "label": rule["label"], "level": rule["level"], "dept": rule["dept"],
                           "count": len(items), "overdue": sum(1 for i in items if i["overdue"]), "items": items})
    with tx() as conn:
        taken = q(conn, """SELECT t.id::text AS id, t.source_ref, t.assigned_to::text AS assigned_to, t.status, t.title,
                                  t.created_by::text AS created_by, t.request_id::text AS request_id
                           FROM placeware_tasks t WHERE t.source='operational' AND t.status IN %s""", (OPEN_STATUSES,))
        # an item dealt with in its module closes the task that was taken for it
        resolved = 0
        for t in taken:
            rule_key, _, ent = (t["source_ref"] or "").partition("|")
            if rule_key in current and ent not in current[rule_key]:
                _apply_status(conn, t, "completed", t["assigned_to"] or me,
                              f"resolved in {RULE_BY_KEY[rule_key]['label'].lower()}", system=True)
                resolved += 1
        names = _names(conn, [t["assigned_to"] for t in taken])
    by_ref = {t["source_ref"]: t for t in taken}
    for g in groups:
        for i in g["items"]:
            t = by_ref.get(f"{g['key']}|{i['id']}")
            if t and t["status"] in OPEN_STATUSES:
                i["task_id"] = t["id"]
                i["taken_by"] = t["assigned_to"]
                i["taken_by_name"] = "you" if t["assigned_to"] == me else names.get(t["assigned_to"])
    return {"groups": groups, "total": sum(g["count"] for g in groups), "resolved_now": resolved}


def take_signal(user: Dict[str, Any], rule_key: str, item_id: str, assign_to: Optional[str] = None) -> Dict[str, Any]:
    me = _me(user)
    rule = RULE_BY_KEY.get(rule_key)
    if not rule or rule not in _rules_for(user):
        raise PermissionError("This item is not in your area")
    item = next((i for i in _run_rule(rule, user, fresh=True) if i["id"] == str(item_id)), None)
    if not item:
        raise WorkspaceError("This has already been dealt with")
    ref = f"{rule_key}|{item['id']}"
    with tx() as conn:
        existing = q1(conn, """SELECT id::text AS id, assigned_to::text AS assigned_to FROM placeware_tasks
                               WHERE source='operational' AND source_ref=%s AND status IN %s""", (ref, OPEN_STATUSES))
        if existing:
            who = _names(conn, [existing["assigned_to"]]).get(existing["assigned_to"], "someone")
            raise WorkspaceError(f"{'You have' if existing['assigned_to'] == me else who + ' has'} already taken this")
        return create_task(user, {
            "title": item["title"], "description": item["detail"], "assigned_to": assign_to or me,
            "priority": "high" if item["overdue"] or rule["level"] == "critical" else "medium",
            "due_at": dt.datetime.combine(item["due"], dt.time(17, 0), TZ).isoformat() if item["due"] else None,
            "department": rule["dept"], "source_ref": ref, "entity_type": item["entity_type"], "entity_id": item["id"],
            "entity_label": rule["label"], "link": item["link"],
        }, conn=conn, source="operational")


# ---------------------------------------------------------------------------
# Requests (ask a person or a team for information or for work)
# ---------------------------------------------------------------------------

_REQ_COLS = """r.id::text AS id, r.from_user::text AS from_user, r.to_user::text AS to_user, r.to_department, r.kind, r.subject,
    r.body, r.task_id::text AS task_id, r.work_task_id::text AS work_task_id, r.due_at, r.status, r.response,
    r.responded_by::text AS responded_by, r.responded_at, r.closed_at, r.created_at, r.updated_at,
    (SELECT COUNT(*) FROM staff_request_messages m WHERE m.request_id=r.id) AS messages"""


def _my_dept(conn, me: str) -> str:
    return next((p["department"] for p in people(conn) if p["user_id"] == me), "Operations")


def _req_decorate(conn, rows: List[Dict[str, Any]], me: str) -> List[Dict[str, Any]]:
    names = _names(conn, [r["from_user"] for r in rows] + [r["to_user"] for r in rows] + [r["responded_by"] for r in rows])
    for r in rows:
        r["from_name"] = names.get(r["from_user"])
        r["to_name"] = names.get(r["to_user"]) if r["to_user"] else f"{r['to_department']} team"
        r["responded_by_name"] = names.get(r["responded_by"]) if r["responded_by"] else None
        r["mine_to_answer"] = r["from_user"] != me and r["status"] in ("sent", "acknowledged", "in_progress")
        r["overdue"] = bool(r["due_at"] and r["due_at"] < now() and r["status"] in ("sent", "acknowledged", "in_progress"))
    return rows


def list_requests(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        dept = _my_dept(conn, me)
        incoming = q(conn, f"""SELECT {_REQ_COLS} FROM staff_requests r
                               WHERE r.from_user<>%s AND (r.to_user=%s OR (r.to_user IS NULL AND r.to_department=%s))
                                 AND (r.status NOT IN ('closed','declined','responded') OR r.updated_at > now() - interval '14 days')
                               ORDER BY (r.status IN ('sent','acknowledged','in_progress')) DESC, r.due_at NULLS LAST, r.created_at DESC""",
                     (me, me, dept))
        outgoing = q(conn, f"""SELECT {_REQ_COLS} FROM staff_requests r WHERE r.from_user=%s
                               AND (r.status NOT IN ('closed','declined') OR r.updated_at > now() - interval '14 days')
                               ORDER BY (r.status='responded') DESC, r.created_at DESC""", (me,))
        return {"incoming": _req_decorate(conn, incoming, me), "outgoing": _req_decorate(conn, outgoing, me), "department": dept}


def create_request(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    subject = (data.get("subject") or "").strip()
    if not subject:
        raise ValueError("Say what you need")
    kind = data.get("kind") or "info"
    if kind not in ("info", "work"):
        raise ValueError("Unknown request type")
    to_user = data.get("to_user") or None
    to_dept = data.get("to_department") or None
    if not to_user and not to_dept:
        raise ValueError("Choose a person or a team")
    if to_user and (not _is_uuid(to_user) or to_user == me):
        raise ValueError("Choose someone else")
    if to_dept and to_dept not in DEPARTMENTS:
        raise ValueError("Unknown team")
    due = _dt(data.get("due_at"))
    with tx() as conn:
        who = _names(conn, [me])[me]
        r = q1(conn, """INSERT INTO staff_requests (from_user, to_user, to_department, kind, subject, body, task_id, due_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id""",
               (me, to_user, None if to_user else to_dept, kind, subject[:300], (data.get("body") or "").strip() or None,
                data.get("task_id") if _is_uuid(data.get("task_id")) else None, due))
        target = _names(conn, [to_user])[to_user] if to_user else f"{to_dept} team"
        if kind == "work" and to_user:
            t = create_task({"sub": me, "roles": user.get("roles")},
                            {"title": subject, "description": data.get("body"), "assigned_to": to_user,
                             "due_at": due.isoformat() if due else None, "priority": data.get("priority") or "medium",
                             "request_id": r["id"]}, conn=conn, source="request")
            ex(conn, "UPDATE staff_requests SET work_task_id=%s WHERE id=%s::uuid", (t["id"], r["id"]))
        else:
            recipients = [to_user] if to_user else _dept_members(conn, to_dept)
            notify(conn, recipients, "request", "action",
                   f"{who} {'asks' if kind == 'info' else 'needs'}{'' if to_user else ' ' + to_dept}: {subject[:120]}",
                   data.get("body"), "request", r["id"], me)
        if data.get("task_id") and _is_uuid(data["task_id"]):
            t = q1(conn, f"SELECT {_TASK_COLS} FROM placeware_tasks t WHERE t.id=%s::uuid", (data["task_id"],))
            if t and t["status"] in ("pending", "in_progress") and _can_see(user, t):
                _apply_status(conn, t, "waiting", me, None, target)
        journal(conn, me, "request_sent", f"Asked {target}: {subject[:120]}", "request", r["id"])
        return _req_decorate(conn, [q1(conn, f"SELECT {_REQ_COLS} FROM staff_requests r WHERE r.id=%s::uuid", (r["id"],))], me)[0]


def get_request(user: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        r = q1(conn, f"SELECT {_REQ_COLS} FROM staff_requests r WHERE r.id=%s::uuid", (request_id,)) if _is_uuid(request_id) else None
        if not r:
            raise LookupError("Request not found")
        if me not in (r["from_user"], r["to_user"]) and r["to_department"] != _my_dept(conn, me) and not (_roles(user) & MANAGER_ROLES):
            raise PermissionError("This request is between other people")
        msgs = q(conn, """SELECT id, author::text AS author, body, created_at FROM staff_request_messages
                          WHERE request_id=%s::uuid ORDER BY created_at""", (request_id,))
        names = _names(conn, [m["author"] for m in msgs])
        for m in msgs:
            m["author_name"] = names.get(m["author"])
        r = _req_decorate(conn, [r], me)[0]
    return {**r, "thread": msgs}


def act_request(user: Dict[str, Any], request_id: str, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    body = (data.get("body") or "").strip()
    with tx() as conn:
        if not _is_uuid(request_id) or not q1(conn, "SELECT 1 FROM staff_requests WHERE id=%s::uuid FOR UPDATE", (request_id,)):
            raise LookupError("Request not found")
        r = q1(conn, f"SELECT {_REQ_COLS} FROM staff_requests r WHERE r.id=%s::uuid", (request_id,))
        if not r:
            raise LookupError("Request not found")
        dept = _my_dept(conn, me)
        is_from = r["from_user"] == me
        is_to = r["to_user"] == me or (r["to_user"] is None and r["to_department"] == dept)
        if not (is_from or is_to):
            raise PermissionError("This request is between other people")
        who = _names(conn, [me])[me]
        open_ = r["status"] in ("sent", "acknowledged", "in_progress")
        if action == "reply":
            if not body:
                raise ValueError("Write a message")
            ex(conn, "INSERT INTO staff_request_messages (request_id, author, body) VALUES (%s::uuid, %s, %s)", (request_id, me, body[:2000]))
            ex(conn, "UPDATE staff_requests SET updated_at=now() WHERE id=%s::uuid", (request_id,))
            other = [r["to_user"]] if is_from and r["to_user"] else ([r["from_user"]] if not is_from else _dept_members(conn, r["to_department"]))
            notify(conn, other, "message", "social", f"{who} on “{r['subject'][:80]}”", body[:300], "request", request_id, me)
        elif action in ("acknowledge", "start"):
            if not is_to or not open_:
                raise WorkspaceError("Only the person asked can take this up while it is open")
            ex(conn, """UPDATE staff_requests SET status=%s, to_user=COALESCE(to_user, %s), updated_at=now() WHERE id=%s::uuid""",
               ("acknowledged" if action == "acknowledge" else "in_progress", me, request_id))
            notify(conn, [r["from_user"]], "response", "info",
                   f"{who} {'has seen' if action == 'acknowledge' else 'is working on'}: {r['subject'][:100]}", None, "request", request_id, me)
        elif action == "respond":
            if not is_to or not open_:
                raise WorkspaceError("Only the person asked can answer while it is open")
            if not body:
                raise ValueError("Write your answer")
            ex(conn, """UPDATE staff_requests SET status='responded', response=%s, responded_by=%s, responded_at=now(),
                               to_user=COALESCE(to_user, %s), updated_at=now() WHERE id=%s::uuid""", (body[:2000], me, me, request_id))
            ex(conn, "INSERT INTO staff_request_messages (request_id, author, body) VALUES (%s::uuid, %s, %s)", (request_id, me, body[:2000]))
            notify(conn, [r["from_user"]], "response", "action", f"{who} answered: {r['subject'][:100]}", body[:300], "request", request_id, me)
            journal(conn, me, "request_answered", f"Answered {_names(conn, [r['from_user']])[r['from_user']]}: {r['subject'][:120]}", "request", request_id)
            if r["task_id"]:
                t = q1(conn, f"SELECT {_TASK_COLS} FROM placeware_tasks t WHERE t.id=%s::uuid", (r["task_id"],))
                if t and t["status"] == "waiting":
                    _apply_status(conn, t, "in_progress", r["from_user"], f"answer from {who}")
        elif action == "decline":
            if not is_to or not open_:
                raise WorkspaceError("Only the person asked can decline while it is open")
            ex(conn, """UPDATE staff_requests SET status='declined', response=%s, responded_by=%s, responded_at=now(),
                               updated_at=now() WHERE id=%s::uuid""", (body or None, me, request_id))
            notify(conn, [r["from_user"]], "response", "action", f"{who} declined: {r['subject'][:100]}", body or None, "request", request_id, me)
        elif action == "close":
            if not is_from:
                raise WorkspaceError("Only the person who asked can close it")
            ex(conn, "UPDATE staff_requests SET status='closed', closed_at=now(), updated_at=now() WHERE id=%s::uuid", (request_id,))
        else:
            raise ValueError("Unknown action")
    return get_request(user, request_id)


# ---------------------------------------------------------------------------
# Inbox (notifications)
# ---------------------------------------------------------------------------

_INBOX_FILTERS = {
    "action": "level IN ('critical','action')",
    "requests": "kind IN ('request','response')",
    "mentions": "kind IN ('mention','comment','message')",
    "updates": "level='info'",
}


def inbox(user: Dict[str, Any], flt: str = "all") -> Dict[str, Any]:
    me = _me(user)
    where = _INBOX_FILTERS.get(flt, "TRUE")
    with tx() as conn:
        rows = q(conn, f"""SELECT id, kind, level, title, body, link_type, link_id, actor::text AS actor, read_at, created_at
                           FROM staff_notifications WHERE user_id=%s AND {where} AND created_at > now() - interval '60 days'
                           ORDER BY created_at DESC LIMIT 200""", (me,))
        counts = q1(conn, f"""SELECT COUNT(*) FILTER (WHERE read_at IS NULL) AS unread,
                                     {', '.join(f"COUNT(*) FILTER (WHERE read_at IS NULL AND {w}) AS {k}" for k, w in _INBOX_FILTERS.items())}
                              FROM staff_notifications WHERE user_id=%s""", (me,))
        names = _names(conn, [r["actor"] for r in rows])
    for r in rows:
        r["actor_name"] = names.get(r["actor"]) if r["actor"] else "ACE"
    return {"items": rows, "counts": {k: int(v or 0) for k, v in counts.items()}}


def mark_read(user: Dict[str, Any], ids: Optional[List[int]] = None) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        if ids:
            ex(conn, "UPDATE staff_notifications SET read_at=now() WHERE user_id=%s AND id = ANY(%s) AND read_at IS NULL",
               (me, [int(i) for i in ids]))
        else:
            ex(conn, "UPDATE staff_notifications SET read_at=now() WHERE user_id=%s AND read_at IS NULL", (me,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Messages (one-to-one and the whole team) on the existing threads tables
# ---------------------------------------------------------------------------

TEAM_KEY = "team:all"


def _thread(conn, me: str, other: str) -> str:
    if other == "team":
        key, title, kind = TEAM_KEY, "Whole team", "team"
    else:
        if not _is_uuid(other) or other == me or not q1(conn, "SELECT 1 FROM placeware_users WHERE id=%s", (other,)):
            raise ValueError("Choose someone to message")
        a, b = sorted([me, other])
        key, title, kind = f"dm:{a}:{b}", "Direct message", "direct"
    r = q1(conn, "SELECT id::text AS id FROM threads WHERE channel_key=%s", (key,))
    if not r:
        r = q1(conn, """INSERT INTO threads (title, created_by, thread_type, channel_key) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (channel_key) WHERE channel_key IS NOT NULL DO UPDATE SET title=EXCLUDED.title
                        RETURNING id::text AS id""", (title, me, kind, key))
    for uid in ([me, other] if other != "team" else [me]):
        if not q1(conn, "SELECT 1 FROM thread_participants WHERE thread_id=%s::uuid AND user_id=%s", (r["id"], uid)):
            ex(conn, "INSERT INTO thread_participants (thread_id, user_id, role) VALUES (%s::uuid, %s, 'member')", (r["id"], uid))
    return r["id"]


def conversations(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        _thread(conn, me, "team")
        rows = q(conn, """SELECT t.id::text AS id, t.thread_type, t.channel_key, t.last_activity_at,
                                 (SELECT content FROM thread_messages m WHERE m.thread_id=t.id ORDER BY created_at DESC LIMIT 1) AS last_message,
                                 (SELECT sender FROM thread_messages m WHERE m.thread_id=t.id ORDER BY created_at DESC LIMIT 1) AS last_sender,
                                 (SELECT COUNT(*) FROM thread_messages m WHERE m.thread_id=t.id AND m.sender<>%s
                                    AND m.created_at > COALESCE((SELECT last_read_at FROM thread_reads r WHERE r.thread_id=t.id AND r.user_id=%s),
                                                                '-infinity'::timestamptz)) AS unread
                          FROM threads t
                          WHERE t.channel_key=%s OR (t.thread_type='direct' AND t.channel_key LIKE %s)
                          ORDER BY t.last_activity_at DESC NULLS LAST""", (me, me, TEAM_KEY, f"%{me}%"))
        pm = person_map(conn)
    online = online_ids()
    out = []
    for r in rows:
        if r["channel_key"] == TEAM_KEY:
            other, name = "team", "Whole team"
        else:
            ids = r["channel_key"].split(":")[1:]
            other = next((i for i in ids if i != me), me)
            name = pm.get(other, {}).get("name", "Former colleague")
        out.append({"id": r["id"], "with": other, "name": name, "online": other in online,
                    "last_message": r["last_message"], "last_sender": pm.get(r["last_sender"] or "", {}).get("name"),
                    "last_activity_at": r["last_activity_at"], "unread": int(r["unread"] or 0)})
    return {"conversations": out, "unread": sum(c["unread"] for c in out)}


def messages(user: Dict[str, Any], other: str, limit: int = 200) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        tid = _thread(conn, me, other)
        rows = q(conn, """SELECT id::text AS id, sender, content, created_at FROM
                            (SELECT * FROM thread_messages WHERE thread_id=%s::uuid ORDER BY created_at DESC LIMIT %s) m
                          ORDER BY created_at""", (tid, limit))
        ex(conn, """INSERT INTO thread_reads (thread_id, user_id, last_read_at) VALUES (%s::uuid, %s, now())
                    ON CONFLICT (thread_id, user_id) DO UPDATE SET last_read_at=now()""", (tid, me))
        names = _names(conn, [r["sender"] for r in rows if _is_uuid(r["sender"])])
    for r in rows:
        r["mine"] = r["sender"] == me
        r["sender_name"] = names.get(r["sender"], "ACE")
    return {"thread_id": tid, "with": other, "messages": rows}


def send_message(user: Dict[str, Any], other: str, body: str) -> Dict[str, Any]:
    me = _me(user)
    body = (body or "").strip()
    if not body:
        raise ValueError("Write a message")
    with tx() as conn:
        tid = _thread(conn, me, other)
        m = q1(conn, """INSERT INTO thread_messages (thread_id, sender, content, metadata) VALUES (%s::uuid, %s, %s, '{}'::jsonb)
                        RETURNING id::text AS id, created_at""", (tid, me, body[:4000]))
        ex(conn, "UPDATE threads SET last_activity_at=now() WHERE id=%s::uuid", (tid,))
        ex(conn, """INSERT INTO thread_reads (thread_id, user_id, last_read_at) VALUES (%s::uuid, %s, now())
                    ON CONFLICT (thread_id, user_id) DO UPDATE SET last_read_at=now()""", (tid, me))
        mentioned = _mentions(conn, body) - {other}
        if mentioned:
            who = _names(conn, [me])[me]
            notify(conn, mentioned, "mention", "social", f"{who} mentioned you{' in the team chat' if other == 'team' else ''}",
                   body[:300], "message", other if other == "team" else me, me)
    return {"id": m["id"], "thread_id": tid, "created_at": m["created_at"]}


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

def team(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    ws = week_start()
    with tx() as conn:
        ppl = [p for p in people(conn) if p["has_login"]]
        sessions = {r["user_id"]: r for r in q(conn, """SELECT user_id::text AS user_id, started_at, break_started_at, break_seconds
                                                          FROM staff_time_sessions WHERE ended_at IS NULL""")}
        load = {r["uid"]: r for r in q(conn, """SELECT assigned_to::text AS uid, COUNT(*) AS open,
                                                       COUNT(*) FILTER (WHERE status='in_progress') AS in_progress,
                                                       COUNT(*) FILTER (WHERE status='waiting') AS waiting,
                                                       COUNT(*) FILTER (WHERE COALESCE(due_date, reminder_at) < %s) AS due_today
                                                FROM placeware_tasks WHERE status IN %s AND kind<>'note' GROUP BY 1""",
                                         (local_midnight(today() + dt.timedelta(days=1)), OPEN_STATUSES))}
        done = {r["uid"]: int(r["n"]) for r in q(conn, """SELECT completed_by::text AS uid, COUNT(*) AS n FROM placeware_tasks
                                                           WHERE status='completed' AND completed_at >= %s GROUP BY 1""", (local_midnight(ws),))}
        hours = {r["uid"]: float(r["h"]) for r in q(conn, """SELECT user_id::text AS uid, SUM(hours_worked) AS h FROM placeware_timesheets
                                                             WHERE date >= %s AND status<>'rejected' AND user_id IS NOT NULL GROUP BY 1""", (ws,))}
    online = online_ids() | {me}   # whoever is looking at the page is online
    out = []
    for p in ppl:
        uid = p["user_id"]
        s = sessions.get(uid)
        status = ("on_break" if s and s["break_started_at"] else "working" if s else "online" if uid in online else "offline")
        live = _worked_seconds(s) if s else 0
        l = load.get(uid) or {}
        out.append({**{k: p[k] for k in ("user_id", "name", "email", "department", "job_title", "phone", "roles")},
                    "me": uid == me, "status": status, "online": uid in online, "clocked_in_at": s["started_at"] if s else None,
                    "open_tasks": int(l.get("open") or 0), "in_progress": int(l.get("in_progress") or 0),
                    "waiting": int(l.get("waiting") or 0), "due_today": int(l.get("due_today") or 0),
                    "done_this_week": done.get(uid, 0), "hours_week": round(hours.get(uid, 0) + live / 3600, 1)})
    rank = {"working": 0, "on_break": 1, "online": 2, "offline": 3}
    out.sort(key=lambda p: (not p["me"], rank[p["status"]], p["name"].lower()))
    return {"people": out, "working": sum(1 for p in out if p["status"] in ("working", "on_break")),
            "online": sum(1 for p in out if p["online"]), "departments": sorted({p["department"] for p in out})}


# ---------------------------------------------------------------------------
# Progress + journal
# ---------------------------------------------------------------------------

def _range(rng: str) -> tuple:
    t = today()
    if rng == "month":
        start = t.replace(day=1)
        prev = (start - dt.timedelta(days=1)).replace(day=1)
        return start, t, prev, start - dt.timedelta(days=1)
    start = week_start(t)
    return start, t, start - dt.timedelta(days=7), start - dt.timedelta(days=1)


def progress(user: Dict[str, Any], rng: str = "week") -> Dict[str, Any]:
    me = _me(user)
    start, end, pstart, pend = _range(rng)
    a, b = local_midnight(start), local_midnight(end + dt.timedelta(days=1))
    with tx() as conn:
        done = q(conn, """SELECT id::text AS id, title, department, source, kind, due_date, completed_at, entity_label
                          FROM placeware_tasks WHERE completed_by=%s AND status='completed' AND completed_at >= %s AND completed_at < %s
                          ORDER BY completed_at DESC""", (me, a, b))
        prev_done = q1(conn, """SELECT COUNT(*) AS n FROM placeware_tasks WHERE completed_by=%s AND status='completed'
                                AND completed_at >= %s AND completed_at < %s""", (me, local_midnight(pstart), local_midnight(pend + dt.timedelta(days=1))))["n"]
        now_open = q1(conn, """SELECT COUNT(*) AS open, COUNT(*) FILTER (WHERE status='waiting') AS waiting,
                                      COUNT(*) FILTER (WHERE status='in_progress') AS in_progress,
                                      COUNT(*) FILTER (WHERE COALESCE(due_date, reminder_at) < %s) AS overdue
                               FROM placeware_tasks WHERE assigned_to=%s AND status IN %s""", (now(), me, OPEN_STATUSES))
        req = q1(conn, """SELECT COUNT(*) FILTER (WHERE responded_by=%s AND responded_at >= %s AND responded_at < %s) AS answered,
                                 COUNT(*) FILTER (WHERE from_user=%s AND created_at >= %s AND created_at < %s) AS sent,
                                 AVG(EXTRACT(EPOCH FROM responded_at - created_at)/3600)
                                   FILTER (WHERE responded_by=%s AND responded_at >= %s AND responded_at < %s) AS avg_hours
                          FROM staff_requests""", (me, a, b, me, a, b, me, a, b))
        ts = q(conn, """SELECT date, SUM(hours_worked) AS h FROM placeware_timesheets WHERE user_id=%s AND date BETWEEN %s AND %s
                        AND status<>'rejected' GROUP BY date""", (me, start, end))
        view = clock_view(conn, me)
    with_due = [t for t in done if t["due_date"]]
    on_time = [t for t in with_due if t["completed_at"] <= t["due_date"] + dt.timedelta(hours=7)]  # same working day counts
    hours_by_day = {r["date"]: float(r["h"]) for r in ts}
    live_today = view["today_seconds"] / 3600 - hours_by_day.get(today(), 0) if view["session"] else 0
    days = []
    d = start
    while d <= end:
        days.append({"date": d, "completed": sum(1 for t in done if t["completed_at"].astimezone(TZ).date() == d),
                     "hours": round(hours_by_day.get(d, 0) + (live_today if d == today() else 0), 2)})
        d += dt.timedelta(days=1)
    by_dept: Dict[str, int] = defaultdict(int)
    by_source: Dict[str, int] = defaultdict(int)
    for t in done:
        by_dept[t["department"] or "General"] += 1
        by_source[{"operational": "Operational items", "request": "Requests from colleagues", "assigned": "Given by colleagues"}
                  .get(t["source"], "My own tasks")] += 1
    return {
        "range": rng, "from": start, "to": end,
        "completed": len(done), "completed_prev": int(prev_done or 0),
        "on_time_pct": round(100 * len(on_time) / len(with_due)) if with_due else None, "with_due": len(with_due),
        "requests_answered": int(req["answered"] or 0), "requests_sent": int(req["sent"] or 0),
        "avg_answer_hours": round(float(req["avg_hours"]), 1) if req["avg_hours"] is not None else None,
        "open": int(now_open["open"] or 0), "waiting": int(now_open["waiting"] or 0),
        "in_progress": int(now_open["in_progress"] or 0), "overdue": int(now_open["overdue"] or 0),
        "hours": round(sum(x["hours"] for x in days), 2),
        "days": days,
        "by_department": sorted(({"name": k, "count": v} for k, v in by_dept.items()), key=lambda x: -x["count"]),
        "by_source": sorted(({"name": k, "count": v} for k, v in by_source.items()), key=lambda x: -x["count"]),
        "accomplishments": done[:12],
    }


def work_journal(user: Dict[str, Any], rng: str = "today") -> List[Dict[str, Any]]:
    me = _me(user)
    t = today()
    start = t if rng == "today" else (week_start(t) if rng == "week" else t.replace(day=1))
    with tx() as conn:
        return q(conn, """SELECT id, kind, summary, entity_type, entity_id, occurred_at FROM staff_work_events
                          WHERE user_id=%s AND occurred_at >= %s ORDER BY occurred_at DESC LIMIT 300""", (me, local_midnight(start)))


# ---------------------------------------------------------------------------
# My Day
# ---------------------------------------------------------------------------

def my_day(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    t = today()
    t0, t1 = local_midnight(t), local_midnight(t + dt.timedelta(days=1))
    with tx() as conn:
        ensure_profile(conn, me)
        profile = next((p for p in people(conn) if p["user_id"] == me), None) or {}
        clock = clock_view(conn, me)
        events = q(conn, """SELECT id::text AS id, title, event_type, start_time, end_time, location FROM placeware_calendar_events
                            WHERE start_time >= %s AND start_time < %s
                              AND (created_by=%s OR attendees::text ILIKE %s OR event_type IN ('holiday'))
                            ORDER BY start_time""", (t0, t1, me, f"%{me}%"))
        unread = q1(conn, """SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE level IN ('critical','action')) AS action
                             FROM staff_notifications WHERE user_id=%s AND read_at IS NULL""", (me,))
        attention = q(conn, """SELECT id, kind, level, title, body, link_type, link_id, created_at FROM staff_notifications
                               WHERE user_id=%s AND read_at IS NULL ORDER BY (level IN ('critical','action')) DESC, created_at DESC LIMIT 8""", (me,))
        journal_today = q(conn, """SELECT kind, summary, occurred_at FROM staff_work_events WHERE user_id=%s AND occurred_at >= %s
                                   ORDER BY occurred_at DESC LIMIT 12""", (me, t0))
    tasks = list_tasks(user)
    reqs = list_requests(user)
    sig = signals(user)
    msgs = conversations(user)
    open_ = tasks["open"]
    timeline = [{"type": "task", "at": x["when"], "task": x} for x in open_ if x["when"] and x["when"] < t1]
    timeline += [{"type": "event", "at": e["start_time"], "event": e} for e in events]
    timeline.sort(key=lambda i: i["at"])
    hour = now().astimezone(TZ).hour
    return {
        "greeting": "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening",
        "date": t, "me": {k: profile.get(k) for k in ("user_id", "name", "email", "department", "job_title", "roles")},
        "clock": clock,
        "counts": {"open": sum(1 for x in open_ if x["kind"] != "note"),
                   "due_today": sum(1 for x in open_ if x["due_today"] or x["overdue"]),
                   "overdue": sum(1 for x in open_ if x["overdue"]),
                   "in_progress": sum(1 for x in open_ if x["status"] == "in_progress"),
                   "waiting": sum(1 for x in open_ if x["status"] == "waiting")
                              + sum(1 for r in reqs["outgoing"] if r["status"] in ("sent", "acknowledged", "in_progress")),
                   "to_answer": sum(1 for r in reqs["incoming"] if r["mine_to_answer"]),
                   "done_today": sum(1 for x in tasks["completed"] if x["completed_at"] and x["completed_at"] >= t0),
                   "unread": int(unread["n"] or 0), "unread_action": int(unread["action"] or 0),
                   "unread_messages": msgs["unread"]},
        "timeline": timeline,
        "no_date": [x for x in open_ if not x["when"]][:12],
        "upcoming": [x for x in open_ if x["when"] and x["when"] >= t1][:8],
        "to_answer": [r for r in reqs["incoming"] if r["mine_to_answer"]][:6],
        "waiting_on_others": [r for r in reqs["outgoing"] if r["status"] in ("sent", "acknowledged", "in_progress")][:6],
        "answered": [r for r in reqs["outgoing"] if r["status"] == "responded"][:6],
        "attention": attention,
        "operational": sig,
        "journal": journal_today,
    }


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

DEFAULT_PREFS = {"show_operational": True, "show_team": True, "show_journal": True, "task_order": "due", "default_tab": "day"}


def get_prefs(user: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    with tx() as conn:
        r = q1(conn, "SELECT prefs FROM staff_preferences WHERE user_id=%s", (me,))
    return {**DEFAULT_PREFS, **((r or {}).get("prefs") or {})}


def set_prefs(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    clean = {k: data[k] for k in DEFAULT_PREFS if k in data}
    with tx() as conn:
        ex(conn, """INSERT INTO staff_preferences (user_id, prefs) VALUES (%s, %s::jsonb)
                    ON CONFLICT (user_id) DO UPDATE SET prefs = staff_preferences.prefs || EXCLUDED.prefs, updated_at=now()""",
           (me, json.dumps(clean)))
    return get_prefs(user)
