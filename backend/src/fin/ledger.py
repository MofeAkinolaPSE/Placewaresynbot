"""General Ledger and Trial Balance - read-only views over posted lines.

Nothing here stores a balance: every figure is summed from fin_v_general_ledger,
so the GL can never drift from the journals (Foundation Pack §27).
Balances are signed debit-positive internally; presentation (which column,
which sign) is the caller's concern.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from src.fin.db import ZERO, money, q, q1
from src.fin.errors import not_found


def _dims(filters: Dict[str, Any], params: List[Any], alias: str = "g") -> str:
    sql = ""
    for col in ("branch_id", "department_id", "cost_centre_id", "customer_id", "supplier_id", "product_sku"):
        if filters.get(col):
            sql += f" AND {alias}.{col} = %s"
            params.append(filters[col])
    return sql


def trial_balance(conn, entity_id: str, date_from: dt.date, date_to: dt.date,
                  include_zero: bool = False, **filters: Any) -> Dict[str, Any]:
    dim_params: List[Any] = []
    dims = _dims(filters, dim_params)
    rows = q(conn, f"""
        SELECT a.id AS account_id, a.code, a.name, a.account_type, a.subtype, a.normal_balance, a.status,
               COALESCE(SUM(CASE WHEN g.journal_date < %s THEN g.debit - g.credit END), 0) AS opening,
               COALESCE(SUM(CASE WHEN g.journal_date >= %s AND g.journal_date <= %s THEN g.debit END), 0) AS period_debit,
               COALESCE(SUM(CASE WHEN g.journal_date >= %s AND g.journal_date <= %s THEN g.credit END), 0) AS period_credit
        FROM fin_accounts a
        LEFT JOIN fin_v_general_ledger g ON g.account_id = a.id {dims}
        WHERE a.legal_entity_id = %s
        GROUP BY a.id ORDER BY a.code
    """, [date_from, date_from, date_to, date_from, date_to] + dim_params + [entity_id])
    out, tot = [], {"opening_debit": ZERO, "opening_credit": ZERO, "period_debit": ZERO,
                    "period_credit": ZERO, "closing_debit": ZERO, "closing_credit": ZERO}
    for r in rows:
        opening = money(r["opening"])
        pd, pc = money(r["period_debit"]), money(r["period_credit"])
        closing = opening + pd - pc
        if not include_zero and opening == 0 and pd == 0 and pc == 0:
            continue
        r.update(opening=opening, period_debit=pd, period_credit=pc, closing=closing,
                 opening_debit=max(opening, ZERO), opening_credit=max(-opening, ZERO),
                 closing_debit=max(closing, ZERO), closing_credit=max(-closing, ZERO))
        for k in tot:
            tot[k] += r[k]
        out.append(r)
    return {
        "date_from": date_from, "date_to": date_to, "rows": out, "totals": tot,
        "balanced": tot["closing_debit"] == tot["closing_credit"] and tot["period_debit"] == tot["period_credit"],
        "difference": tot["closing_debit"] - tot["closing_credit"],
    }


def account_balance(conn, entity_id: str, account_id: str, as_of: dt.date) -> Any:
    r = q1(conn, """SELECT COALESCE(SUM(debit - credit),0) b FROM fin_v_general_ledger
                    WHERE legal_entity_id=%s AND account_id=%s AND journal_date <= %s""",
           (entity_id, account_id, as_of))
    return money(r["b"])


def account_activity(conn, entity_id: str, account_id: str, date_from: dt.date, date_to: dt.date,
                     limit: int = 1000, offset: int = 0, **filters: Any) -> Dict[str, Any]:
    acct = q1(conn, "SELECT * FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (account_id, entity_id))
    if not acct:
        raise not_found("Account", account_id)
    p0: List[Any] = [entity_id, account_id, date_from]
    d0 = _dims(filters, p0)
    opening = money(q1(conn, f"""SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger g
                                  WHERE g.legal_entity_id=%s AND g.account_id=%s AND g.journal_date < %s {d0}""", p0)["b"])
    p1: List[Any] = [entity_id, account_id, date_from, date_to]
    d1 = _dims(filters, p1)
    # Running balance must include rows skipped by OFFSET, so compute it in SQL.
    rows = q(conn, f"""
        SELECT * FROM (
            SELECT g.line_id, g.journal_id, g.journal_number, g.journal_date, g.journal_type, g.source_type,
                   g.source_id, g.source_ref, COALESCE(g.description, g.journal_description) AS description,
                   g.debit, g.credit, g.customer_id, g.supplier_id, g.product_sku,
                   %s + SUM(g.debit - g.credit) OVER (ORDER BY g.journal_date, g.journal_number, g.line_no
                                                     ROWS UNBOUNDED PRECEDING) AS running_balance,
                   ROW_NUMBER() OVER (ORDER BY g.journal_date, g.journal_number, g.line_no) AS rn
            FROM fin_v_general_ledger g
            WHERE g.legal_entity_id=%s AND g.account_id=%s AND g.journal_date BETWEEN %s AND %s {d1}
        ) x ORDER BY rn LIMIT %s OFFSET %s
    """, [opening] + p1 + [limit, offset])
    totals = q1(conn, f"""SELECT COALESCE(SUM(debit),0) d, COALESCE(SUM(credit),0) c, COUNT(*) n
                          FROM fin_v_general_ledger g WHERE g.legal_entity_id=%s AND g.account_id=%s
                          AND g.journal_date BETWEEN %s AND %s {d1}""", p1)
    d, c = money(totals["d"]), money(totals["c"])
    return {"account": acct, "date_from": date_from, "date_to": date_to, "opening": opening,
            "total_debit": d, "total_credit": c, "closing": opening + d - c,
            "count": totals["n"], "rows": rows}


def general_ledger(conn, entity_id: str, date_from: dt.date, date_to: dt.date,
                   account_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Every account with activity: opening, lines, closing (Sage 'General Ledger' report)."""
    tb = trial_balance(conn, entity_id, date_from, date_to)
    wanted = set(account_ids or [])
    out = []
    for r in tb["rows"]:
        if wanted and str(r["account_id"]) not in wanted:
            continue
        act = account_activity(conn, entity_id, str(r["account_id"]), date_from, date_to, limit=100000)
        out.append({"account_id": r["account_id"], "code": r["code"], "name": r["name"],
                    "opening": act["opening"], "closing": act["closing"], "rows": act["rows"]})
    return out
