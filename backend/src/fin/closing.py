"""Year-end close and budgets.

Year-end: every income/expense (and 'gets closed' equity, e.g. drawings)
balance is zeroed into Retained Earnings by one CLOSING journal dated the
last day of the year, the last period is closed through the normal
checklist, and the year is locked. The next year must exist first so the
business can keep posting.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List

from src.fin import audit, periods, posting, rules
from src.fin.db import ZERO, ex, money, q, q1
from src.fin.errors import FinError, invalid, not_found


def close_fiscal_year(conn, ctx, fiscal_year_id: str) -> Dict[str, Any]:
    ctx.require("finance.period.close")
    fy = q1(conn, "SELECT * FROM fin_fiscal_years WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (fiscal_year_id, ctx.entity_id))
    if not fy:
        raise not_found("Fiscal year", fiscal_year_id)
    if fy["status"] == "CLOSED":
        raise FinError("INVALID_STATE_TRANSITION", f"{fy['name']} is already closed")
    earlier = q1(conn, "SELECT name FROM fin_fiscal_years WHERE legal_entity_id=%s AND start_date < %s AND status='OPEN'",
                 (ctx.entity_id, fy["start_date"]))
    if earlier:
        raise FinError("CLOSE_BLOCKED", f"Close {earlier['name']} first")
    nxt = q1(conn, "SELECT id FROM fin_fiscal_years WHERE legal_entity_id=%s AND start_date = %s",
             (ctx.entity_id, fy["end_date"] + dt.timedelta(days=1)))
    if not nxt:
        periods.create_fiscal_year(conn, ctx, fy["end_date"] + dt.timedelta(days=1))
    still_open = q(conn, """SELECT name FROM fin_periods WHERE fiscal_year_id=%s AND status='OPEN' AND end_date < %s
                            ORDER BY start_date""", (fiscal_year_id, fy["end_date"]))
    if still_open:
        raise FinError("CLOSE_BLOCKED", f"Close the year's periods first ({', '.join(p['name'] for p in still_open)})")
    re_acct = rules.account(conn, ctx.entity_id, "RETAINED_EARNINGS")
    bals = q(conn, """SELECT account_id, SUM(debit) d, SUM(credit) c FROM fin_v_general_ledger
                      WHERE legal_entity_id=%s AND journal_date <= %s
                        AND (account_type IN ('REVENUE','EXPENSE') OR subtype='EQUITY_CLOSING')
                      GROUP BY account_id HAVING SUM(debit) <> SUM(credit)""", (ctx.entity_id, fy["end_date"]))
    lines: List[Dict[str, Any]] = []
    net = ZERO
    for b in bals:
        bal = money(b["d"]) - money(b["c"])
        lines.append({"account_id": b["account_id"], ("credit" if bal > 0 else "debit"): abs(bal),
                      "description": f"Close {fy['name']}"})
        net += bal
    journal = None
    if lines:
        lines.append({"account_id": re_acct["id"], ("debit" if net > 0 else "credit"): abs(net),
                      "description": f"{fy['name']} result to retained earnings"})
        journal = posting.post_system(conn, ctx, event_type="YEAR_END_CLOSED", journal_date=fy["end_date"], lines=lines,
                                      description=f"Year-end close {fy['name']}", source_type="YEAR_END",
                                      source_id=fiscal_year_id, source_ref=fy["name"], journal_type="CLOSING")
    last = q1(conn, "SELECT * FROM fin_periods WHERE fiscal_year_id=%s ORDER BY period_number DESC LIMIT 1", (fiscal_year_id,))
    if last["status"] == "OPEN":
        periods.close_period(conn, ctx, str(last["id"]), force_warnings=True)
    ex(conn, "UPDATE fin_fiscal_years SET status='CLOSED', closing_journal_id=%s, closed_at=now(), closed_by=%s WHERE id=%s",
       (journal["id"] if journal else None, ctx.actor_id, fiscal_year_id))
    audit.record(conn, ctx, "FISCAL_YEAR_CLOSED", "fiscal_year", fiscal_year_id, ref=fy["name"],
                 metadata={"result_to_retained_earnings": str(-net), "journal": journal["journal_number"] if journal else None})
    return {"fiscal_year": fy["name"], "net_profit": -net, "journal": journal}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def list_budgets(conn, entity_id: str) -> List[Dict[str, Any]]:
    return q(conn, """SELECT b.*, f.name AS fiscal_year, COALESCE(SUM(l.amount),0) AS total, COUNT(DISTINCT l.account_id) AS accounts
                      FROM fin_budgets b JOIN fin_fiscal_years f ON f.id=b.fiscal_year_id
                      LEFT JOIN fin_budget_lines l ON l.budget_id=b.id
                      WHERE b.legal_entity_id=%s GROUP BY b.id, f.name, f.start_date ORDER BY f.start_date DESC, b.name""", (entity_id,))


def create_budget(conn, ctx, fiscal_year_id: str, name: str) -> Dict[str, Any]:
    ctx.require("budget.edit")
    fy = q1(conn, "SELECT id FROM fin_fiscal_years WHERE id=%s AND legal_entity_id=%s", (fiscal_year_id, ctx.entity_id))
    if not fy:
        raise not_found("Fiscal year", fiscal_year_id)
    b = q1(conn, "INSERT INTO fin_budgets (legal_entity_id, fiscal_year_id, name, created_by) VALUES (%s,%s,%s,%s) RETURNING *",
           (ctx.entity_id, fiscal_year_id, name.strip(), ctx.actor_id))
    audit.record(conn, ctx, "BUDGET_CREATED", "budget", b["id"], ref=name)
    return b


def get_budget(conn, entity_id: str, budget_id: str) -> Dict[str, Any]:
    b = q1(conn, "SELECT b.*, f.name AS fiscal_year FROM fin_budgets b JOIN fin_fiscal_years f ON f.id=b.fiscal_year_id WHERE b.id=%s AND b.legal_entity_id=%s",
           (budget_id, entity_id))
    if not b:
        raise not_found("Budget", budget_id)
    b["periods"] = q(conn, "SELECT id, name, period_number FROM fin_periods WHERE fiscal_year_id=%s ORDER BY period_number", (b["fiscal_year_id"],))
    rows = q(conn, """SELECT l.account_id, a.code, a.name, l.period_id, l.amount FROM fin_budget_lines l
                      JOIN fin_accounts a ON a.id=l.account_id WHERE l.budget_id=%s ORDER BY a.code""", (budget_id,))
    accounts: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        acc = accounts.setdefault(str(r["account_id"]), {"account_id": str(r["account_id"]), "code": r["code"], "name": r["name"],
                                                         "amounts": {}, "total": ZERO})
        acc["amounts"][str(r["period_id"])] = r["amount"]
        acc["total"] += money(r["amount"])
    b["lines"] = list(accounts.values())
    return b


def set_budget_lines(conn, ctx, budget_id: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """lines: [{account_id, amounts: {period_id: amount}} | {account_id, annual: amount}] (annual is spread evenly)."""
    ctx.require("budget.edit")
    b = get_budget(conn, ctx.entity_id, budget_id)
    if b["status"] == "APPROVED":
        raise FinError("INVALID_STATE_TRANSITION", "An approved budget is locked; copy it to revise")
    pids = [str(p["id"]) for p in b["periods"]]
    for l in lines:
        acct = q1(conn, "SELECT id, account_type FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (l["account_id"], ctx.entity_id))
        if not acct:
            raise not_found("Account", l["account_id"])
        if l.get("remove"):
            ex(conn, "DELETE FROM fin_budget_lines WHERE budget_id=%s AND account_id=%s", (budget_id, acct["id"]))
            continue
        amounts = l.get("amounts") or {}
        if l.get("annual") not in (None, ""):
            annual = money(l["annual"])
            each = (annual / Decimal(len(pids))).quantize(Decimal("0.01"))
            amounts = {pid: each for pid in pids}
            amounts[pids[-1]] = annual - each * (len(pids) - 1)
        ex(conn, "DELETE FROM fin_budget_lines WHERE budget_id=%s AND account_id=%s", (budget_id, acct["id"]))
        for pid, amt in amounts.items():
            if pid not in pids:
                raise invalid("Budget amounts must fall in the budget's fiscal year")
            if money(amt) != 0:
                ex(conn, "INSERT INTO fin_budget_lines (budget_id, account_id, period_id, amount) VALUES (%s,%s,%s,%s)",
                   (budget_id, acct["id"], pid, money(amt)))
    audit.record(conn, ctx, "BUDGET_UPDATED", "budget", budget_id, ref=b["name"], metadata={"accounts": len(lines)})
    return get_budget(conn, ctx.entity_id, budget_id)


def update_budget(conn, ctx, budget_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Rename a budget, or reopen an approved one to draft so it can be edited again."""
    ctx.require("budget.edit")
    b = get_budget(conn, ctx.entity_id, budget_id)
    if data.get("name") and data["name"].strip() != b["name"]:
        ex(conn, "UPDATE fin_budgets SET name=%s WHERE id=%s", (data["name"].strip(), budget_id))
    if data.get("status") == "DRAFT" and b["status"] == "APPROVED":
        ctx.require("budget.approve")
        ex(conn, "UPDATE fin_budgets SET status='DRAFT', approved_by=NULL, approved_at=NULL WHERE id=%s", (budget_id,))
    audit.record(conn, ctx, "BUDGET_UPDATED", "budget", budget_id, ref=b["name"], after={k: v for k, v in data.items() if k in ("name", "status")})
    return get_budget(conn, ctx.entity_id, budget_id)


