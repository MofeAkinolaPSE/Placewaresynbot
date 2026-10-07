"""Staff Workspace automation: recurring tasks and escalation chains.

Recurring   A task keeps its rule (daily | weekdays | weekly[:MO,FR] | monthly[:15|last] |
            every:N:days|weeks|months) and series. Finishing or skipping one schedules the
            next occurrence (missed ones are not piled up), until the end date if there is one.

Escalation  When a task, reminder or request passes its due time, the chain for its priority
            (staff_escalation_policy) fires step by step:
              assignee / recipient  a reminder that it is due or overdue
              giver / requester     the person who gave it (or asked) is told it is late
              management            admin + management are told, as critical
            The step reached is stored on the record and moved with a conditional update, so
            each step fires exactly once however many workers run the sweep. Moving the due
            date or reopening starts the chain again. Notes never escalate; reminders only
            remind their owner.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from src.fin.db import ex, q, q1, tx
from src.services.staff_workspace import TZ, _activity, _names, notify, now

log = logging.getLogger(__name__)
WD = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
RULE_LABELS = {"daily": "every day", "weekdays": "every weekday", "weekly": "every week", "monthly": "every month"}


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------

def validate_rule(rule: Optional[str]) -> Optional[str]:
    if not rule:
        return None
    r = rule.strip().lower()
    if r in ("daily", "weekdays", "weekly", "monthly"):
        return r
    if r.startswith("weekly:") and all(c.upper() in WD for c in r[7:].split(",") if c):
        return "weekly:" + ",".join(sorted({c.upper() for c in r[7:].split(",") if c}, key=WD.index))
    if r.startswith("monthly:") and (r[8:] == "last" or r[8:].isdigit() and 1 <= int(r[8:]) <= 31):
        return r
    parts = r.split(":")
    if len(parts) == 3 and parts[0] == "every" and parts[1].isdigit() and 1 <= int(parts[1]) <= 365 and parts[2] in ("days", "weeks", "months"):
        return r
    raise ValueError(f"Unknown repeat rule: {rule}")


def describe(rule: Optional[str]) -> Optional[str]:
    if not rule:
        return None
    if rule in RULE_LABELS:
        return RULE_LABELS[rule]
    if rule.startswith("weekly:"):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return "every " + ", ".join(names[WD.index(c)] for c in rule[7:].split(","))
    if rule.startswith("monthly:"):
        a = rule[8:]
        return "at the end of every month" if a == "last" else f"monthly on day {a}"
    _, n, unit = rule.split(":")
    return f"every {n} {unit}" if n != "1" else f"every {unit[:-1]}"


def _month_add(d: dt.date, months: int, day: Optional[int] = None, last: bool = False) -> dt.date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    nxt = dt.date(y + (m // 12), m % 12 + 1, 1)
    end = (nxt - dt.timedelta(days=1)).day
    return dt.date(y, m, end if last else min(day or d.day, end))


def next_after(rule: str, prev: dt.datetime) -> dt.datetime:
    """The occurrence after prev (same time of day, Lagos)."""
    local = prev.astimezone(TZ)
    d, t = local.date(), local.timetz().replace(tzinfo=None)
    if rule == "daily":
        n = d + dt.timedelta(days=1)
    elif rule == "weekdays":
        n = d + dt.timedelta(days=1)
        while n.weekday() >= 5:
            n += dt.timedelta(days=1)
    elif rule == "weekly":
        n = d + dt.timedelta(days=7)
    elif rule.startswith("weekly:"):
        days = sorted(WD.index(c) for c in rule[7:].split(","))
        n = d + dt.timedelta(days=1)
        while n.weekday() not in days:
            n += dt.timedelta(days=1)
    elif rule == "monthly":
        n = _month_add(d, 1)
    elif rule.startswith("monthly:"):
        a = rule[8:]
        n = _month_add(d, 1, last=True) if a == "last" else _month_add(d, 1, day=int(a))
    else:
        _, k, unit = rule.split(":")
        k = int(k)
        n = d + dt.timedelta(days=k) if unit == "days" else d + dt.timedelta(weeks=k) if unit == "weeks" else _month_add(d, k)
    return dt.datetime.combine(n, t, TZ)


def schedule_next(conn, task: Dict[str, Any], actor: Optional[str]) -> Optional[str]:
    """After a recurring task is completed or skipped: create the next one (once)."""
    t = q1(conn, """SELECT id::text AS id, title, description, kind, priority, due_date, reminder_at, assigned_to::text AS assigned_to,
                           created_by::text AS created_by, source, department, entity_type, entity_id, entity_label, link, checklist,
                           recurrence, recurrence_until, COALESCE(series_id, id)::text AS series_id
                    FROM placeware_tasks WHERE id=%s::uuid""", (task["id"],))
    if not t or not t["recurrence"]:
        return None
    base = t["due_date"] or t["reminder_at"] or now()
    nxt = next_after(t["recurrence"], base)
    # missed occurrences are not piled up: jump to the first one from today
    today0 = dt.datetime.combine(now().astimezone(TZ).date(), dt.time(0, 0), TZ)
    guard = 0
    while nxt < today0 and guard < 1000:
        nxt = next_after(t["recurrence"], nxt)
        guard += 1
    if t["recurrence_until"] and nxt.astimezone(TZ).date() > t["recurrence_until"]:
        _activity(conn, t["id"], None, "recurrence", "Series ended (repeat end date reached)")
        return None
    if q1(conn, """SELECT 1 FROM placeware_tasks WHERE series_id=%s::uuid AND status IN ('pending','in_progress','waiting','blocked')
                   AND id<>%s::uuid""", (t["series_id"], t["id"])):
        return None      # the next one already exists
    checklist = [{"text": c.get("text"), "done": False} for c in (t["checklist"] or []) if isinstance(c, dict)]
    r = q1(conn, """INSERT INTO placeware_tasks (title, description, kind, status, priority, due_date, reminder_at, assigned_to, created_by,
                                                  source, department, entity_type, entity_id, entity_label, link, checklist,
                                                  recurrence, recurrence_until, series_id)
                    VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::uuid)
                    RETURNING id::text AS id""",
           (t["title"], t["description"], t["kind"], t["priority"], nxt if t["due_date"] else None,
            nxt if t["reminder_at"] or t["kind"] == "reminder" else None, t["assigned_to"], t["created_by"],
            t["source"] if t["source"] not in ("operational",) else "manual", t["department"], t["entity_type"], t["entity_id"],
            t["entity_label"], t["link"], json.dumps(checklist), t["recurrence"], t["recurrence_until"], t["series_id"]))
    ex(conn, "UPDATE placeware_tasks SET series_id=%s::uuid WHERE id=%s::uuid AND series_id IS NULL", (t["series_id"], t["id"]))
    _activity(conn, r["id"], None, "created", f"Repeats {describe(t['recurrence'])} - next in the series")
    _activity(conn, t["id"], None, "recurrence", f"Next one scheduled for {nxt.astimezone(TZ):%a %d %b %H:%M}")
    return r["id"]


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

def policies() -> Dict[str, Any]:
    with tx() as conn:
        rows = q(conn, "SELECT subject, priority, steps, updated_at FROM staff_escalation_policy ORDER BY subject, priority")
    return {f"{r['subject']}:{r['priority']}": r["steps"] for r in rows}


TARGETS = {"task": {"assignee", "giver", "management"}, "request": {"recipient", "requester", "management"}}


def set_policy(user: Dict[str, Any], subject: str, priority: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    roles = {str(r).lower() for r in user.get("roles") or []}
    if not roles & {"admin", "management", "hr"}:
        raise PermissionError("Only admin, management or HR can change escalation rules")
    if subject not in TARGETS:
        raise ValueError("Unknown subject")
    clean = []
    for s in steps or []:
        h = float(s.get("after_hours"))
        if h < 0 or h > 24 * 60:
            raise ValueError("Hours must be between 0 and 1440")
        if s.get("to") not in TARGETS[subject]:
            raise ValueError(f"Unknown recipient {s.get('to')}")
        clean.append({"after_hours": h, "to": s["to"]})
    clean.sort(key=lambda s: s["after_hours"])
    with tx() as conn:
        ex(conn, """INSERT INTO staff_escalation_policy (subject, priority, steps, updated_by) VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (subject, priority) DO UPDATE SET steps=EXCLUDED.steps, updated_by=EXCLUDED.updated_by, updated_at=now()""",
           (subject, priority, json.dumps(clean), user.get("sub")))
    return policies()


def _management(conn) -> List[str]:
    return [r["id"] for r in q(conn, """SELECT id::text AS id FROM placeware_users
                                        WHERE is_active AND roles && ARRAY['admin','management']::text[]""")]


def _late(h: float) -> str:
    if h < 1:
        return "now due"
    if h < 48:
        return f"{int(h)}h overdue"
    return f"{int(h // 24)} days overdue"


def run_escalations(at: Optional[dt.datetime] = None) -> Dict[str, int]:
    at = at or now()
    fired = {"tasks": 0, "requests": 0, "notifications": 0}
    pol = policies()
    with tx() as conn:
        tasks = q(conn, """SELECT id::text AS id, title, kind, priority, assigned_to::text AS assigned_to, created_by::text AS created_by,
                                  -- a task entered after its due time starts its chain when it was entered
                                  GREATEST(COALESCE(due_date, reminder_at), created_at) AS due, escalation_level
                           FROM placeware_tasks
                           WHERE status IN ('pending','in_progress','waiting','blocked') AND kind<>'note'
                             AND COALESCE(due_date, reminder_at) <= %s""", (at,))
        names = _names(conn, [t["assigned_to"] for t in tasks])
        mgmt = None
        for t in tasks:
            steps = pol.get(f"task:{t['priority']}") or pol.get("task:medium") or []
            if t["kind"] == "reminder":
                steps = [{"after_hours": 0, "to": "assignee"}]
            hours = (at - t["due"]).total_seconds() / 3600
            reached = sum(1 for s in steps if hours >= float(s["after_hours"]))
            if reached <= t["escalation_level"]:
                continue
            new_steps = steps[t["escalation_level"]:reached]
            last_to = new_steps[-1]["to"]
            won = q1(conn, """UPDATE placeware_tasks SET escalation_level=%s, escalated_at=now(), escalated_to=%s
                              WHERE id=%s::uuid AND escalation_level=%s RETURNING 1 AS ok""",
                     (reached, last_to, t["id"], t["escalation_level"]))
            if not won:
                continue      # another worker got there first
            fired["tasks"] += 1
            who = names.get(t["assigned_to"], "Someone")
            late = _late(hours)
            for s in new_steps:
                to = s["to"]
                if to == "assignee":
                    title = f"Reminder: {t['title']}" if t["kind"] == "reminder" else f"{'Due now' if hours < 1 else 'Overdue'}: {t['title']}"
                    fired["notifications"] += notify(conn, [t["assigned_to"]], "reminder" if t["kind"] == "reminder" else "escalation",
                                                     "action", title, None if t["kind"] == "reminder" else late, "task", t["id"])
                elif to == "giver":
                    if t["created_by"] and t["created_by"] != t["assigned_to"]:
                        fired["notifications"] += notify(conn, [t["created_by"]], "escalation", "action",
                                                         f"Not done yet - {who}: {t['title']}", late, "task", t["id"])
                        _activity(conn, t["id"], None, "escalated", f"Escalated to {names.get(t['created_by']) or 'the person who gave it'} ({late})")
                elif to == "management":
                    mgmt = mgmt if mgmt is not None else _management(conn)
                    targets = [m for m in mgmt if m != t["assigned_to"]]
                    fired["notifications"] += notify(conn, targets, "escalation", "critical",
                                                     f"Escalated: {t['title']} ({who}, {late})", None, "task", t["id"])
                    if targets:
                        _activity(conn, t["id"], None, "escalated", f"Escalated to management ({late})")

        reqs = q(conn, """SELECT id::text AS id, subject, from_user::text AS from_user, to_user::text AS to_user, to_department,
                                 GREATEST(due_at, created_at) AS due_at, escalation_level FROM staff_requests
                          WHERE status IN ('sent','acknowledged','in_progress') AND due_at IS NOT NULL AND due_at <= %s""", (at,))
        steps = pol.get("request:all") or []
        rn = _names(conn, [r["from_user"] for r in reqs] + [r["to_user"] for r in reqs])
        for r in reqs:
            hours = (at - r["due_at"]).total_seconds() / 3600
            reached = sum(1 for s in steps if hours >= float(s["after_hours"]))
            if reached <= r["escalation_level"]:
                continue
            new_steps = steps[r["escalation_level"]:reached]
            won = q1(conn, """UPDATE staff_requests SET escalation_level=%s, escalated_at=now(), escalated_to=%s
                              WHERE id=%s::uuid AND escalation_level=%s RETURNING 1 AS ok""",
                     (reached, new_steps[-1]["to"], r["id"], r["escalation_level"]))
            if not won:
                continue
            fired["requests"] += 1
            late = _late(hours)
            asker = rn.get(r["from_user"], "A colleague")
            target = rn.get(r["to_user"]) if r["to_user"] else f"the {r['to_department']} team"
            for s in new_steps:
                if s["to"] == "recipient":
                    from src.services.staff_workspace import _dept_members
                    rec = [r["to_user"]] if r["to_user"] else _dept_members(conn, r["to_department"])
                    fired["notifications"] += notify(conn, rec, "escalation", "action", f"{asker} is waiting: {r['subject'][:120]}",
                                                     late, "request", r["id"])
                elif s["to"] == "requester":
                    fired["notifications"] += notify(conn, [r["from_user"]], "escalation", "info",
                                                     f"Still no answer from {target}: {r['subject'][:120]}", late, "request", r["id"])
                elif s["to"] == "management":
                    mgmt = mgmt if mgmt is not None else _management(conn)
                    fired["notifications"] += notify(conn, [m for m in mgmt if m != r["to_user"]], "escalation", "critical",
                                                     f"Unanswered request escalated: {r['subject'][:100]} ({asker} → {target}, {late})",
                                                     None, "request", r["id"])
    if any(fired.values()):
        log.info("workspace escalations: %s", fired)
    return fired
