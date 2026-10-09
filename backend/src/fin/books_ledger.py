"""One ledger across the Sage years and ACE Books.

Sage was the record up to and including ``fin_settings.history_until`` (H); ACE Books journals
are the record after it. Every report reads through this module so a date range can start in
2017 and end today, in one table, without the user knowing where the line came from:

    balance(account, d)   d <= H: Sage's Beginning Balance for d's month + Sage lines to d
                          d >  H: ACE Books journals up to d (the opening / roll-forward journals
                                  make ACE Books equal to Sage at H)
    lines(account, f, t)  Sage General Ledger lines for f..min(t,H) + ACE journal lines for
                          max(f,H+1)..t
Income and expense accounts restart each fiscal year (Sage closes them into retained earnings),
so a period's result is worked out per calendar year.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.fin import journal_map
from src.fin.db import ZERO, money, q, q1

ONE = dt.timedelta(days=1)

# ACE posting source -> the Sage journal code it corresponds to (shown in the Jrnl column)
PL_TYPES = ("REVENUE", "EXPENSE")


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

def history_until(conn, entity_id: str) -> Optional[dt.date]:
    s = q1(conn, "SELECT history_until, cutover_date FROM fin_settings WHERE legal_entity_id=%s", (entity_id,))
    if not s:
        return None
    if s["history_until"]:
        return s["history_until"]
    return s["cutover_date"] - ONE if s["cutover_date"] else None


def history_start(conn, entity_id: str) -> Optional[dt.date]:
    r = q1(conn, "SELECT MIN(period_start) d FROM fin_sage_gl_balances WHERE legal_entity_id=%s", (entity_id,))
    return r["d"] if r else None


def accounts(conn, entity_id: str) -> Dict[str, Dict[str, Any]]:
    return {a["code"]: a for a in q(conn, """SELECT id::text AS id, code, name, account_type, subtype, normal_balance, status
                                             FROM fin_accounts WHERE legal_entity_id=%s""", (entity_id,))}


def _hist_balances(conn, entity_id: str, d: dt.date, codes: Optional[List[str]] = None,
                   start_of_day: bool = False) -> Dict[str, Decimal]:
    """Sage balance (debit positive) of every account at the end of day d (or its start).
    Sage's own Beginning Balance for d's month is the anchor, so anything Sage changed in
    earlier months - and its year-end closing of income and expense - is always included.

    Shared across workers: one report makes several of these calls and every Books screen
    repeats them; the cache is dropped on any save (src/utils/shared_response.py)."""
    from src.utils.shared_response import shared_response
    key = f"fin:hist_bal:{entity_id}:{d}:{int(start_of_day)}:{','.join(sorted(codes)) if codes else '*'}"
    return shared_response(key, 300, lambda: _hist_balances_uncached(conn, entity_id, d, codes, start_of_day))


def _hist_balances_uncached(conn, entity_id: str, d: dt.date, codes: Optional[List[str]] = None,
                            start_of_day: bool = False) -> Dict[str, Decimal]:
    cf = " AND account_code = ANY(%s)" if codes else ""
    p: List[Any] = [entity_id, d] + ([codes] if codes else [])
    op = "<" if start_of_day else "<="
    # Corrections posted from Data exceptions (jrnl 'ADJ', no load) are not in Sage's own later
    # Beginning Balances, so they are carried past the anchor: balance-sheet accounts always,
    # income and expense within the correction's year.
    rows = q(conn, f"""
        WITH s AS (SELECT DISTINCT ON (account_code) account_code, period_start, beginning_balance
                   FROM fin_sage_gl_balances WHERE legal_entity_id=%s AND period_start <= %s {cf}
                   ORDER BY account_code, period_start DESC),
             -- an account Sage never used that a correction posted to (e.g. Inventory Adjustments)
             a AS (SELECT * FROM s UNION ALL
                   SELECT DISTINCT l.account_code, DATE '1900-01-01', 0::numeric FROM fin_sage_gl_lines l
                   WHERE l.legal_entity_id=%s AND l.jrnl='ADJ' AND l.load_id IS NULL
                     AND NOT EXISTS (SELECT 1 FROM s WHERE s.account_code=l.account_code) {cf.replace('account_code', 'l.account_code')})
        SELECT a.account_code, a.beginning_balance + COALESCE(m.v, 0) + COALESCE(c.v, 0) AS bal
        FROM a LEFT JOIN LATERAL (
            SELECT SUM(l.debit - l.credit) v FROM fin_sage_gl_lines l
            WHERE l.legal_entity_id=%s AND l.account_code=a.account_code AND l.txn_date >= a.period_start AND l.txn_date {op} %s
        ) m ON TRUE
        LEFT JOIN LATERAL (
            SELECT SUM(l.debit - l.credit) v FROM fin_sage_gl_lines l
            WHERE l.legal_entity_id=%s AND l.account_code=a.account_code AND l.jrnl='ADJ' AND l.load_id IS NULL
              AND l.txn_date < a.period_start
              AND (date_part('year', l.txn_date) = date_part('year', a.period_start)
                   OR NOT EXISTS (SELECT 1 FROM fin_accounts x WHERE x.legal_entity_id=l.legal_entity_id AND x.code=l.account_code
                                  AND x.account_type IN ('REVENUE','EXPENSE')))
        ) c ON TRUE""", p + [entity_id] + ([codes] if codes else []) + [entity_id, d, entity_id])
    return {r["account_code"]: money(r["bal"]) for r in rows}


def _ace_balances(conn, entity_id: str, d: dt.date, codes: Optional[List[str]] = None) -> Dict[str, Decimal]:
    cf = " AND account_code = ANY(%s)" if codes else ""
    p: List[Any] = [entity_id, d] + ([codes] if codes else [])
    return {r["account_code"]: money(r["bal"]) for r in q(conn, f"""
        SELECT account_code, SUM(debit - credit) AS bal FROM fin_v_general_ledger
        WHERE legal_entity_id=%s AND journal_date <= %s {cf} GROUP BY account_code""", p)}


def balances(conn, entity_id: str, d: dt.date, codes: Optional[List[str]] = None,
             fresh: bool = False) -> Dict[str, Decimal]:
    """Balance at the end of day d. fresh=True skips the shared cache (for code that posts
    journals from the figure, so it always sees this transaction's own data)."""
    h = history_until(conn, entity_id)
    if h and d <= h:
        return (_hist_balances_uncached if fresh else _hist_balances)(conn, entity_id, d, codes)
    return _ace_balances(conn, entity_id, d, codes)


def balances_at_start(conn, entity_id: str, d: dt.date, codes: Optional[List[str]] = None) -> Dict[str, Decimal]:
    """Balance brought forward into day d. On the 1st of a Sage month this is Sage's own
    Beginning Balance (income and expense start each year at Sage's figure, normally nil)."""
    h = history_until(conn, entity_id)
    if h and d <= h:
        return _hist_balances(conn, entity_id, d, codes, start_of_day=True)
    return _ace_balances(conn, entity_id, d - ONE, codes)


def _year_segments(f: dt.date, t: dt.date) -> List[Tuple[dt.date, dt.date]]:
    out, a = [], f
    while a <= t:
        b = min(t, dt.date(a.year, 12, 31))
        out.append((a, b))
        a = b + ONE
    return out


def movement(conn, entity_id: str, f: dt.date, t: dt.date) -> Dict[str, Decimal]:
    """Change in each account over f..t (debit positive). Income and expense accounts restart
    each year, so their change is added up year by year; balance-sheet accounts over the span."""
    acc = accounts(conn, entity_id)
    out: Dict[str, Decimal] = {}
    for a, b in _year_segments(f, t):
        end, start = balances(conn, entity_id, b), balances_at_start(conn, entity_id, a)
        for code in set(end) | set(start):
            if acc.get(code, {}).get("account_type") in PL_TYPES:
                v = end.get(code, ZERO) - start.get(code, ZERO)
                if v != 0:
                    out[code] = out.get(code, ZERO) + v
    end, start = balances(conn, entity_id, t), balances_at_start(conn, entity_id, f)
    for code in set(end) | set(start):
        if acc.get(code, {}).get("account_type") not in PL_TYPES:
            v = end.get(code, ZERO) - start.get(code, ZERO)
            if v != 0:
                out[code] = v
    return out


def ytd_pl(conn, entity_id: str, d: dt.date) -> Dict[str, Decimal]:
    """Income/expense balances for d's year to date."""
    acc = accounts(conn, entity_id)
    end, start = balances(conn, entity_id, d), balances_at_start(conn, entity_id, dt.date(d.year, 1, 1))
    out = {}
    for c in set(end) | set(start):
        if acc.get(c, {}).get("account_type") in PL_TYPES:
            v = end.get(c, ZERO) - start.get(c, ZERO)
            if v != 0:
                out[c] = v
    return out


# ---------------------------------------------------------------------------
# Lines (the General Ledger detail)
# ---------------------------------------------------------------------------

def lines(conn, entity_id: str, code: str, f: dt.date, t: dt.date, search: Optional[str] = None,
          limit: int = 20000) -> List[Dict[str, Any]]:
    h = history_until(conn, entity_id)
    out: List[Dict[str, Any]] = []
    sf_h = " AND (l.description ILIKE %s OR l.reference ILIKE %s)" if search else ""
    sf_a = " AND (COALESCE(g.description, g.journal_description) ILIKE %s OR g.source_ref ILIKE %s OR g.journal_number ILIKE %s)" if search else ""
    if h and f <= h:
        p: List[Any] = [entity_id, code, f, min(t, h)] + ([f"%{search}%"] * 2 if search else []) + [limit]
        for r in q(conn, f"""SELECT l.id, l.txn_date, l.reference, l.jrnl, l.description, l.debit, l.credit
                             FROM fin_sage_gl_lines l WHERE l.legal_entity_id=%s AND l.account_code=%s
                             AND l.txn_date BETWEEN %s AND %s {sf_h} ORDER BY l.txn_date, l.seq LIMIT %s""", p):
            out.append({"date": r["txn_date"], "reference": r["reference"], "jrnl": r["jrnl"], "description": r["description"],
                        "debit": r["debit"], "credit": r["credit"], "source": "sage", "sage_line_id": r["id"]})
    a_from = max(f, h + ONE) if h else f
    if a_from <= t:
        p = [entity_id, code, a_from, t] + ([f"%{search}%"] * 3 if search else []) + [limit]
        for r in q(conn, f"""SELECT g.line_id, g.journal_id, g.journal_number, g.journal_date, g.journal_type, g.source_type,
                                    g.source_id, g.source_ref, COALESCE(g.description, g.journal_description) AS description,
                                    g.debit, g.credit, g.customer_id, g.supplier_id, g.product_sku, {journal_map.code_sql()} AS jrnl
                             FROM fin_v_general_ledger g WHERE g.legal_entity_id=%s AND g.account_code=%s
                             AND g.journal_date BETWEEN %s AND %s {sf_a}
                             -- an entry deleted the same day (posted, then reversed on its own date) nets to nothing:
                             -- neither it nor its reversal is listed; both stay in Journals and the audit trail
                             AND NOT EXISTS (SELECT 1 FROM fin_journals jx JOIN fin_journals jy ON jy.id = COALESCE(jx.reversed_by_id, jx.reversal_of_id)
                                             WHERE jx.id = g.journal_id AND jy.journal_date = jx.journal_date)
                             ORDER BY g.journal_date, g.journal_number, g.line_no LIMIT %s""", p):
            out.append({"date": r["journal_date"], "reference": r["source_ref"] or r["journal_number"],
                        "jrnl": r["jrnl"], "description": r["description"],
                        "debit": r["debit"], "credit": r["credit"], "source": "ace", "journal_id": r["journal_id"],
                        "journal_number": r["journal_number"], "source_type": r["source_type"], "source_id": r["source_id"],
                        "line_id": r["line_id"]})
    return out


def _month_starts(f: dt.date, t: dt.date) -> List[dt.date]:
    out, m = [], f.replace(day=1)
    while m <= t:
        out.append(m)
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def gl_account(conn, entity_id: str, code: str, f: dt.date, t: dt.date, search: Optional[str] = None) -> Dict[str, Any]:
    """One account in Sage's General Ledger layout: for each month a Beginning Balance, every
    transaction (Date, Reference, Jrnl, Trans Description, Debit, Credit, Balance) and the
    Current Period Change; the Ending Balance last."""
    acc = accounts(conn, entity_id).get(code)
    if not acc:
        from src.fin.errors import not_found
        raise not_found("Account", code)
    h = history_until(conn, entity_id)
    hs = history_start(conn, entity_id)
    if hs and f < hs:
        f = hs  # nothing exists before the first Sage month
    if f > t:
        t = f
    all_lines = lines(conn, entity_id, code, f, t, search=search)
    months = []
    bal = balances_at_start(conn, entity_id, f, [code]).get(code, ZERO)
    opening = bal
    for m in _month_starts(f, t):
        start, end = max(m, f), min((m.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - ONE, t)
        # Each month opens on Sage's own Beginning Balance (it carries anything Sage changed in
        # earlier months after an export, and income/expense restarting in January).
        if start == m and start != f:
            bal = balances_at_start(conn, entity_id, m, [code]).get(code, ZERO)
        begin = bal
        rows = []
        for l in all_lines:
            if start <= l["date"] <= end:
                bal += money(l["debit"]) - money(l["credit"])
                rows.append({**l, "balance": bal})
        d = sum((money(l["debit"]) for l in rows), ZERO)
        c = sum((money(l["credit"]) for l in rows), ZERO)
        months.append({"period_start": start, "period_end": end, "beginning_balance": begin, "lines": rows,
                       "period_debit": d, "period_credit": c, "net_change": d - c, "ending_balance": bal})
    return {"account": acc, "date_from": f, "date_to": t, "history_until": h, "opening": opening, "closing": bal,
            "total_debit": sum((m["period_debit"] for m in months), ZERO),
            "total_credit": sum((m["period_credit"] for m in months), ZERO), "months": months}


def gl_summary(conn, entity_id: str, f: dt.date, t: dt.date, codes: Optional[List[str]] = None,
               include_zero: bool = False) -> Dict[str, Any]:
    """Every account for the period: beginning balance, debits, credits, ending balance and how
    many lines - the collapsed view of the General Ledger (expand an account for its lines)."""
    acc = accounts(conn, entity_id)
    h = history_until(conn, entity_id)
    end = balances(conn, entity_id, t)
    start = balances_at_start(conn, entity_id, f)
    sums: Dict[str, List[Any]] = {}
    if h and f <= h:
        for r in q(conn, """SELECT account_code, SUM(debit) d, SUM(credit) c, COUNT(*) n FROM fin_sage_gl_lines
                            WHERE legal_entity_id=%s AND txn_date BETWEEN %s AND %s GROUP BY account_code""",
                   (entity_id, f, min(t, h))):
            sums[r["account_code"]] = [money(r["d"]), money(r["c"]), r["n"]]
    a_from = max(f, h + ONE) if h else f
    if a_from <= t:
        for r in q(conn, """SELECT account_code, SUM(debit) d, SUM(credit) c, COUNT(*) n FROM fin_v_general_ledger
                            WHERE legal_entity_id=%s AND journal_date BETWEEN %s AND %s GROUP BY account_code""",
                   (entity_id, a_from, t)):
            s = sums.setdefault(r["account_code"], [ZERO, ZERO, 0])
            s[0] += money(r["d"])
            s[1] += money(r["c"])
            s[2] += r["n"]
    rows = []
    for code in sorted(set(acc) | set(sums) | set(end) | set(start)):
        a = acc.get(code, {"code": code, "name": code, "account_type": None, "id": None})
        opening = start.get(code, ZERO)
        d, c, n = sums.get(code, [ZERO, ZERO, 0])
        closing = end.get(code, ZERO)
        # Non-zero only when Sage's balances move without line detail (a year-end closing inside
        # the range, or a change Sage made to earlier months after the export).
        other = closing - (opening + d - c)
        if not include_zero and opening == 0 and d == 0 and c == 0 and closing == 0:
            continue
        if codes and code not in codes:
            continue
        rows.append({"account_id": a.get("id"), "code": code, "name": a.get("name"), "account_type": a.get("account_type"),
                     "subtype": a.get("subtype"), "opening": opening, "debit": d, "credit": c, "closing": closing,
                     "other_changes": other, "lines": n})
    return {"date_from": f, "date_to": t, "history_until": h, "rows": rows,
            "totals": {"debit": sum((r["debit"] for r in rows), ZERO), "credit": sum((r["credit"] for r in rows), ZERO)}}


def trial_balance_as_of(conn, entity_id: str, d: dt.date, include_zero: bool = False) -> Dict[str, Any]:
    """Sage 'General Ledger Trial Balance': Account ID, Account Description, Debit Amt, Credit Amt
    as of a date. Income and expense show the year to date."""
    acc = accounts(conn, entity_id)
    bal = balances(conn, entity_id, d)
    pl = ytd_pl(conn, entity_id, d)
    rows, dr, cr = [], ZERO, ZERO
    for code in sorted(set(bal) | set(pl) | (set(acc) if include_zero else set())):
        a = acc.get(code, {"code": code, "name": code, "account_type": None, "id": None, "subtype": None})
        v = pl.get(code, ZERO) if a.get("account_type") in PL_TYPES else bal.get(code, ZERO)
        if v == 0 and not include_zero:
            continue
        rows.append({"account_id": a.get("id"), "code": code, "name": a.get("name"), "account_type": a.get("account_type"),
                     "subtype": a.get("subtype"), "debit": v if v > 0 else ZERO, "credit": -v if v < 0 else ZERO})
        dr += max(v, ZERO)
        cr += max(-v, ZERO)
    return {"as_of": d, "rows": rows, "total_debit": dr, "total_credit": cr, "balanced": dr == cr,
            "history_until": history_until(conn, entity_id)}


# ---------------------------------------------------------------------------
# A single Sage transaction (all lines with the same date, journal and reference)
# ---------------------------------------------------------------------------

def sage_transaction(conn, entity_id: str, date: dt.date, jrnl: Optional[str], reference: Optional[str],
                     line_id: Optional[int] = None) -> Dict[str, Any]:
    rows = q(conn, """SELECT l.id, l.account_code, a.name AS account_name, a.id::text AS account_id, l.txn_date, l.reference,
                             l.jrnl, l.description, l.debit, l.credit
                      FROM fin_sage_gl_lines l LEFT JOIN fin_accounts a ON a.legal_entity_id=l.legal_entity_id AND a.code=l.account_code
                      WHERE l.legal_entity_id=%s AND l.txn_date=%s AND COALESCE(l.jrnl,'')=COALESCE(%s,'')
                        AND COALESCE(l.reference,'')=COALESCE(%s,'')
                      ORDER BY l.debit DESC, l.account_code, l.seq LIMIT 2000""", (entity_id, date, jrnl, reference))
    out = {"date": date, "jrnl": jrnl, "reference": reference, "lines": rows,
           "total_debit": sum((money(r["debit"]) for r in rows), ZERO), "total_credit": sum((money(r["credit"]) for r in rows), ZERO)}
    # The journal as Sage exported it (qty, U/M, order of entry) when that journal was loaded.
    kind = {"COGS": "COGS"}.get(jrnl or "", jrnl)
    if kind in ("SJ", "CRJ", "CDJ", "PJ", "COGS", "GENJ") and reference:
        out["journal_lines"] = q(conn, """SELECT account_code, account_description, reference, description, qty, um, debit, credit
                                          FROM fin_sage_journal_lines WHERE legal_entity_id=%s AND kind=%s AND txn_date=%s
                                          AND reference=%s ORDER BY seq LIMIT 2000""", (entity_id, kind, date, reference))
    if jrnl in ("SJ", "COGS") and reference:
        out["invoice_number"] = reference
    if jrnl == "ADJ" and reference:
        # a correction posted from Data exceptions: the decision behind it
        out["correction"] = q1(conn, """SELECT a.action, a.note, a.created_by, a.created_at, a.payload, x.id::text AS exception_id,
                                               x.title, x.kind, j.id::text AS journal_id, j.journal_number
                                        FROM fin_data_exception_actions a JOIN fin_data_exceptions x ON x.id=a.exception_id
                                        LEFT JOIN fin_journals j ON j.id=a.journal_id
                                        WHERE a.legal_entity_id=%s AND a.reference=%s LIMIT 1""", (entity_id, reference))
    return out
