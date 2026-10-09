"""ACE Books as the finance read model for the rest of ACE.

Before ACE Books, the finance pages (AR & Alerts, Analytics, Reports), the KPI
watchdog, the intelligence services and Ask ACE's tools read Sage snapshot
tables. Once the books are live those snapshots freeze at the cut-over and go
stale, so the shared finance read functions delegate here instead. The return
shapes match the legacy functions exactly, so no consumer needs to change; the
numbers now agree with ACE Books screen for screen.

"Live" means the opening balances have been loaded and a cut-over date is set.
Before that, callers keep using the Sage snapshots.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from src.fin import reports
from src.fin.context import resolve_entity
from src.fin.db import ZERO, money, q, q1, tx


def live() -> bool:
    try:
        with tx() as conn:
            e = resolve_entity(conn, None)
            r = q1(conn, """SELECT s.cutover_date,
                                   EXISTS (SELECT 1 FROM fin_journals j WHERE j.legal_entity_id=s.legal_entity_id
                                           AND j.journal_type='OPENING' AND j.status='POSTED') AS opened
                            FROM fin_settings s WHERE s.legal_entity_id=%s""", (e,))
            return bool(r and r["cutover_date"] and r["opened"])
    except Exception:
        return False


def _customers(conn) -> Dict[int, Dict[str, Any]]:
    return {r["id"]: r for r in q(conn, """SELECT id, name, customer_code, credit_limit, payment_terms_days,
                                                  contact_details->>'email' AS email, contact_details->>'phone' AS phone
                                           FROM customers""")}


def _key(c: Optional[Dict[str, Any]], cid: Any) -> str:
    """The customer key legacy screens and alert rules use: the Sage customer code."""
    return (c or {}).get("customer_code") or str(cid)


def _bucket(days: int) -> str:
    return "0_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "91_plus"


def ar_rows(on: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    """Open receivable items (invoices, unapplied receipts and credits), one row each."""
    on = on or dt.date.today()
    with tx() as conn:
        e = resolve_entity(conn, None)
        cust = _customers(conn)
        out = []
        for it in reports.ar_open_items(conn, e, on):
            c = cust.get(it["customer_id"])
            days = (on - it["due_date"]).days
            out.append({"customer_id": _key(c, it["customer_id"]), "ace_customer_id": it["customer_id"],
                        "name": (c or {}).get("name"), "email": (c or {}).get("email"), "phone": (c or {}).get("phone"),
                        "doc_type": it["doc_type"], "doc_id": str(it["doc_id"]), "doc_number": it["doc_number"],
                        "date": it["doc_date"], "due_date": it["due_date"], "balance": float(money(it["open_amount"])),
                        "days_overdue": max(days, 0), "bucket": _bucket(max(days, 0))})
        return out


def ar_aging_buckets() -> Dict[str, float]:
    """Same buckets as the ACE Books aged-receivables report (by due date, credits netted)."""
    b = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_plus": 0.0}
    for r in ar_rows():
        b[r["bucket"]] += r["balance"]
    return {k: round(v, 2) for k, v in b.items()}


def ar_aging_customers(bucket: str) -> List[Dict[str, Any]]:
    raw = (bucket or "").strip().lower().replace("_", "-")
    key = ("0_30" if raw.startswith("0-30") else "31_60" if raw.startswith("31-60") else
           "61_90" if raw.startswith("61-90") else "91_plus" if raw.startswith(("90+", "91+")) else None)
    if not key:
        return []
    per: Dict[str, Dict[str, Any]] = {}
    for r in ar_rows():
        if r["bucket"] != key:
            continue
        e = per.setdefault(r["customer_id"], {"customer_id": r["customer_id"], "ace_customer_id": r["ace_customer_id"],
                                              "name": r["name"], "email": r["email"], "phone": r["phone"],
                                              "total_balance": 0.0, "total_amount": 0.0, "invoices_count": 0,
                                              "max_days_overdue": 0, "earliest_due_date": None, "bucket": key})
        e["total_balance"] += r["balance"]
        if r["doc_type"] == "INVOICE":
            e["total_amount"] += r["balance"]
            e["invoices_count"] += 1
        e["max_days_overdue"] = max(e["max_days_overdue"], r["days_overdue"])
        if not e["earliest_due_date"] or r["due_date"] < e["earliest_due_date"]:
            e["earliest_due_date"] = r["due_date"]
    rows = [r for r in per.values() if abs(r["total_balance"]) >= 0.005]
    for r in rows:
        r["total_balance"] = round(r["total_balance"], 2)
        r["total_amount"] = round(r["total_amount"], 2)
    return sorted(rows, key=lambda r: ((r["name"] or "").strip().lower(), str(r["customer_id"])))


def kpis() -> Dict[str, Any]:
    """AR/AP totals and overdue counts, cash, and year-to-date revenue and cost of sales."""
    today = dt.date.today()
    with tx() as conn:
        e = resolve_entity(conn, None)
        ar = reports.ar_open_items(conn, e, today)
        ap = reports.ap_open_items(conn, e, today)
        cash = q1(conn, """SELECT COALESCE(SUM(debit-credit),0) v FROM fin_v_general_ledger
                           WHERE legal_entity_id=%s AND subtype='CASH' AND journal_date <= %s""", (e, today))["v"]
        pl = reports.income_statement(conn, e, reports._fy_start(conn, e, today), today)

    def tot(items, doc):
        return float(sum((money(i["open_amount"]) for i in items if i["doc_type"] == doc), ZERO))
    return {
        "ar": {"total_amount": tot(ar, "INVOICE"), "total_balance": float(sum((money(i["open_amount"]) for i in ar), ZERO)),
               "overdue_count": sum(1 for i in ar if i["doc_type"] == "INVOICE" and i["due_date"] < today)},
        "ap": {"total_amount": tot(ap, "BILL"), "total_balance": float(sum((money(i["open_amount"]) for i in ap), ZERO)),
               "overdue_count": sum(1 for i in ap if i["doc_type"] == "BILL" and i["due_date"] < today)},
        "cash": float(money(cash)),
        "total_revenue": float(money(pl["revenue"])),
        "total_cost": float(money(pl["cost_of_sales"])),
        "source": "ACE Books",
    }


def monthly_pl(period: Optional[str] = None) -> List[Dict[str, Any]]:
    """Revenue (sales) and expenses (net of other income) by month from ACE Books postings, so revenue matches the
    Control Tower and revenue - expenses = net profit. Opening/closing journals excluded."""
    with tx() as conn:
        e = resolve_entity(conn, None)
        rows = q(conn, """SELECT to_char(journal_date,'YYYY-MM') AS period,
                                 SUM(CASE WHEN subtype='SALES' THEN credit-debit ELSE 0 END) AS revenue,
                                 SUM(CASE WHEN account_type='EXPENSE' THEN debit-credit
                                          WHEN subtype='OTHER_INCOME' THEN debit-credit ELSE 0 END) AS expenses
                          FROM fin_v_general_ledger
                          WHERE legal_entity_id=%s AND journal_type NOT IN ('OPENING','CLOSING')
                            AND account_type IN ('REVENUE','EXPENSE') AND (%s::text IS NULL OR to_char(journal_date,'YYYY-MM') LIKE %s)
                          GROUP BY 1 ORDER BY 1""", (e, period, f"{period}%" if period else None))
        return [{"period": r["period"], "revenue": float(money(r["revenue"])), "expenses": float(money(r["expenses"]))} for r in rows]


def cutover() -> Optional[dt.date]:
    with tx() as conn:
        e = resolve_entity(conn, None)
        r = q1(conn, "SELECT cutover_date FROM fin_settings WHERE legal_entity_id=%s", (e,))
        return r["cutover_date"] if r else None


def cash_position() -> float:
    with tx() as conn:
        e = resolve_entity(conn, None)
        return float(money(q1(conn, """SELECT COALESCE(SUM(debit-credit),0) v FROM fin_v_general_ledger
                                        WHERE legal_entity_id=%s AND subtype='CASH'""", (e,))["v"]))


def ap_rows(on: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    on = on or dt.date.today()
    with tx() as conn:
        e = resolve_entity(conn, None)
        names = {str(r["id"]): r["name"] for r in q(conn, "SELECT id, name FROM suppliers")}
        return [{"supplier_id": str(i["supplier_id"]), "name": names.get(str(i["supplier_id"])), "doc_type": i["doc_type"],
                 "doc_number": i["doc_number"], "due_date": i["due_date"], "balance": float(money(i["open_amount"]))}
                for i in reports.ap_open_items(conn, e, on)]


def pl_series(period: Optional[str] = None) -> List[Dict[str, Any]]:
    """P&L rows for the legacy P&L tab, entirely from ACE Books.

    The part of the fiscal year before the cut-over exists only as the migrated
    opening balance (Sage's own figures), so it is one row; months from the
    cut-over are ACE Books postings. The old Sage-GL monthly view is not used:
    it double-counted revenue against Sage's own income statement."""
    today = dt.date.today()
    with tx() as conn:
        e = resolve_entity(conn, None)
        cut = q1(conn, "SELECT cutover_date FROM fin_settings WHERE legal_entity_id=%s", (e,))["cutover_date"]
        fy = reports._fy_start(conn, e, cut)
        rows: List[Dict[str, Any]] = []
        if cut > fy and (not period or f"{fy:%Y-%m}" <= period[:7] <= f"{cut - dt.timedelta(days=1):%Y-%m}" or period == str(fy.year)):
            pre = reports.income_statement(conn, e, fy, cut - dt.timedelta(days=1))
            rev = float(money(pre["revenue"]))   # sales revenue, as on the Control Tower and income statement
            rows.append({"period": f"{fy:%Y-%m} to {cut - dt.timedelta(days=1):%Y-%m} (Sage, migrated)",
                         "revenue": rev, "expenses": rev - float(money(pre["net_profit"]))})
    rows += [r for r in monthly_pl(period) if r["period"] >= f"{cut:%Y-%m}"]
    return rows