def delete_budget(conn, ctx, budget_id: str) -> Dict[str, Any]:
    """A budget is a plan, not a posting: it can be deleted (lines go with it); kept in the audit trail."""
    ctx.require("budget.edit")
    b = get_budget(conn, ctx.entity_id, budget_id)
    if b["status"] == "APPROVED":
        ctx.require("budget.approve")
    ex(conn, "DELETE FROM fin_budgets WHERE id=%s", (budget_id,))
    audit.record(conn, ctx, "BUDGET_DELETED", "budget", budget_id, ref=b["name"],
                 metadata={"fiscal_year": b["fiscal_year"], "status": b["status"]})
    return {"deleted": budget_id}


def copy_budget(conn, ctx, budget_id: str, name: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("budget.edit")
    b = get_budget(conn, ctx.entity_id, budget_id)
    n = q1(conn, "INSERT INTO fin_budgets (legal_entity_id, fiscal_year_id, name, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
           (ctx.entity_id, b["fiscal_year_id"], (name or f"{b['name']} (copy)").strip(), ctx.actor_id))
    ex(conn, """INSERT INTO fin_budget_lines (budget_id, account_id, period_id, amount)
                SELECT %s, account_id, period_id, amount FROM fin_budget_lines WHERE budget_id=%s""", (n["id"], budget_id))
    audit.record(conn, ctx, "BUDGET_COPIED", "budget", n["id"], ref=name, metadata={"from": b["name"]})
    return get_budget(conn, ctx.entity_id, n["id"])


def approve_budget(conn, ctx, budget_id: str) -> Dict[str, Any]:
    ctx.require("budget.approve")
    b = get_budget(conn, ctx.entity_id, budget_id)
    ex(conn, "UPDATE fin_budgets SET status='APPROVED', approved_by=%s, approved_at=now() WHERE id=%s", (ctx.actor_id, budget_id))
    audit.record(conn, ctx, "BUDGET_APPROVED", "budget", budget_id, ref=b["name"])
    return get_budget(conn, ctx.entity_id, budget_id)
