"""Current business data for the non-finance features, from ACE Books.

CRM 360, reorder prediction, top sellers, margin drivers, ops KPIs, dashboards,
agents, reports and Ask ACE used to read Sage snapshot tables, which froze at
the ACE Books cut-over (and, for stock, double-counted every item). They read
these functions instead; each is a thin query over the migration-120 views:

    v_sales_lines           Sage sales history to the cut-over + ACE Books invoices after
    v_customer_invoices     one row per invoice, with its open balance
    v_ar_open               open receivable items today (= ACE Books ageing)
    v_customer_sales_summary lifetime sales / cost / margin per customer
    v_inventory             current stock (ACE Books for every item it holds)
    v_gl_monthly            monthly ledger movement per account

Numbers returned here therefore agree with the ACE Books screens.
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Dict, List, Optional

from src.fin.db import q, q1, tx


def _f(v: Any) -> float:
    return float(v or 0)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def customer_receivables(customer_pk: int) -> Dict[str, Any]:
    with tx() as conn:
        r = q1(conn, """SELECT COALESCE(SUM(balance),0) AS outstanding,
                               -- netted with unapplied receipts/credits, as on the Control Tower (never above what is owed)
                               COALESCE(SUM(balance) FILTER (WHERE due_date < current_date),0) AS overdue_amount,
                               COUNT(*) FILTER (WHERE doc_type='INVOICE' AND due_date < current_date) AS overdue_count,
                               COUNT(*) FILTER (WHERE doc_type='INVOICE') AS open_invoices
                        FROM v_ar_open WHERE customer_pk=%s""", (customer_pk,))
        last = q1(conn, "SELECT MAX(date) AS d, COUNT(*) AS n FROM v_customer_invoices WHERE customer_pk=%s", (customer_pk,))
    return {"outstanding": _f(r["outstanding"]), "overdue_amount": _f(r["overdue_amount"]), "overdue_count": r["overdue_count"],
            "open_invoices": r["open_invoices"], "invoice_count": last["n"], "last_invoice_date": last["d"]}


def customer_profitability(customer_pk: int) -> Optional[Dict[str, Any]]:
    with tx() as conn:
        r = q1(conn, "SELECT * FROM v_customer_sales_summary WHERE customer_pk=%s", (customer_pk,))
    if not r:
        return None
    return {"sales": _f(r["amount"]), "cost_of_sales": _f(r["cost_of_sales"]), "gross_profit": _f(r["gross_profit"]),
            "gross_margin_pct": _f(r["gross_margin"]), "invoices": r["invoices"], "first_sale": r["first_sale"], "last_sale": r["last_sale"]}


def customer_top_items(customer_pk: int, limit: int = 8) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """SELECT COALESCE(sku, description) AS item_id, SUM(quantity) AS quantity, SUM(amount) AS amount,
                                 SUM(gross_profit) AS gross_profit, MAX(invoice_date) AS last_date
                          FROM v_sales_lines WHERE customer_pk=%s AND (sku IS NOT NULL OR quantity IS NOT NULL)
                          GROUP BY 1 ORDER BY amount DESC NULLS LAST LIMIT %s""", (customer_pk, limit))
    return [{"item_id": r["item_id"], "quantity": round(_f(r["quantity"]), 2), "amount": round(_f(r["amount"]), 2),
             "gross_profit": round(_f(r["gross_profit"]), 2), "last_date": r["last_date"]} for r in rows]


def customer_order_history(customer_code: Optional[str] = None) -> List[Dict[str, Any]]:
    """Dated invoices (Sage history + ACE Books): customer_id (Sage code), date, amount."""
    with tx() as conn:
        if customer_code:
            return q(conn, """SELECT customer_id, customer_pk, date, amount FROM v_customer_invoices
                              WHERE customer_id=%s AND amount > 0""", (customer_code,))
        return q(conn, "SELECT customer_id, customer_pk, date, amount FROM v_customer_invoices WHERE amount > 0 AND customer_id IS NOT NULL")


def overdue_by_customer() -> Dict[str, float]:
    with tx() as conn:
        rows = q(conn, """SELECT customer_id, SUM(balance) AS v FROM v_ar_open
                          WHERE due_date < current_date AND customer_id IS NOT NULL GROUP BY 1 HAVING SUM(balance) > 0""")
    return {r["customer_id"]: _f(r["v"]) for r in rows}


def crm_totals() -> Dict[str, Any]:
    """Pipeline (open invoices), win rate (paid / all invoices), counts and recent invoices."""
    with tx() as conn:
        r = q1(conn, """SELECT COALESCE(SUM(balance) FILTER (WHERE status='open'),0) AS open_value,
                               COUNT(*) FILTER (WHERE status='open') AS open_count,
                               COUNT(*) FILTER (WHERE status='paid') AS paid_count, COUNT(*) AS total,
                               COALESCE(SUM(amount),0) AS invoiced
                        FROM v_customer_invoices WHERE amount > 0""")
        customers = q1(conn, "SELECT COUNT(*) n FROM customers")["n"]
        active = q1(conn, "SELECT COUNT(DISTINCT customer_pk) n FROM v_customer_invoices WHERE date >= current_date - 365")["n"]
        recent = q(conn, """SELECT invoice_id, customer_id, customer_name, amount, balance, status, date FROM v_customer_invoices
                            ORDER BY date DESC, invoice_id DESC LIMIT 5""")
    return {"open_value": _f(r["open_value"]), "open_count": r["open_count"],
            "win_rate": round(r["paid_count"] / r["total"] * 100, 1) if r["total"] else 0.0,
            "invoiced": _f(r["invoiced"]), "customer_count": customers, "active_customers": active, "recent": recent}


# ---------------------------------------------------------------------------
# Products & sales
# ---------------------------------------------------------------------------

def lifetime_units_by_sku() -> Dict[str, float]:
    with tx() as conn:
        rows = q(conn, "SELECT sku, SUM(quantity) AS qty FROM v_sales_lines WHERE sku IS NOT NULL GROUP BY sku")
    return {r["sku"]: _f(r["qty"]) for r in rows}


def top_selling_items(limit: int = 10, since: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """SELECT sku, SUM(quantity) AS total_qty, SUM(amount) AS total_revenue, SUM(gross_profit) AS total_gross_profit,
                                 MAX(invoice_date) AS last_sold
                          FROM v_sales_lines WHERE sku IS NOT NULL AND (%s::date IS NULL OR invoice_date >= %s)
                          GROUP BY sku ORDER BY total_qty DESC NULLS LAST LIMIT %s""", (since, since, limit))
    return [{"sku": r["sku"], "total_qty": round(_f(r["total_qty"]), 2), "total_revenue": round(_f(r["total_revenue"]), 2),
             "total_gross_profit": round(_f(r["total_gross_profit"]), 2), "last_sold": r["last_sold"]} for r in rows]


def top_customers_for_skus(skus: List[str], limit: int = 8) -> List[Dict[str, Any]]:
    if not skus:
        return []
    with tx() as conn:
        rows = q(conn, """SELECT customer_id AS customer_code, customer_pk, MAX(customer_name) AS customer_name,
                                 SUM(quantity) AS quantity, SUM(amount) AS amount, MAX(invoice_date) AS last_date
                          FROM v_sales_lines WHERE sku = ANY(%s) AND customer_pk IS NOT NULL
                          GROUP BY customer_id, customer_pk ORDER BY amount DESC NULLS LAST LIMIT %s""", (skus, limit))
    return [{**r, "quantity": round(_f(r["quantity"]), 2), "amount": round(_f(r["amount"]), 2)} for r in rows]


def product_profitability(months: int = 12) -> List[Dict[str, Any]]:
    """Per-product revenue and cost of sales (real product grain, not GL accounts)."""
    with tx() as conn:
        rows = q(conn, """SELECT l.sku AS product_id, COALESCE(p.name, MAX(l.description)) AS product_name,
                                 SUM(l.amount) AS revenue, SUM(COALESCE(l.cost,0)) AS cost, SUM(l.quantity) AS units
                          FROM v_sales_lines l LEFT JOIN fin_products p ON p.sku = l.sku
                          WHERE l.sku IS NOT NULL AND l.invoice_date >= (SELECT MAX(invoice_date) FROM v_sales_lines) - make_interval(months => %s)
                          GROUP BY l.sku, p.name ORDER BY revenue DESC""", (months,))
    return [{"product_id": r["product_id"], "product_name": r["product_name"], "entity_kind": "product",
             "revenue": round(_f(r["revenue"]), 2), "cost": round(_f(r["cost"]), 2), "units": _f(r["units"])} for r in rows]


def sold_units_by_month(periods: int = 6) -> List[Dict[str, Any]]:
    with tx() as conn:
        return q(conn, """SELECT to_char(invoice_date,'YYYY-MM') AS period, SUM(quantity) AS qty FROM v_sales_lines
                          WHERE sku IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT %s""", (periods,))[::-1]


def stock_totals() -> Dict[str, Any]:
    with tx() as conn:
        r = q1(conn, """SELECT COALESCE(SUM(current_stock),0) AS units, COUNT(*) FILTER (WHERE current_stock > 0) AS skus_in_stock,
                               COUNT(*) AS skus FROM v_inventory""")
        v = q1(conn, "SELECT COALESCE(SUM(qty_remaining*unit_cost),0) AS value FROM fin_cost_layers")
    return {"units": _f(r["units"]), "skus_in_stock": r["skus_in_stock"], "skus": r["skus"], "value": _f(v["value"])}


def traded_skus(since: dt.date) -> set:
    with tx() as conn:
        rows = q(conn, """SELECT DISTINCT sku FROM v_sales_lines WHERE sku IS NOT NULL AND invoice_date >= %s
                          UNION SELECT DISTINCT sku FROM fin_inventory_transactions WHERE txn_date >= %s""", (since, since))
    return {r["sku"] for r in rows}


# ---------------------------------------------------------------------------
# Receivables trend, counts, freshness
# ---------------------------------------------------------------------------

def ar_by_month(periods: int = 6) -> List[Dict[str, Any]]:
    """Invoiced amount and what is still open, per invoice month (Sage history + ACE Books)."""
    with tx() as conn:
        rows = q(conn, """SELECT to_char(date,'YYYY-MM') AS period, SUM(amount) AS amount, SUM(balance) AS balance
                          FROM v_customer_invoices WHERE amount > 0 GROUP BY 1 ORDER BY 1 DESC LIMIT %s""", (periods,))
    return [{"period": r["period"], "amount": _f(r["amount"]), "balance": _f(r["balance"])} for r in rows][::-1]


def data_counts() -> Dict[str, Any]:
    with tx() as conn:
        return dict(q1(conn, """SELECT (SELECT COUNT(*) FROM customers) AS customers,
                                       (SELECT COUNT(*) FROM fin_products) AS products,
                                       (SELECT COUNT(*) FROM fin_journal_lines) AS gl_lines,
                                       (SELECT COUNT(*) FROM v_customer_invoices) AS invoices,
                                       (SELECT COUNT(*) FROM fin_sales_invoices WHERE NOT is_opening AND status NOT IN ('DRAFT','VOID')) AS ace_invoices,
                                       (SELECT MAX(GREATEST(COALESCE(posted_at, created_at), created_at)) FROM fin_journals) AS last_posting"""))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def gl_rows(limit: int = 1000, include_opening: bool = False) -> List[Dict[str, Any]]:
    """Monthly ledger movement per account, newest period first (the legacy GL snapshot shape)."""
    with tx() as conn:
        rows = q(conn, """SELECT period, account_code, account_name, account_type, subtype, journal_type,
                                 debit, credit FROM v_gl_monthly
                          WHERE (%s OR journal_type NOT IN ('OPENING','CLOSING'))
                          ORDER BY period DESC, account_code LIMIT %s""", (include_opening, limit))
    return [{**r, "debit": _f(r["debit"]), "credit": _f(r["credit"])} for r in rows]


def gl_detail(limit: int = 500, offset: int = 0, account_code: Optional[str] = None) -> List[Dict[str, Any]]:
    with tx() as conn:
        return q(conn, """SELECT line_id AS id, account_code, account_name, journal_date AS txn_date, COALESCE(source_ref, journal_number) AS reference,
                                 journal_type, COALESCE(description, journal_description) AS description, debit, credit, journal_number
                          FROM fin_v_general_ledger WHERE (%s::text IS NULL OR account_code=%s)
                          ORDER BY journal_date DESC, journal_number DESC, line_no LIMIT %s OFFSET %s""",
                 (account_code, account_code, limit, offset))


def gl_account_summary() -> List[Dict[str, Any]]:
    today = dt.date.today()
    fy = dt.date(today.year, 1, 1)
    with tx() as conn:
        return q(conn, """SELECT account_code, account_name,
                                 SUM(CASE WHEN journal_date < %s THEN debit-credit ELSE 0 END) AS beginning_balance,
                                 SUM(CASE WHEN journal_date >= %s THEN debit ELSE 0 END) AS debit_change,
                                 SUM(CASE WHEN journal_date >= %s THEN credit ELSE 0 END) AS credit_change,
                                 SUM(CASE WHEN journal_date >= %s THEN debit-credit ELSE 0 END) AS net_change,
                                 SUM(debit-credit) AS ending_balance
                          FROM fin_v_general_ledger GROUP BY account_code, account_name ORDER BY account_code""", (fy, fy, fy, fy))


def cash_register(limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
    with tx() as conn:
        return q(conn, """SELECT line_id AS id, journal_date AS txn_date, journal_number AS trans_no, journal_type AS txn_type,
                                 COALESCE(description, journal_description) AS description, source_ref AS reference,
                                 credit AS payment_amount, debit AS receipt_amount, account_name,
                                 SUM(debit-credit) OVER (ORDER BY journal_date, journal_number, line_no) AS running_balance
                          FROM fin_v_general_ledger WHERE subtype='CASH'
                          ORDER BY journal_date DESC, journal_number DESC LIMIT %s OFFSET %s""", (limit, offset))


# ---------------------------------------------------------------------------
# Margin drivers (replaces the 4-digit-code GL bucketing, which never matched
# this client's 5-digit chart and reported zero revenue)
# ---------------------------------------------------------------------------

_DRIVERS = [
    ("Cost of Goods Sold", "COGS", "Direct product / vaccine acquisition cost", ("COST_OF_SALES",), None),
    ("Salaries & Workforce", "Workforce", "Payroll, benefits and staff costs", ("OPERATING_EXPENSE",),
     ("salar", "wage", "staff", "pension", "payroll", "allowance", "bonus", "nhf", "paye")),
    ("Cold-Chain & Logistics", "Logistics", "Cold storage, distribution and delivery", ("OPERATING_EXPENSE",),
     ("deliver", "transport", "freight", "fuel", "logist", "cold", "vehicle", "courier", "haulage")),
    ("Premises & Utilities", "Premises", "Rent, power, diesel, water and maintenance", ("OPERATING_EXPENSE",),
     ("rent", "electric", "power", "diesel", "generator", "water", "utilit", "repair", "maintenance")),
    ("Quality Assurance & Compliance", "QA/Compliance", "NAFDAC, regulatory and QA costs", ("OPERATING_EXPENSE",),
     ("nafdac", "regulat", "licen", "permit", "quality", "audit")),
    ("Finance Costs", "Finance", "Bank charges and interest", ("OPERATING_EXPENSE", "OTHER_EXPENSE"),
     ("bank charge", "interest", "commission")),
    ("General Overheads", "Overheads", "Other operating expenses", ("OPERATING_EXPENSE", "OTHER_EXPENSE"), ()),
]


def _driver_for(subtype: str, name: str) -> Optional[int]:
    lname = (name or "").lower()
    for i, (_, _, _, subs, words) in enumerate(_DRIVERS):
        if subtype not in subs:
            continue
        if words is None or words == () or any(w in lname for w in words):
            return i
    return None


def margin_drivers() -> Dict[str, Any]:
    """Year-to-date cost drivers against revenue, with month-on-month change where ACE Books has monthly postings."""
    today = dt.date.today()
    with tx() as conn:
        fy = dt.date(today.year, 1, 1)
        rows = q(conn, """SELECT account_name, subtype, account_type,
                                 CASE WHEN journal_type='OPENING' THEN 'OPENING' ELSE to_char(journal_date,'YYYY-MM') END AS period,
                                 SUM(debit-credit) AS net
                          FROM fin_v_general_ledger
                          WHERE account_type IN ('REVENUE','EXPENSE') AND journal_type <> 'CLOSING'
                            AND (journal_date >= %s OR journal_type='OPENING')
                          GROUP BY 1,2,3,4""", (fy,))
        last = q1(conn, "SELECT MAX(COALESCE(posted_at, created_at)) AS t FROM fin_journals")["t"]
    revenue = sum(-_f(r["net"]) for r in rows if r["subtype"] == "SALES")
    cost: Dict[int, float] = {}
    by_period: Dict[int, Dict[str, float]] = {}
    months = sorted({r["period"] for r in rows if r["period"] != "OPENING"})
    for r in rows:
        if r["account_type"] != "EXPENSE":
            continue
        i = _driver_for(r["subtype"], r["account_name"])
        if i is None:
            continue
        cost[i] = cost.get(i, 0.0) + _f(r["net"])
        by_period.setdefault(i, {})[r["period"]] = by_period.setdefault(i, {}).get(r["period"], 0.0) + _f(r["net"])
    total_cost = sum(cost.values())
    out = []
    for i, (name, short, desc, _, _) in enumerate(_DRIVERS):
        c = max(cost.get(i, 0.0), 0.0)
        pct = round(c / revenue * 100, 2) if revenue > 0 else 0.0
        mom = 0.0
        if len(months) >= 2:
            prev, curr = by_period.get(i, {}).get(months[-2], 0.0), by_period.get(i, {}).get(months[-1], 0.0)
            mom = round((curr - prev) / prev * 100, 2) if prev else 0.0
        sev = "high" if pct > 40 or (mom > 15 and pct > 15) else "medium" if pct > 20 or mom > 10 else "low"
        out.append({"name": name, "short": short, "account_range": "by account type", "description": desc, "cost": round(c, 2),
                    "pct_of_revenue": pct, "mom_change_pct": mom, "trend": "up" if mom > 0 else "down" if mom < 0 else "flat",
                    "severity": sev if c > 0 else "low"})
    out.sort(key=lambda x: -x["pct_of_revenue"])
    return {"overall_margin_pct": round((revenue - total_cost) / revenue * 100, 2) if revenue > 0 else 0.0,
            "total_revenue": round(revenue, 2), "total_cost": round(total_cost, 2),
            "top_drivers": [d for d in out if d["cost"] > 0][:3], "all_drivers": out,
            "last_updated": last.isoformat() if last else None, "source": "ACE Books (year to date)",
            "months_with_postings": months}
