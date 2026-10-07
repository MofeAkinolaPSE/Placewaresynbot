"""HR, read from what people actually do in ACE.

  Overview    who is online now, who is on the clock (live, before it is saved),
              hours this week per person (saved timesheets + the running clock),
              summed for the headline number; department split; exceptions.
  Directory   everyone registered on User Access (plus HR-only records), with
              their profile, status today and workload - not a separate list.
  Timesheets  entries written when people clock out (or HR adds one), reviewed
              and approved here, exportable per week.

Same tables as the Staff Workspace (staff_workspace.py): nothing is copied.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.fin.db import ex, q, q1, tx
from src.services.staff_workspace import (DEPARTMENTS, TZ, _is_uuid, _me, _worked_seconds, ensure_profile, local_midnight,
                                          now, online_ids, people, person_map, today, week_start, OPEN_STATUSES)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _week(ws: Optional[str]) -> dt.date:
    return week_start(dt.date.fromisoformat(ws[:10])) if ws else week_start()


def _entries(conn, start: dt.date, end: dt.date) -> List[Dict[str, Any]]:
    return q(conn, """SELECT t.id, COALESCE(t.user_id::text, 'staff:' || t.staff_id::text) AS person, t.user_id::text AS user_id,
                             t.staff_id::text AS staff_id, t.date, t.hours_worked, t.department, t.activity_note, t.source, t.status,
                             t.recorded_by, t.approved_by::text AS approved_by, t.approved_at, t.review_note, t.created_at,
                             t.session_id::text AS session_id
                      FROM placeware_timesheets t WHERE t.date BETWEEN %s AND %s ORDER BY t.date, t.id""", (start, end))


def _open_sessions(conn) -> Dict[str, Dict[str, Any]]:
    return {r["user_id"]: r for r in q(conn, """SELECT id::text AS id, user_id::text AS user_id, started_at, break_started_at,
                                                        break_seconds, department FROM staff_time_sessions WHERE ended_at IS NULL""")}


def _live_by_day(s: Dict[str, Any]) -> Dict[dt.date, float]:
    """Hours of a running clock per local day (so far)."""
    out: Dict[dt.date, float] = {}
    total = _worked_seconds(s)
    t0 = local_midnight(today())
    today_part = total if s["started_at"] >= t0 else max(0.0, total - _worked_seconds(s, t0))
    out[today()] = today_part / 3600
    if total - today_part > 0:
        out[(t0 - dt.timedelta(seconds=1)).astimezone(TZ).date()] = (total - today_part) / 3600
    return out


def _backfill_profiles(conn) -> None:
    """Logins made before User Access linked HR records get one now (linked by email, so never duplicated)."""
    for r in q(conn, """SELECT u.id::text AS id FROM placeware_users u
                        WHERE NOT EXISTS (SELECT 1 FROM placeware_staff s WHERE s.user_id = u.id)"""):
        ensure_profile(conn, r["id"])


def overview(week: Optional[str] = None) -> Dict[str, Any]:
    ws = _week(week)
    we = ws + dt.timedelta(days=6)
    is_current = ws == week_start()
    with tx() as conn:
        _backfill_profiles(conn)
        ppl = people(conn)
        entries = _entries(conn, ws, we)
        sessions = _open_sessions(conn) if is_current else {}
        trend_rows = q(conn, """SELECT date_trunc('week', date)::date AS wk, SUM(hours_worked) AS h,
                                       COUNT(DISTINCT COALESCE(user_id::text, staff_id::text)) AS people
                                FROM placeware_timesheets WHERE status<>'rejected' AND date >= %s AND date <= %s GROUP BY 1""",
                           (ws - dt.timedelta(weeks=7), we))
        pending = q1(conn, """SELECT COUNT(*) AS n, COALESCE(SUM(hours_worked),0) AS h FROM placeware_timesheets WHERE status='submitted'""")
    online = online_ids()
    grid = []
    dept_hours: Dict[str, float] = defaultdict(float)
    saved_total = live_total = 0.0
    for p in ppl:
        days = {d: 0.0 for d in DAYS}
        saved = 0.0
        for e in entries:
            if e["person"] == p["key"] and e["status"] != "rejected":
                h = float(e["hours_worked"])
                days[DAYS[e["date"].weekday()]] += h
                saved += h
                dept_hours[e["department"] or p["department"]] += h
        s = sessions.get(p["user_id"]) if p["user_id"] else None
        live = 0.0
        if s:
            for d, h in _live_by_day(s).items():
                if ws <= d <= we:
                    days[DAYS[d.weekday()]] += h
                    live += h
            dept_hours[s["department"] or p["department"]] += live
        saved_total += saved
        live_total += live
        status = ("on_break" if s and s["break_started_at"] else "working" if s else
                  "online" if p["user_id"] in online else "offline")
        total = saved + live
        grid.append({"key": p["key"], "user_id": p["user_id"], "name": p["name"], "department": p["department"],
                     "job_title": p["job_title"], "has_login": p["has_login"], "status": status,
                     "clocked_in_at": s["started_at"] if s else None, "days": {d: round(v, 2) for d, v in days.items()},
                     "saved": round(saved, 2), "live": round(live, 2), "total": round(total, 2),
                     "target": p["weekly_hours"], "pct": round(100 * total / p["weekly_hours"]) if p["weekly_hours"] else None,
                     "pending": sum(1 for e in entries if e["person"] == p["key"] and e["status"] == "submitted")})
    grid.sort(key=lambda r: (-r["total"], r["name"].lower()))
    on_clock = [r for r in grid if r["status"] in ("working", "on_break")]
    long_clocks = [r for r in on_clock if r["clocked_in_at"] and now() - r["clocked_in_at"] > dt.timedelta(hours=12)]
    trend = {r["wk"]: r for r in trend_rows}
    weeks = []
    for i in range(7, -1, -1):
        w = ws - dt.timedelta(weeks=i)
        r = trend.get(w)
        h = float(r["h"]) if r else 0.0
        if w == ws:
            h += live_total
        weeks.append({"week": w, "hours": round(h, 1), "people": int(r["people"]) if r else 0})
    worked_days = defaultdict(float)
    for r in grid:
        for d, h in r["days"].items():
            worked_days[d] += h
    return {
        "week": ws, "week_end": we, "is_current": is_current, "as_of": now(),
        "headcount": len(ppl), "with_login": sum(1 for p in ppl if p["has_login"]),
        "online": [{"user_id": r["user_id"], "name": r["name"], "department": r["department"], "status": r["status"]}
                   for r in grid if r["user_id"] in online],
        "on_clock": [{k: r[k] for k in ("key", "name", "department", "status", "clocked_in_at")} for r in on_clock],
        "hours_total": round(saved_total + live_total, 2), "hours_saved": round(saved_total, 2), "hours_live": round(live_total, 2),
        "people_with_hours": sum(1 for r in grid if r["total"] > 0),
        "avg_per_person": round((saved_total + live_total) / max(1, sum(1 for r in grid if r["total"] > 0)), 1),
        "pending_approval": {"entries": int(pending["n"] or 0), "hours": float(pending["h"] or 0)},
        "long_clocks": [{k: r[k] for k in ("key", "name", "clocked_in_at")} for r in long_clocks],
        "grid": grid,
        "by_day": [{"day": d, "hours": round(worked_days[d], 2)} for d in DAYS],
        "by_department": sorted(({"department": k, "hours": round(v, 2)} for k, v in dept_hours.items() if v > 0),
                                key=lambda x: -x["hours"]),
        "weeks": weeks,
    }


def directory() -> Dict[str, Any]:
    ws = week_start()
    with tx() as conn:
        _backfill_profiles(conn)
        ppl = people(conn, include_inactive=True)
        sessions = _open_sessions(conn)
        hours = {r["person"]: float(r["h"]) for r in q(conn, """SELECT COALESCE(user_id::text, 'staff:' || staff_id::text) AS person,
                                                                        SUM(hours_worked) AS h FROM placeware_timesheets
                                                                 WHERE date >= %s AND status<>'rejected' GROUP BY 1""", (ws,))}
        load = {r["uid"]: r for r in q(conn, """SELECT assigned_to::text AS uid, COUNT(*) AS open,
                                                       COUNT(*) FILTER (WHERE COALESCE(due_date, reminder_at) < %s) AS overdue
                                                FROM placeware_tasks WHERE status IN %s AND kind<>'note' GROUP BY 1""",
                                         (now(), OPEN_STATUSES))}
        last = {r["uid"]: r["at"] for r in q(conn, """SELECT user_id::text AS uid, MAX(started_at) AS at FROM staff_time_sessions GROUP BY 1""")}
    online = online_ids()
    out = []
    for p in ppl:
        s = sessions.get(p["user_id"]) if p["user_id"] else None
        live = _worked_seconds(s) / 3600 if s else 0
        l = load.get(p["user_id"]) or {}
        out.append({**p, "status": ("on_break" if s and s["break_started_at"] else "working" if s else
                                    "online" if p["user_id"] in online else "offline") if p["active"] else "inactive",
                    "hours_week": round(hours.get(p["key"], 0) + live, 1), "open_tasks": int(l.get("open") or 0),
                    "overdue_tasks": int(l.get("overdue") or 0), "last_clock_in": last.get(p["user_id"])})
    depts = defaultdict(int)
    for p in out:
        if p["active"]:
            depts[p["department"]] += 1
    return {"people": out, "departments": DEPARTMENTS,
            "by_department": sorted(({"department": k, "count": v} for k, v in depts.items()), key=lambda x: -x["count"]),
            "counts": {"active": sum(1 for p in out if p["active"]), "inactive": sum(1 for p in out if not p["active"]),
                       "no_login": sum(1 for p in out if not p["has_login"]),
                       "working": sum(1 for p in out if p["status"] in ("working", "on_break")),
                       "online": sum(1 for p in out if p["status"] != "offline" and p["status"] != "inactive")}}


def _resolve(conn, key: str) -> Dict[str, Any]:
    pm = person_map(conn)
    p = pm.get(key)
    if not p:
        raise LookupError("Staff member not found")
    return p


def person(key: str) -> Dict[str, Any]:
    ws = week_start()
    with tx() as conn:
        p = _resolve(conn, key)
        entries = q(conn, """SELECT id, date, hours_worked, department, activity_note, source, status, review_note, approved_at
                             FROM placeware_timesheets WHERE (user_id::text=%s OR ('staff:' || staff_id::text)=%s)
                               AND date >= %s ORDER BY date DESC, id DESC""", (p["user_id"] or "", key, ws - dt.timedelta(weeks=8)))
        sessions = q(conn, """SELECT id::text AS id, started_at, ended_at, break_seconds, breaks, note FROM staff_time_sessions
                              WHERE user_id::text=%s ORDER BY started_at DESC LIMIT 20""", (p["user_id"] or "",))
        work = q1(conn, """SELECT COUNT(*) FILTER (WHERE status IN %s AND kind<>'note') AS open,
                                  COUNT(*) FILTER (WHERE status='completed' AND completed_by::text=%s AND completed_at >= %s) AS done_week,
                                  COUNT(*) FILTER (WHERE status='completed' AND completed_by::text=%s AND completed_at >= now() - interval '30 days') AS done_30d
                           FROM placeware_tasks WHERE assigned_to::text=%s OR completed_by::text=%s""",
                   (OPEN_STATUSES, p["user_id"] or "", local_midnight(ws), p["user_id"] or "", p["user_id"] or "", p["user_id"] or ""))
        reqs = q1(conn, """SELECT COUNT(*) FILTER (WHERE responded_by::text=%s AND responded_at > now() - interval '30 days') AS answered
                           FROM staff_requests""", (p["user_id"] or "",))
        open_s = _open_sessions(conn).get(p["user_id"]) if p["user_id"] else None
    weeks = []
    for i in range(7, -1, -1):
        w = ws - dt.timedelta(weeks=i)
        h = sum(float(e["hours_worked"]) for e in entries if w <= e["date"] <= w + dt.timedelta(days=6) and e["status"] != "rejected")
        weeks.append({"week": w, "hours": round(h, 2)})
    live = _live_by_day(open_s) if open_s else {}
    days = []
    for i in range(7):
        d = ws + dt.timedelta(days=i)
        h = sum(float(e["hours_worked"]) for e in entries if e["date"] == d and e["status"] != "rejected") + live.get(d, 0)
        days.append({"day": DAYS[i], "date": d, "hours": round(h, 2)})
    weeks[-1]["hours"] = round(weeks[-1]["hours"] + sum(v for d, v in live.items() if d >= ws), 2)
    for s in sessions:
        end = s["ended_at"] or now()
        s["worked_seconds"] = int(max(0, (end - s["started_at"]).total_seconds() - s["break_seconds"]))
    return {**p, "clock": None if not open_s else {"started_at": open_s["started_at"], "on_break": bool(open_s["break_started_at"]),
                                                   "worked_seconds": int(_worked_seconds(open_s))},
            "status": "working" if open_s else ("online" if p["user_id"] in online_ids() else "offline"),
            "week_days": days, "weeks": weeks, "entries": entries[:40], "sessions": sessions,
            "work": {"open_tasks": int(work["open"] or 0), "done_week": int(work["done_week"] or 0),
                     "done_30d": int(work["done_30d"] or 0), "requests_answered_30d": int(reqs["answered"] or 0)}}


def update_person(user: Dict[str, Any], key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    with tx() as conn:
        p = _resolve(conn, key)
        staff_id = p["staff_id"] or ensure_profile(conn, p["user_id"])
        sets, vals = [], []
        fields = {"name": "full_name", "department": "department", "job_title": "role", "phone": "phone", "branch": "branch",
                  "start_date": "start_date", "weekly_hours": "weekly_hours"}
        for k, col in fields.items():
            if k in data:
                v = data[k]
                if isinstance(v, str):
                    v = v.strip() or None
                if k == "name" and not v:
                    raise ValueError("A name is required")
                if k == "department" and v not in DEPARTMENTS:
                    raise ValueError("Unknown department")
                if k == "weekly_hours" and (v is None or not 0 < float(v) <= 80):
                    raise ValueError("Weekly hours must be between 1 and 80")
                sets.append(f"{col}=%s"); vals.append(v)
        if "active" in data and not p["has_login"]:
            sets.append("status=%s"); vals.append("active" if data["active"] else "inactive")
        if sets:
            ex(conn, f"UPDATE placeware_staff SET {', '.join(sets)}, updated_at=now() WHERE staff_id=%s::uuid", (*vals, staff_id))
            ex(conn, """INSERT INTO placeware_audit_logs (event_type, event_class, action, outcome, actor_id, subject_type, subject_id, details)
                        VALUES ('hr_profile_updated', 'hr', 'update_profile', 'success', %s, 'staff', %s, %s::jsonb)""",
               (str(user.get("sub")), staff_id, __import__("json").dumps({k: str(data[k]) for k in data if k in fields}, default=str)))
    return person(key)


def create_person(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """HR-only record (someone without a login yet). Linked automatically when a login with that email is created."""
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name or "@" not in email:
        raise ValueError("Name and email are required")
    if data.get("department") not in DEPARTMENTS:
        raise ValueError("Choose a department")
    with tx() as conn:
        if q1(conn, "SELECT 1 FROM placeware_staff WHERE lower(email)=%s", (email,)):
            raise ValueError("A staff record with this email already exists")
        u = q1(conn, "SELECT id::text AS id FROM placeware_users WHERE lower(email)=%s", (email,))
        r = q1(conn, """INSERT INTO placeware_staff (full_name, email, department, role, phone, status, user_id)
                        VALUES (%s, %s, %s, %s, %s, 'active', %s) RETURNING staff_id::text AS staff_id""",
               (name, email, data["department"], (data.get("job_title") or "").strip() or None,
                (data.get("phone") or "").strip() or None, u["id"] if u else None))
    return person(u["id"] if u else f"staff:{r['staff_id']}")


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------

_ALL_TIME = dt.date(2000, 1, 1)


def timesheets(week: Optional[str] = None, person_key: Optional[str] = None, status: Optional[str] = None,
               pending: bool = False) -> Dict[str, Any]:
    """One week of entries, or with `pending` every entry still awaiting approval, whatever its week -
    the same set the overview's "Awaiting approval" card counts."""
    ws = _week(week)
    we = ws + dt.timedelta(days=6)
    if pending:
        status = "submitted"
    with tx() as conn:
        rows = _entries(conn, _ALL_TIME, today()) if pending else _entries(conn, ws, we)
        pm = person_map(conn)
        sessions = _open_sessions(conn) if ws == week_start() and not pending else {}
    approver_names = {k: v["name"] for k, v in pm.items()}
    out = []
    for r in rows:
        if person_key and r["person"] != person_key:
            continue
        if status and r["status"] != status:
            continue
        p = pm.get(r["person"], {})
        r["name"] = p.get("name", "Unknown")
        r["person_department"] = p.get("department")
        r["approved_by_name"] = approver_names.get(r["approved_by"]) if r["approved_by"] else None
        r["recorded_by_name"] = approver_names.get(r["recorded_by"] or "", None)
        out.append(r)
    live = []
    for uid, s in sessions.items():
        if person_key and person_key != uid:
            continue
        live.append({"person": uid, "name": pm.get(uid, {}).get("name", "Unknown"), "started_at": s["started_at"],
                     "on_break": bool(s["break_started_at"]), "hours_so_far": round(_worked_seconds(s) / 3600, 2),
                     "department": s["department"]})
    per: Dict[str, Dict[str, Any]] = {}
    for r in out:
        g = per.setdefault(r["person"], {"person": r["person"], "name": r["name"], "hours": 0.0, "approved": 0.0,
                                         "submitted": 0.0, "rejected": 0.0, "entries": 0})
        g["entries"] += 1
        g[r["status"]] += float(r["hours_worked"])
        if r["status"] != "rejected":
            g["hours"] += float(r["hours_worked"])
    for l in live:
        g = per.setdefault(l["person"], {"person": l["person"], "name": l["name"], "hours": 0.0, "approved": 0.0,
                                         "submitted": 0.0, "rejected": 0.0, "entries": 0})
        g["live"] = l["hours_so_far"]
    return {"week": ws, "week_end": we, "pending": pending, "entries": out, "live": live,
            "people": sorted(per.values(), key=lambda g: -(g["hours"] + g.get("live", 0))),
            "totals": {"hours": round(sum(g["hours"] for g in per.values()), 2),
                       "live": round(sum(l["hours_so_far"] for l in live), 2),
                       "submitted": round(sum(g["submitted"] for g in per.values()), 2),
                       "approved": round(sum(g["approved"] for g in per.values()), 2)}}


