"""Fiscal years and periods: open -> closed (-> reopened by authority).

Posting into a closed period is refused twice over: here with a clear
business error, and in the database trigger as the last line of defence.
"""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Any, Dict, List, Optional

from src.fin import audit
from src.fin.db import q, q1, ex
from src.fin.errors import FinError, invalid, not_found


def _month_end(d: dt.date) -> dt.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    y = d.year + m // 12
    return dt.date(y, m % 12 + 1, 1)


def create_fiscal_year(conn, ctx, start_date: dt.date) -> Dict[str, Any]:
    """Create a 12-month fiscal year with monthly periods, all OPEN."""
    ent = q1(conn, "SELECT fiscal_year_start_month FROM fin_legal_entities WHERE id=%s", (ctx.entity_id,))
    if start_date.day != 1 or start_date.month != int(ent["fiscal_year_start_month"]):
        raise invalid("A fiscal year must start on the 1st of the entity's fiscal start month",
                      fiscal_year_start_month=ent["fiscal_year_start_month"])
    end_date = _month_end(_add_months(start_date, 11))
    if q1(conn, """SELECT 1 FROM fin_fiscal_years WHERE legal_entity_id=%s
                   AND daterange(start_date, end_date, '[]') && daterange(%s, %s, '[]')""",
          (ctx.entity_id, start_date, end_date)):
        raise FinError("DUPLICATE_RESOURCE", "A fiscal year already covers these dates")
    name = f"FY {start_date.year}" if start_date.month == 1 else f"FY {start_date.year}/{end_date.year % 100:02d}"
    fy = q1(conn, """INSERT INTO fin_fiscal_years (legal_entity_id, name, start_date, end_date)
                     VALUES (%s,%s,%s,%s) RETURNING *""", (ctx.entity_id, name, start_date, end_date))
    for i in range(12):
        s = _add_months(start_date, i)
        ex(conn, """INSERT INTO fin_periods (legal_entity_id, fiscal_year_id, period_number, name, start_date, end_date)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
           (ctx.entity_id, fy["id"], i + 1, s.strftime("%b %Y"), s, _month_end(s)))
    audit.record(conn, ctx, "FISCAL_YEAR_CREATED", "fiscal_year", fy["id"], ref=name,
                 after={"start": start_date, "end": end_date})
    return fy


def period_for(conn, entity_id: str, on: dt.date) -> Dict[str, Any]:
    p = q1(conn, """SELECT * FROM fin_periods WHERE legal_entity_id=%s AND %s BETWEEN start_date AND end_date""",
           (entity_id, on))
    if not p:
        raise FinError("PERIOD_NOT_FOUND", f"No financial period covers {on:%d %b %Y}. Create the fiscal year first.",
                       {"date": on.isoformat()})
    return p


def require_open(conn, entity_id: str, on: dt.date) -> Dict[str, Any]:
    p = period_for(conn, entity_id, on)
    if p["status"] != "OPEN":
        raise FinError("PERIOD_CLOSED", f"{p['name']} is {p['status'].lower()}; nothing can be posted into it.",
                       {"period": p["name"], "status": p["status"]})
    return p


def list_years(conn, entity_id: str) -> List[Dict[str, Any]]:
    years = q(conn, "SELECT * FROM fin_fiscal_years WHERE legal_entity_id=%s ORDER BY start_date DESC", (entity_id,))
    periods = q(conn, "SELECT * FROM fin_periods WHERE legal_entity_id=%s ORDER BY start_date", (entity_id,))
    for y in years:
        y["periods"] = [p for p in periods if p["fiscal_year_id"] == y["id"]]
    return years


def close_period(conn, ctx, period_id: str, *, force_warnings: bool = False) -> Dict[str, Any]:
    ctx.require("finance.period.close")
    p = q1(conn, "SELECT * FROM fin_periods WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (period_id, ctx.entity_id))
    if not p:
        raise not_found("Period", period_id)
    if p["status"] != "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", f"{p['name']} is already {p['status'].lower()}")
    earlier_open = q1(conn, """SELECT name FROM fin_periods WHERE legal_entity_id=%s AND start_date < %s
                               AND status='OPEN' ORDER BY start_date LIMIT 1""", (ctx.entity_id, p["start_date"]))
    if earlier_open:
        raise FinError("CLOSE_BLOCKED", f"Close {earlier_open['name']} first; periods close in order.")
    from src.fin.controls import close_checklist  # late import: controls depends on ledger
    checklist = close_checklist(conn, ctx, p)
    blockers = [c for c in checklist if c["status"] == "FAIL" and c["blocking"]]
    warnings = [c for c in checklist if c["status"] == "FAIL" and not c["blocking"]]
    if blockers or (warnings and not force_warnings):
        raise FinError("CLOSE_BLOCKED", f"{p['name']} cannot be closed yet",
                       {"checklist": checklist, "blocking": len(blockers), "warnings": len(warnings)})
    ex(conn, "UPDATE fin_periods SET status='CLOSED', closed_at=now(), closed_by=%s WHERE id=%s",
       (ctx.actor_id, period_id))
    audit.record(conn, ctx, "PERIOD_CLOSED", "period", period_id, ref=p["name"],
                 metadata={"warnings_accepted": [w["code"] for w in warnings]})
    return {**p, "status": "CLOSED", "checklist": checklist}


def reopen_period(conn, ctx, period_id: str, reason: str) -> Dict[str, Any]:
    ctx.require("finance.period.reopen")
    if not (reason or "").strip():
        raise invalid("A reason is required to reopen a period")
    p = q1(conn, "SELECT * FROM fin_periods WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (period_id, ctx.entity_id))
    if not p:
        raise not_found("Period", period_id)
    fy = q1(conn, "SELECT status FROM fin_fiscal_years WHERE id=%s", (p["fiscal_year_id"],))
    if fy["status"] == "CLOSED":
        raise FinError("INVALID_STATE_TRANSITION", "The fiscal year is closed; its periods cannot be reopened")
    if p["status"] == "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", f"{p['name']} is already open")
    later_closed = q1(conn, """SELECT name FROM fin_periods WHERE legal_entity_id=%s AND start_date > %s
                               AND status<>'OPEN' ORDER BY start_date DESC LIMIT 1""", (ctx.entity_id, p["start_date"]))
    if later_closed:
        raise FinError("INVALID_STATE_TRANSITION", f"Reopen {later_closed['name']} first; periods reopen newest first.")
    ex(conn, "UPDATE fin_periods SET status='OPEN', closed_at=NULL, closed_by=NULL WHERE id=%s", (period_id,))
    audit.record(conn, ctx, "PERIOD_REOPENED", "period", period_id, ref=p["name"], reason=reason)
    return {**p, "status": "OPEN"}


def current_period(conn, entity_id: str, on: Optional[dt.date] = None) -> Optional[Dict[str, Any]]:
    return q1(conn, "SELECT * FROM fin_periods WHERE legal_entity_id=%s AND %s BETWEEN start_date AND end_date",
              (entity_id, on or dt.date.today()))
