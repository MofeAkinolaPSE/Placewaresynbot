"""Reporting engine - every figure derived from posted journals / subledger
documents, nothing stored (Workflow Map §38). Each row carries the ids the UI
needs to drill down: statement -> account -> GL lines -> journal -> source.

Sign convention for presentation: amounts are shown "natural" -
revenue/liabilities/equity as positive credits, assets/expenses as positive debits.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin.db import ZERO, money, q, q1, qty

CURRENT_ASSETS = ("CASH", "RECEIVABLE", "INVENTORY", "OTHER_CURRENT_ASSET")
NONCURRENT_ASSETS = ("FIXED_ASSET", "ACCUMULATED_DEPRECIATION", "OTHER_ASSET")
CURRENT_LIABS = ("PAYABLE", "OTHER_CURRENT_LIABILITY")
EQUITY_SUBTYPES = ("EQUITY", "EQUITY_CLOSING", "RETAINED_EARNINGS")


def _balances(conn, entity_id: str, *, date_from: Optional[dt.date] = None, date_to: dt.date,
              exclude_types: tuple = (), extra: str = "", params: Optional[list] = None) -> List[Dict[str, Any]]:
    where = ["g.legal_entity_id=%s", "g.journal_date <= %s"]
    p: List[Any] = [entity_id, date_to]
    if date_from:
        where.append("g.journal_date >= %s")
        p.append(date_from)
    if exclude_types:
        where.append("g.journal_type <> ALL(%s)")
        p.append(list(exclude_types))
    return q(conn, f"""SELECT g.account_id, g.account_code AS code, g.account_name AS name, g.account_type, g.subtype,
                              COALESCE(SUM(g.debit),0) AS debit, COALESCE(SUM(g.credit),0) AS credit
                       FROM fin_v_general_ledger g WHERE {' AND '.join(where)} {extra}
                       GROUP BY g.account_id, g.account_code, g.account_name, g.account_type, g.subtype
                       ORDER BY g.account_code""", p + (params or []))


def _natural(row: Dict[str, Any]) -> Decimal:
    d, c = money(row["debit"]), money(row["credit"])
    return d - c if row["account_type"] in ("ASSET", "EXPENSE") else c - d


def _section(rows, subtypes, title) -> Dict[str, Any]:
    lines = [{"account_id": r["account_id"], "code": r["code"], "name": r["name"], "subtype": r["subtype"],
              "amount": _natural(r)} for r in rows if r["subtype"] in subtypes and _natural(r) != 0]
    return {"title": title, "lines": lines, "total": sum((l["amount"] for l in lines), ZERO)}


def _fy_start(conn, entity_id: str, on: dt.date) -> dt.date:
    fy = q1(conn, "SELECT start_date FROM fin_fiscal_years WHERE legal_entity_id=%s AND %s BETWEEN start_date AND end_date",
            (entity_id, on))
    return fy["start_date"] if fy else dt.date(on.year, 1, 1)


# ---------------------------------------------------------------------------
# Income statement
# ---------------------------------------------------------------------------

def _ledger_rows(conn, entity_id: str, f: dt.date, t: dt.date, pl_only: bool = False) -> List[Dict[str, Any]]:
    """Movement per account over f..t from the one ledger (Sage history up to the hand-over,
    ACE Books after it), in the shape _section/_natural expect."""
    from src.fin import books_ledger
    acc = books_ledger.accounts(conn, entity_id)
    mv = books_ledger.movement(conn, entity_id, f, t)
    rows = []
    for code, v in mv.items():
        a = acc.get(code)
        if not a or (pl_only and a["account_type"] not in ("REVENUE", "EXPENSE")):
            continue
        rows.append({"account_id": a["id"], "code": code, "name": a["name"], "account_type": a["account_type"],
                     "subtype": a["subtype"], "debit": v if v > 0 else ZERO, "credit": -v if v < 0 else ZERO})
    return sorted(rows, key=lambda r: r["code"])


def _ledger_balance_rows(conn, entity_id: str, d: dt.date) -> List[Dict[str, Any]]:
    from src.fin import books_ledger
    acc = books_ledger.accounts(conn, entity_id)
    bal = books_ledger.balances(conn, entity_id, d)
    ytd = books_ledger.ytd_pl(conn, entity_id, d)
    rows = []
    for code in set(bal) | set(ytd):
        a = acc.get(code)
        if not a:
            continue
        v = ytd.get(code, ZERO) if a["account_type"] in ("REVENUE", "EXPENSE") else bal.get(code, ZERO)
        rows.append({"account_id": a["id"], "code": code, "name": a["name"], "account_type": a["account_type"],
                     "subtype": a["subtype"], "debit": v if v > 0 else ZERO, "credit": -v if v < 0 else ZERO})
    return sorted(rows, key=lambda r: r["code"])


def income_statement(conn, entity_id: str, date_from: dt.date, date_to: dt.date,
                     compare_from: Optional[dt.date] = None, compare_to: Optional[dt.date] = None,
                     budget_id: Optional[str] = None) -> Dict[str, Any]:
    """Sage layout: Revenues (sales, then other income) - cost of sales = gross profit;
    expenses; net income. Any period back to the first Sage year."""
    def build(f, t):
        rows = _ledger_rows(conn, entity_id, f, t, pl_only=True)
        sales = _section(rows, ("SALES",), "Revenue")
        oinc = _section(rows, ("OTHER_INCOME",), "Other income")
        cogs = _section(rows, ("COST_OF_SALES",), "Cost of sales")
        opex = _section(rows, ("OPERATING_EXPENSE",), "Operating expenses")
        oexp = _section(rows, ("OTHER_EXPENSE",), "Other expenses")
        total_revenue = sales["total"] + oinc["total"]
        gross = total_revenue - cogs["total"]
        operating = gross - opex["total"]
        net = operating - oexp["total"]
        return {"sections": [sales, oinc, cogs, opex, oexp], "revenue": sales["total"], "other_income": oinc["total"],
                "total_revenue": total_revenue, "cost_of_sales": cogs["total"], "gross_profit": gross,
                "gross_margin_pct": (gross / total_revenue * 100).quantize(Decimal("0.01")) if total_revenue else None,
                "operating_profit": operating, "net_profit": net}
    out = {"date_from": date_from, "date_to": date_to, **build(date_from, date_to)}
    ytd_from = _fy_start(conn, entity_id, date_to)
    if ytd_from != date_from:
        y = build(ytd_from, date_to)
        out["year_to_date"] = {"date_from": ytd_from, "net_profit": y["net_profit"], "revenue": y["revenue"],
                               "gross_profit": y["gross_profit"]}
    if compare_from and compare_to:
        out["comparison"] = {"date_from": compare_from, "date_to": compare_to, **build(compare_from, compare_to)}
    if budget_id:
        out["budget"] = budget_totals(conn, budget_id, date_from, date_to)
    return out


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------

def balance_sheet(conn, entity_id: str, as_of: dt.date) -> Dict[str, Any]:
    rows = _ledger_balance_rows(conn, entity_id, as_of)
    ca = _section(rows, CURRENT_ASSETS, "Current assets")
    nca = _section(rows, NONCURRENT_ASSETS, "Non-current assets")
    cl = _section(rows, CURRENT_LIABS, "Current liabilities")
    ltl = _section(rows, ("LONG_TERM_LIABILITY",), "Long-term liabilities")
    eq = _section(rows, EQUITY_SUBTYPES, "Equity")
    # Profit not yet closed to retained earnings is still part of equity.
    pl = sum((_natural(r) if r["account_type"] == "REVENUE" else -_natural(r)
              for r in rows if r["account_type"] in ("REVENUE", "EXPENSE")), ZERO)
    eq["lines"].append({"account_id": None, "code": "", "name": "Current year earnings (not yet closed)", "amount": pl})
    eq["total"] += pl
    assets = ca["total"] + nca["total"]
    liab = cl["total"] + ltl["total"]
    return {"as_of": as_of, "assets": [ca, nca], "total_assets": assets, "liabilities": [cl, ltl],
            "total_liabilities": liab, "equity": eq, "total_equity": eq["total"],
            "total_liabilities_and_equity": liab + eq["total"], "balanced": assets == liab + eq["total"],
            "difference": assets - liab - eq["total"]}


# ---------------------------------------------------------------------------
# Cash flow (indirect) and retained earnings
# ---------------------------------------------------------------------------

def cash_flow(conn, entity_id: str, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    """Indirect method. Movements exclude migration (OPENING) and year-end (CLOSING)
    journals, which move balances but not cash. Operating+Investing+Financing
    always equals the change in cash because every journal balances."""
    from src.fin import books_ledger
    mv = _ledger_rows(conn, entity_id, date_from, date_to)

    def credit_move(r):  # increase in a credit-natured balance / decrease in a debit one
        return money(r["credit"]) - money(r["debit"])
    net = sum((credit_move(r) for r in mv if r["account_type"] in ("REVENUE", "EXPENSE")), ZERO)
    # Profit closed into retained earnings at each year end inside the range is already in the
    # net profit above; take it out of the retained-earnings movement.
    closed = ZERO
    for y in range(date_from.year, date_to.year):
        closed += -sum(books_ledger.ytd_pl(conn, entity_id, dt.date(y, 12, 31)).values(), ZERO)

    def group(subtypes, label_prefix):
        lines = []
        for r in mv:
            if r["subtype"] not in subtypes:
                continue
            amt = credit_move(r) - (closed if r["subtype"] == "RETAINED_EARNINGS" else ZERO)
            if amt != 0:
                lines.append({"account_id": r["account_id"], "code": r["code"], "name": f"{label_prefix}{r['name']}", "amount": amt})
        return lines, sum((l["amount"] for l in lines), ZERO)
    dep_lines, dep = group(("ACCUMULATED_DEPRECIATION",), "Depreciation - ")
    wc_lines, wc = group(("RECEIVABLE", "INVENTORY", "OTHER_CURRENT_ASSET", "PAYABLE", "OTHER_CURRENT_LIABILITY"), "Change in ")
    inv_lines, inv = group(("FIXED_ASSET", "OTHER_ASSET"), "")
    fin_lines, fin = group(("LONG_TERM_LIABILITY", "EQUITY", "EQUITY_CLOSING", "RETAINED_EARNINGS"), "")
    operating = net + dep + wc
    change = operating + inv + fin
    acc = books_ledger.accounts(conn, entity_id)
    cash = [c for c, a in acc.items() if a["subtype"] == "CASH"]
    cash_open = sum(books_ledger.balances_at_start(conn, entity_id, date_from, cash).values(), ZERO)
    cash_close = sum(books_ledger.balances(conn, entity_id, date_to, cash).values(), ZERO)
    return {"date_from": date_from, "date_to": date_to,
            "operating": {"net_profit": net, "adjustments": dep_lines, "working_capital": wc_lines, "total": operating},
            "investing": {"lines": inv_lines, "total": inv}, "financing": {"lines": fin_lines, "total": fin},
            "net_change": change, "opening_cash": cash_open, "closing_cash": cash_close,
            "reconciles": cash_open + change == cash_close}


def retained_earnings(conn, entity_id: str, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    from src.fin import books_ledger
    acc = books_ledger.accounts(conn, entity_id)
    re_codes = [c for c, a in acc.items() if a["subtype"] == "RETAINED_EARNINGS"]
    opening = -sum(books_ledger.balances_at_start(conn, entity_id, date_from, re_codes).values(), ZERO)
    end = -sum(books_ledger.balances(conn, entity_id, date_to, re_codes).values(), ZERO)
    closing_entries = ZERO
    for y in range(date_from.year, date_to.year):
        closing_entries += -sum(books_ledger.ytd_pl(conn, entity_id, dt.date(y, 12, 31)).values(), ZERO)
    adjustments = end - opening - closing_entries
    net = income_statement(conn, entity_id, date_from, date_to)["net_profit"]
    # Before the year is closed, the period's profit sits in P&L accounts, not yet in RE.
    unclosed = net - closing_entries  # this year's result is still in the income and expense accounts
    return {"date_from": date_from, "date_to": date_to, "opening": opening, "adjustments": adjustments,
            "net_profit": net, "closed_to_retained_earnings": closing_entries,
            "closing": opening + adjustments + closing_entries + unclosed}


# ---------------------------------------------------------------------------
# AR / AP aging and statements (open-item subledgers)
# ---------------------------------------------------------------------------

def _buckets(conn, entity_id: str) -> List[int]:
    s = q1(conn, "SELECT aging_buckets FROM fin_settings WHERE legal_entity_id=%s", (entity_id,))
    return list(s["aging_buckets"]) if s else [30, 60, 90, 120]


def _bucket_labels(b: List[int]) -> List[str]:
    labels, lo = [], 0
    for x in b:
        labels.append(f"{lo}-{x}" if lo == 0 else f"{lo + 1}-{x}")
        lo = x
    labels.append(f"Over {b[-1]}")
    return labels


def _age(days: int, b: List[int]) -> int:
    for i, x in enumerate(b):
        if days <= x:
            return i
    return len(b)


def ar_open_items(conn, entity_id: str, as_of: dt.date, customer_id: Optional[int] = None) -> List[Dict[str, Any]]:
    cf = " AND x.customer_id=%s" if customer_id else ""
    p: List[Any] = [as_of, entity_id, as_of, as_of, as_of, entity_id, as_of, as_of, entity_id, as_of]
    if customer_id:
        p.append(int(customer_id))
    return q(conn, f"""
        SELECT x.* FROM (
          SELECT 'INVOICE' AS doc_type, i.id AS doc_id, i.invoice_number AS doc_number, i.customer_id, i.invoice_date AS doc_date,
                 i.due_date, i.total - COALESCE((SELECT SUM(a.amount) FROM fin_ar_allocations a WHERE a.invoice_id=i.id
                                                 AND NOT a.reversed AND a.allocation_date <= %s),0) AS open_amount
          FROM fin_sales_invoices i WHERE i.legal_entity_id=%s AND i.invoice_date <= %s AND i.status <> 'DRAFT'
            AND NOT (i.status='VOID' AND COALESCE(i.voided_at::date, i.invoice_date) <= %s)
          UNION ALL
          SELECT 'RECEIPT', r.id, r.receipt_number, r.customer_id, r.receipt_date, r.receipt_date,
                 -(r.amount + r.wht_amount - COALESCE((SELECT SUM(a.amount) FROM fin_ar_allocations a WHERE a.source_type='RECEIPT'
                   AND a.source_id=r.id AND NOT a.reversed AND a.allocation_date <= %s),0))
          FROM fin_customer_receipts r WHERE r.legal_entity_id=%s AND r.receipt_date <= %s AND r.status='POSTED'
          UNION ALL
          SELECT 'CREDIT_NOTE', n.id, n.credit_note_number, n.customer_id, n.note_date, n.note_date,
                 -(n.total - COALESCE((SELECT SUM(a.amount) FROM fin_ar_allocations a WHERE a.source_type='CREDIT_NOTE'
                   AND a.source_id=n.id AND NOT a.reversed AND a.allocation_date <= %s),0))
          FROM fin_credit_notes n WHERE n.legal_entity_id=%s AND n.note_date <= %s AND n.status='POSTED'
        ) x WHERE x.open_amount <> 0 {cf}""", p)


def aged_receivables(conn, entity_id: str, as_of: dt.date, basis: str = "due_date") -> Dict[str, Any]:
    b = _buckets(conn, entity_id)
    labels = _bucket_labels(b)
    names = {r["id"]: r for r in q(conn, "SELECT id, name, customer_code, credit_limit FROM customers")}
    per: Dict[int, Dict[str, Any]] = {}
    for it in ar_open_items(conn, entity_id, as_of):
        ref = it["doc_date"] if basis == "invoice_date" else it["due_date"]
        idx = _age(max((as_of - ref).days, 0), b)
        c = per.setdefault(it["customer_id"], {"customer_id": it["customer_id"],
                                               "customer_name": names.get(it["customer_id"], {}).get("name"),
                                               "customer_code": names.get(it["customer_id"], {}).get("customer_code"),
                                               "credit_limit": names.get(it["customer_id"], {}).get("credit_limit"),
                                               "buckets": [ZERO] * len(labels), "total": ZERO, "items": []})
        amt = money(it["open_amount"])
        c["buckets"][idx] += amt
        c["total"] += amt
        c["items"].append({**it, "bucket": labels[idx], "days": (as_of - ref).days})
    rows = sorted(per.values(), key=lambda r: -r["total"])
    totals = [sum((r["buckets"][i] for r in rows), ZERO) for i in range(len(labels))]
    return {"as_of": as_of, "basis": basis, "buckets": labels, "rows": rows, "bucket_totals": totals,
            "total": sum(totals, ZERO)}


def ap_open_items(conn, entity_id: str, as_of: dt.date, supplier_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sf = " AND x.supplier_id=%s" if supplier_id else ""
    p: List[Any] = [as_of, entity_id, as_of, as_of, entity_id, as_of, as_of, entity_id, as_of]
    if supplier_id:
        p.append(str(supplier_id))
    return q(conn, f"""
        SELECT x.* FROM (
          SELECT 'BILL' AS doc_type, b.id AS doc_id, b.bill_number AS doc_number, b.supplier_invoice_number AS supplier_ref,
                 b.supplier_id, b.bill_date AS doc_date, b.due_date,
                 b.total - COALESCE((SELECT SUM(a.amount) FROM fin_ap_allocations a WHERE a.bill_id=b.id AND NOT a.reversed
                                     AND a.allocation_date <= %s),0) AS open_amount
          FROM fin_supplier_bills b WHERE b.legal_entity_id=%s AND b.bill_date <= %s AND b.status <> 'VOID'
          UNION ALL
          SELECT 'PAYMENT', p.id, p.payment_number, p.reference, p.supplier_id, p.payment_date, p.payment_date,
                 -(p.amount + p.wht_amount - COALESCE((SELECT SUM(a.amount) FROM fin_ap_allocations a WHERE a.source_type='PAYMENT'
                   AND a.source_id=p.id AND NOT a.reversed AND a.allocation_date <= %s),0))
          FROM fin_supplier_payments p WHERE p.legal_entity_id=%s AND p.payment_date <= %s AND p.status='POSTED'
          UNION ALL
          SELECT 'DEBIT_NOTE', d.id, d.debit_note_number, NULL, d.supplier_id, d.note_date, d.note_date,
                 -(d.total - COALESCE((SELECT SUM(a.amount) FROM fin_ap_allocations a WHERE a.source_type='DEBIT_NOTE'
                   AND a.source_id=d.id AND NOT a.reversed AND a.allocation_date <= %s),0))
          FROM fin_debit_notes d WHERE d.legal_entity_id=%s AND d.note_date <= %s AND d.status='POSTED'
        ) x WHERE x.open_amount <> 0 {sf}""", p)


def aged_payables(conn, entity_id: str, as_of: dt.date, basis: str = "due_date") -> Dict[str, Any]:
    b = _buckets(conn, entity_id)
    labels = _bucket_labels(b)
    names = {str(r["id"]): r for r in q(conn, "SELECT id, name, external_vendor_id FROM suppliers")}
    per: Dict[str, Dict[str, Any]] = {}
    for it in ap_open_items(conn, entity_id, as_of):
        ref = it["doc_date"] if basis == "invoice_date" else it["due_date"]
        idx = _age(max((as_of - ref).days, 0), b)
        sid = str(it["supplier_id"])
        s = per.setdefault(sid, {"supplier_id": sid, "supplier_name": names.get(sid, {}).get("name"),
                                 "buckets": [ZERO] * len(labels), "total": ZERO, "items": []})
        amt = money(it["open_amount"])
        s["buckets"][idx] += amt
        s["total"] += amt
        s["items"].append({**it, "bucket": labels[idx], "days": (as_of - ref).days})
    rows = sorted(per.values(), key=lambda r: -r["total"])
    totals = [sum((r["buckets"][i] for r in rows), ZERO) for i in range(len(labels))]
    return {"as_of": as_of, "basis": basis, "buckets": labels, "rows": rows, "bucket_totals": totals,
            "total": sum(totals, ZERO)}


def customer_statement(conn, entity_id: str, customer_id: int, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    c = q1(conn, "SELECT id, name, customer_code, contact_details, credit_limit FROM customers WHERE id=%s", (customer_id,))
    docs = q(conn, """
        SELECT * FROM (
          SELECT i.invoice_date AS date, 'Invoice' AS type, i.invoice_number AS number, i.id AS doc_id, i.total AS debit,
                 0::numeric AS credit, i.is_opening, i.status FROM fin_sales_invoices i
          WHERE i.legal_entity_id=%s AND i.customer_id=%s AND i.status <> 'DRAFT'
          UNION ALL
          SELECT i.voided_at::date, 'Invoice void', i.invoice_number, i.id, 0, i.total, FALSE, i.status FROM fin_sales_invoices i
          WHERE i.legal_entity_id=%s AND i.customer_id=%s AND i.status='VOID' AND i.journal_id IS NOT NULL
          UNION ALL
          SELECT r.receipt_date, 'Receipt' || COALESCE(' ' || r.reference, ''), r.receipt_number, r.id, 0, r.amount + r.wht_amount,
                 FALSE, r.status FROM fin_customer_receipts r WHERE r.legal_entity_id=%s AND r.customer_id=%s
          UNION ALL
          SELECT r.receipt_date, 'Receipt reversed', r.receipt_number, r.id, r.amount + r.wht_amount, 0, FALSE, r.status
          FROM fin_customer_receipts r WHERE r.legal_entity_id=%s AND r.customer_id=%s AND r.status='VOID'
          UNION ALL
          SELECT n.note_date, 'Credit note', n.credit_note_number, n.id, 0, n.total, n.journal_id IS NULL, n.status
          FROM fin_credit_notes n WHERE n.legal_entity_id=%s AND n.customer_id=%s
        ) d ORDER BY d.date, d.number""", (entity_id, customer_id) * 5)
    opening = sum((money(d["debit"]) - money(d["credit"]) for d in docs if d["date"] < date_from), ZERO)
    bal, rows = opening, []
    for d in docs:
        if date_from <= d["date"] <= date_to:
            bal += money(d["debit"]) - money(d["credit"])
            rows.append({**d, "balance": bal})
    return {"customer": c, "date_from": date_from, "date_to": date_to, "opening_balance": opening,
            "rows": rows, "closing_balance": bal,
            "aging": aged_customer(conn, entity_id, customer_id, date_to)}


def aged_customer(conn, entity_id: str, customer_id: int, as_of: dt.date) -> Dict[str, Any]:
    b = _buckets(conn, entity_id)
    labels = _bucket_labels(b)
    buckets = [ZERO] * len(labels)
    for it in ar_open_items(conn, entity_id, as_of, customer_id):
        buckets[_age(max((as_of - it["doc_date"]).days, 0), b)] += money(it["open_amount"])
    return {"buckets": labels, "amounts": buckets, "total": sum(buckets, ZERO)}


def supplier_statement(conn, entity_id: str, supplier_id: str, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    s = q1(conn, "SELECT id, name, external_vendor_id FROM suppliers WHERE id=%s", (supplier_id,))
    docs = q(conn, """
        SELECT * FROM (
          SELECT b.bill_date AS date, 'Bill ' || b.supplier_invoice_number AS type, b.bill_number AS number, b.id AS doc_id,
                 0::numeric AS debit, b.total AS credit, b.status FROM fin_supplier_bills b
          WHERE b.legal_entity_id=%s AND b.supplier_id=%s
          UNION ALL
          SELECT b.bill_date, 'Bill voided', b.bill_number, b.id, b.total, 0, b.status FROM fin_supplier_bills b
          WHERE b.legal_entity_id=%s AND b.supplier_id=%s AND b.status='VOID' AND b.journal_id IS NOT NULL
          UNION ALL
          SELECT p.payment_date, 'Payment' || COALESCE(' ' || p.reference, ''), p.payment_number, p.id,
                 p.amount + p.wht_amount, 0, p.status FROM fin_supplier_payments p WHERE p.legal_entity_id=%s AND p.supplier_id=%s
          UNION ALL
          SELECT p.payment_date, 'Payment reversed', p.payment_number, p.id, 0, p.amount + p.wht_amount, p.status
          FROM fin_supplier_payments p WHERE p.legal_entity_id=%s AND p.supplier_id=%s AND p.status='VOID'
          UNION ALL
          SELECT d.note_date, 'Debit note', d.debit_note_number, d.id, d.total, 0, d.status FROM fin_debit_notes d
          WHERE d.legal_entity_id=%s AND d.supplier_id=%s
        ) d ORDER BY d.date, d.number""", (entity_id, supplier_id) * 5)
    opening = sum((money(d["credit"]) - money(d["debit"]) for d in docs if d["date"] < date_from), ZERO)
    bal, rows = opening, []
    for d in docs:
        if date_from <= d["date"] <= date_to:
            bal += money(d["credit"]) - money(d["debit"])
            rows.append({**d, "balance": bal})
    return {"supplier": s, "date_from": date_from, "date_to": date_to, "opening_balance": opening, "rows": rows,
            "closing_balance": bal}


def subledger_balances(conn, entity_id: str, as_of: dt.date) -> Dict[str, Decimal]:
    ar = sum((money(i["open_amount"]) for i in ar_open_items(conn, entity_id, as_of)), ZERO)
    ap = sum((money(i["open_amount"]) for i in ap_open_items(conn, entity_id, as_of)), ZERO)
    return {"ar": ar, "ap": ap}


# ---------------------------------------------------------------------------
# Sage-style journals (Sales, Cash Receipts, Purchases, Cash Disbursements,
# COGS, Inventory Adjustment, General) - all views over the GL by source.
# ---------------------------------------------------------------------------

JOURNAL_SOURCES = {
    "sales": ("SALES_INVOICE", "CREDIT_NOTE"),
    "cash-receipts": ("CUSTOMER_RECEIPT",),
    "purchases": ("SUPPLIER_BILL", "DEBIT_NOTE"),
    "cash-disbursements": ("SUPPLIER_PAYMENT", "CASH_VOUCHER"),
    "inventory-adjustments": ("STOCK_ADJUSTMENT", "STOCK_LOAN", "STOCK_LOAN_RETURN", "STOCK_LOAN_WRITEOFF"),
    "general": ("MANUAL_JOURNAL",),
    "assets": ("FIXED_ASSET", "DEPRECIATION_RUN", "FIXED_ASSET_DISPOSAL"),
}


def journal_report(conn, entity_id: str, kind: str, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    if kind == "cogs":
        rows = q(conn, """SELECT g.journal_date AS date, g.account_code, g.account_name, g.source_ref AS reference,
                                 g.product_sku, g.description, g.debit, g.credit, g.journal_id, g.journal_number, g.source_type, g.source_id
                          FROM fin_v_general_ledger g WHERE g.legal_entity_id=%s AND g.journal_date BETWEEN %s AND %s
                          AND g.product_sku IS NOT NULL AND g.subtype IN ('COST_OF_SALES','INVENTORY')
                          AND g.source_type IN ('SALES_INVOICE','CREDIT_NOTE')
                          ORDER BY g.journal_date, g.journal_number, g.line_no""", (entity_id, date_from, date_to))
    else:
        sources = JOURNAL_SOURCES.get(kind)
        if not sources:
            from src.fin.errors import invalid
            raise invalid(f"Unknown journal {kind}", allowed=sorted(list(JOURNAL_SOURCES) + ["cogs"]))
        rows = q(conn, """SELECT g.journal_date AS date, g.account_code, g.account_name, g.source_ref AS reference,
                                 g.product_sku, COALESCE(g.description, g.journal_description) AS description,
                                 g.debit, g.credit, g.journal_id, g.journal_number, g.source_type, g.source_id
                          FROM fin_v_general_ledger g WHERE g.legal_entity_id=%s AND g.journal_date BETWEEN %s AND %s
                          AND g.source_type = ANY(%s) ORDER BY g.journal_date, g.journal_number, g.line_no""",
                 (entity_id, date_from, date_to, list(sources)))
    return {"kind": kind, "date_from": date_from, "date_to": date_to, "rows": rows,
            "total_debit": sum((money(r["debit"]) for r in rows), ZERO),
            "total_credit": sum((money(r["credit"]) for r in rows), ZERO)}


# ---------------------------------------------------------------------------
# Inventory reports
# ---------------------------------------------------------------------------

def inventory_valuation(conn, entity_id: str, as_of: dt.date) -> Dict[str, Any]:
    rows = q(conn, """SELECT t.sku, p.name, p.inventory_account_id, a.code AS inventory_account,
                             SUM(t.quantity) AS quantity, SUM(t.total_cost) AS value
                      FROM fin_inventory_transactions t JOIN fin_products p ON p.legal_entity_id=t.legal_entity_id AND p.sku=t.sku
                      LEFT JOIN fin_accounts a ON a.id=p.inventory_account_id
                      WHERE t.legal_entity_id=%s AND t.txn_date <= %s
                        AND t.txn_type NOT IN ('LOAN_OUT','LOAN_RETURN')
                      GROUP BY t.sku, p.name, p.inventory_account_id, a.code
                      HAVING SUM(t.quantity) <> 0 OR SUM(t.total_cost) <> 0 ORDER BY t.sku""", (entity_id, as_of))
    # Loans are shown separately: still owned, but not in the warehouse.
    for r in rows:
        r["avg_cost"] = (Decimal(str(r["value"])) / Decimal(str(r["quantity"]))).quantize(Decimal("0.01")) if r["quantity"] else None
    loans = q(conn, """SELECT l.sku, SUM(l.quantity - l.quantity_returned) AS quantity,
                              SUM((l.quantity - l.quantity_returned) * l.unit_cost) AS value
                       FROM fin_stock_loans l WHERE l.legal_entity_id=%s AND l.status IN ('OPEN','PARTIALLY_RETURNED')
                       GROUP BY l.sku""", (entity_id,))
    total = sum((money(r["value"]) for r in rows), ZERO)
    return {"as_of": as_of, "rows": rows, "total_value": total, "on_loan": loans,
            "on_loan_value": sum((money(l["value"]) for l in loans), ZERO)}


def unit_activity(conn, entity_id: str, date_from: dt.date, date_to: dt.date, sku: Optional[str] = None) -> Dict[str, Any]:
    """Sage 'Inventory Unit Activity': opening + purchased - sold ± adjusted = closing, per item.
    (The report the accountant used in the meeting for Rotarix.)"""
    sf = " AND t.sku=%s" if sku else ""
    p: List[Any] = [date_from] * 1 + [date_from, date_to] * 6 + [date_to, entity_id]
    if sku:
        p.append(sku)
    rows = q(conn, f"""
        SELECT t.sku, p.name,
          SUM(CASE WHEN t.txn_date < %s THEN t.quantity ELSE 0 END) AS opening,
          SUM(CASE WHEN t.txn_date BETWEEN %s AND %s AND t.txn_type IN ('PURCHASE') THEN t.quantity ELSE 0 END) AS purchased,
          SUM(CASE WHEN t.txn_date BETWEEN %s AND %s AND t.txn_type IN ('SALE') THEN -t.quantity ELSE 0 END) AS sold,
          SUM(CASE WHEN t.txn_date BETWEEN %s AND %s AND t.txn_type IN ('RETURN_IN','RETURN_OUT') THEN t.quantity ELSE 0 END) AS returns,
          SUM(CASE WHEN t.txn_date BETWEEN %s AND %s AND t.txn_type IN ('LOAN_OUT','LOAN_RETURN') THEN t.quantity ELSE 0 END) AS loans,
          SUM(CASE WHEN t.txn_date BETWEEN %s AND %s AND t.txn_type IN ('ADJUSTMENT','DAMAGE','EXPIRY','STOCK_COUNT','RECALL',
                   'BATCH_REPLACEMENT','TRANSFER_IN','TRANSFER_OUT','OPENING_BALANCE') THEN t.quantity ELSE 0 END) AS adjusted,
          SUM(CASE WHEN t.txn_date BETWEEN %s AND %s AND t.txn_type='SALE' THEN -t.total_cost ELSE 0 END) AS cost_of_sales,
          SUM(CASE WHEN t.txn_date <= %s THEN t.quantity ELSE 0 END) AS closing
        FROM fin_inventory_transactions t JOIN fin_products p ON p.legal_entity_id=t.legal_entity_id AND p.sku=t.sku
        WHERE t.legal_entity_id=%s {sf}
        GROUP BY t.sku, p.name ORDER BY t.sku""", p)
    rows = [r for r in rows if any(Decimal(str(r[k] or 0)) != 0 for k in ("opening", "purchased", "sold", "returns",
                                                                          "loans", "adjusted", "closing"))]
    return {"date_from": date_from, "date_to": date_to, "rows": rows}


def stock_status(conn, entity_id: str) -> List[Dict[str, Any]]:
    return q(conn, """SELECT p.sku, p.name, p.reorder_level, p.status,
                             COALESCE(SUM(l.qty_remaining),0) AS on_hand,
                             COALESCE(SUM(l.qty_remaining * l.unit_cost),0) AS value,
                             MIN(b.expiry_date) FILTER (WHERE l.qty_remaining > 0) AS nearest_expiry,
                             COUNT(DISTINCT l.batch_id) FILTER (WHERE l.qty_remaining > 0) AS batches
                      FROM fin_products p
                      LEFT JOIN fin_cost_layers l ON l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku
                      LEFT JOIN fin_batches b ON b.id=l.batch_id
                      WHERE p.legal_entity_id=%s AND p.product_type='INVENTORY'
                      GROUP BY p.sku, p.name, p.reorder_level, p.status ORDER BY p.sku""", (entity_id,))


def batch_list(conn, entity_id: str, sku: Optional[str] = None, expiring_within_days: Optional[int] = None):
    p: List[Any] = [entity_id]
    extra = ""
    if sku:
        extra += " AND b.sku=%s"
        p.append(sku)
    if expiring_within_days is not None:
        extra += " AND b.expiry_date <= current_date + %s"
        p.append(int(expiring_within_days))
    return q(conn, f"""SELECT b.*, p.name AS product_name, COALESCE(SUM(l.qty_remaining),0) AS on_hand,
                              COALESCE(SUM(l.qty_remaining*l.unit_cost),0) AS value
                       FROM fin_batches b LEFT JOIN fin_products p ON p.legal_entity_id=b.legal_entity_id AND p.sku=b.sku
                       LEFT JOIN fin_cost_layers l ON l.batch_id=b.id
                       WHERE b.legal_entity_id=%s {extra}
                       GROUP BY b.id, p.name ORDER BY b.expiry_date NULLS LAST, b.sku""", p)


def item_movements(conn, entity_id: str, sku: str, date_from: dt.date, date_to: dt.date):
    return q(conn, """SELECT t.*, b.batch_number, c.name AS customer_name, s.name AS supplier_name, j.journal_number
                      FROM fin_inventory_transactions t LEFT JOIN fin_batches b ON b.id=t.batch_id
                      LEFT JOIN customers c ON c.id=t.customer_id LEFT JOIN suppliers s ON s.id=t.supplier_id
                      LEFT JOIN fin_journals j ON j.id=t.journal_id
                      WHERE t.legal_entity_id=%s AND t.sku=%s AND t.txn_date BETWEEN %s AND %s
                      ORDER BY t.txn_date, t.created_at""", (entity_id, sku, date_from, date_to))


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def budget_totals(conn, budget_id: str, date_from: dt.date, date_to: dt.date) -> List[Dict[str, Any]]:
    return q(conn, """SELECT bl.account_id, a.code, a.name, a.account_type, SUM(bl.amount) AS budget
                      FROM fin_budget_lines bl JOIN fin_periods p ON p.id=bl.period_id JOIN fin_accounts a ON a.id=bl.account_id
                      WHERE bl.budget_id=%s AND p.start_date >= %s AND p.end_date <= %s
                      GROUP BY bl.account_id, a.code, a.name, a.account_type ORDER BY a.code""", (budget_id, date_from, date_to))


def budget_vs_actual(conn, entity_id: str, budget_id: str, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    budget = {str(r["account_id"]): r for r in budget_totals(conn, budget_id, date_from, date_to)}
    actual = {str(r["account_id"]): r for r in _ledger_rows(conn, entity_id, date_from, date_to, pl_only=True)}
    rows = []
    for aid in sorted(set(budget) | set(actual), key=lambda k: (budget.get(k) or actual.get(k))["code"]):
        b = budget.get(aid)
        a = actual.get(aid)
        ref = a or b
        act = _natural(a) if a else ZERO
        bud = money(b["budget"]) if b else ZERO
        var = act - bud
        favourable = var >= 0 if ref["account_type"] == "REVENUE" else var <= 0
        rows.append({"account_id": aid, "code": ref["code"], "name": ref["name"], "account_type": ref["account_type"],
                     "budget": bud, "actual": act, "variance": var,
                     "variance_pct": (var / bud * 100).quantize(Decimal("0.1")) if bud else None,
                     "favourable": favourable})
    return {"date_from": date_from, "date_to": date_to, "rows": rows}