def add_entry(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """HR records hours for someone (e.g. a missed clock-in). Approved as it is entered by HR."""
    me = _me(user)
    hours = float(data.get("hours") or 0)
    if not 0 < hours <= 24:
        raise ValueError("Hours must be more than 0 and at most 24")
    d = dt.date.fromisoformat(str(data.get("date"))[:10])
    if d > today():
        raise ValueError("Hours cannot be recorded for a future date")
    with tx() as conn:
        p = _resolve(conn, str(data.get("person") or ""))
        staff_id = p["staff_id"] or ensure_profile(conn, p["user_id"])
        r = q1(conn, """INSERT INTO placeware_timesheets (staff_id, user_id, date, hours_worked, department, activity_note, recorded_by,
                                                          source, status, approved_by, approved_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'hr', 'approved', %s, now()) RETURNING id""",
               (staff_id, p["user_id"], d, round(hours, 2), data.get("department") or p["department"],
                (data.get("note") or "").strip() or "Recorded by HR", me, me))
    return {"id": r["id"]}


def review(user: Dict[str, Any], entry_id: int, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
    me = _me(user)
    note = (data.get("note") or "").strip() or None
    with tx() as conn:
        e = q1(conn, "SELECT id, status, hours_worked, user_id::text AS user_id FROM placeware_timesheets WHERE id=%s FOR UPDATE", (entry_id,))
        if not e:
            raise LookupError("Timesheet entry not found")
        if action == "approve":
            ex(conn, """UPDATE placeware_timesheets SET status='approved', approved_by=%s, approved_at=now(),
                               review_note=COALESCE(%s, review_note) WHERE id=%s""", (me, note, entry_id))
        elif action == "reject":
            if not note:
                raise ValueError("Say why the entry is rejected")
            ex(conn, """UPDATE placeware_timesheets SET status='rejected', approved_by=%s, approved_at=now(), review_note=%s
                        WHERE id=%s""", (me, note, entry_id))
        elif action == "adjust":
            hours = float(data.get("hours") or 0)
            if not 0 < hours <= 24:
                raise ValueError("Hours must be more than 0 and at most 24")
            if not note:
                raise ValueError("Say why the hours are changed")
            ex(conn, """UPDATE placeware_timesheets SET hours_worked=%s, status='approved', approved_by=%s, approved_at=now(),
                               review_note=%s WHERE id=%s""", (round(hours, 2), me, f"{float(e['hours_worked']):g}h → {hours:g}h: {note}", entry_id))
        else:
            raise ValueError("Unknown action")
        if e["user_id"] and action in ("reject", "adjust"):
            from src.services.staff_workspace import notify
            notify(conn, [e["user_id"]], "hr", "action" if action == "reject" else "info",
                   f"Your timesheet was {'rejected' if action == 'reject' else 'adjusted'} by HR", note, "page", "/workspace?tab=progress", me)
    return {"ok": True}


def approve_week(user: Dict[str, Any], person_key: Optional[str], week: Optional[str], all_weeks: bool = False) -> Dict[str, Any]:
    me = _me(user)
    ws = _week(week)
    span = (_ALL_TIME, today()) if all_weeks else (ws, ws + dt.timedelta(days=6))
    with tx() as conn:
        r = q1(conn, """WITH u AS (UPDATE placeware_timesheets SET status='approved', approved_by=%s, approved_at=now()
                                   WHERE status='submitted' AND date BETWEEN %s AND %s
                                     AND (%s::text IS NULL OR COALESCE(user_id::text, 'staff:' || staff_id::text)=%s)
                                   RETURNING 1) SELECT COUNT(*) AS n FROM u""",
               (me, span[0], span[1], person_key, person_key))
    return {"approved": int(r["n"])}


def timesheets_csv(week: Optional[str] = None) -> str:
    data = timesheets(week)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Department", "Date", "Hours", "Source", "Status", "Note", "Reviewed by", "Review note"])
    for e in data["entries"]:
        w.writerow([e["name"], e["department"], e["date"], f"{float(e['hours_worked']):g}", e["source"], e["status"],
                    e["activity_note"] or "", e["approved_by_name"] or "", e["review_note"] or ""])
    for l in data["live"]:
        w.writerow([l["name"], l["department"] or "", today(), f"{l['hours_so_far']:g}", "clock (running)", "not yet saved", "", "", ""])
    return buf.getvalue()
