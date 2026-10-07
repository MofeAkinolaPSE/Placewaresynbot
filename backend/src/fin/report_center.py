"""ACE Books Report Center: the Sage 50 report set as tabular, downloadable reports.

Every report returns ``{"title", "columns", "rows", "totals"}``. Columns carry a
type (text/money/qty/date) and optionally a ``link`` naming the lineage target
(invoice, receipt, bill, payment, customer, supplier, product, batch, account,
journal, source) plus the row field holding its id. The React Report Center
turns those into clicks, so every figure opens the record behind it
(report -> summary -> transaction -> journal -> source document).

Structured statements (P&L, balance sheet, cash flow, ageing, TB, GL,
Sage-style journals, valuation, unit activity) live in ``reports.py``/``ledger.py``;
this module adds the list/register/analysis reports Sage offers around them.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from src.fin import ledger, reports
from src.fin.db import ZERO, money, q, q1
from src.fin.errors import FinError, invalid

REPORTS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def report(key: str):
    def deco(fn):
        REPORTS[key] = fn
        return fn
    return deco


def C(key: str, label: str, type_: str = "text", link: Optional[str] = None, id_field: Optional[str] = None) -> Dict[str, Any]:
    c = {"key": key, "label": label, "type": type_}
    if link:
        c["link"] = link
        c["id"] = id_field or key
    return c


def _tot(rows: List[Dict[str, Any]], *keys: str) -> Dict[str, Any]:
    return {k: sum((money(r.get(k)) for r in rows), ZERO) for k in keys}


def run(conn, entity_id: str, key: str, p: Dict[str, Any]) -> Dict[str, Any]:
    fn = REPORTS.get(key)
    if not fn:
        raise FinError("RESOURCE_NOT_FOUND", f"Unknown report {key}", {"available": sorted(REPORTS)})
    out = fn(conn, entity_id, p)
    out.setdefault("totals", {})
    out["key"] = key
    return out


# ---------------------------------------------------------------------------
# General ledger
# ---------------------------------------------------------------------------

@report("chart-of-accounts")
def chart_of_accounts(conn, e, p):
    from src.fin import books_ledger
    rows = q(conn, """SELECT a.id AS account_id, a.code, a.name, a.account_type, a.subtype, a.normal_balance,
                             a.is_control, a.is_postable, a.status, a.legacy_code, a.legacy_type
                      FROM fin_accounts a WHERE a.legal_entity_id=%s ORDER BY a.code""", (e,))
    bal = books_ledger.balances(conn, e, p["as_of"])
    for r in rows:
        r["balance"] = bal.get(r["code"], ZERO)
        r["account_type"] = r["account_type"].title()
        r["subtype"] = r["subtype"].replace("_", " ").title()
        r["flags"] = ", ".join(x for x, on in (("control", r["is_control"]), ("header", not r["is_postable"])) if on)
    return {"title": "Chart of Accounts", "subtitle": f"Balances as of {p['as_of']}",
            "columns": [C("code", "Account ID", link="account", id_field="account_id"), C("name", "Description"),
                        C("account_type", "Type"), C("subtype", "Subtype"), C("normal_balance", "Normal"),
                        C("status", "Status"), C("flags", "Flags"), C("legacy_type", "Sage type"),
                        C("balance", "Balance", "money", link="account", id_field="account_id")],
            "rows": rows}


@report("gl-account-summary")
def gl_account_summary(conn, e, p):
    from src.fin import books_ledger
    rows = books_ledger.gl_summary(conn, e, p["from"], p["to"])["rows"]
    return {"title": "General Ledger Account Summary", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("code", "Account ID", link="account", id_field="account_id"), C("name", "Description"),
                        C("opening", "Beginning balance", "money"), C("debit", "Debits", "money", link="account", id_field="account_id"),
                        C("credit", "Credits", "money", link="account", id_field="account_id"), C("closing", "Ending balance", "money")],
            "rows": rows, "totals": _tot(rows, "debit", "credit")}


@report("working-trial-balance")
def working_trial_balance(conn, e, p):
    tb = ledger.trial_balance(conn, e, p["from"], p["to"])
    rows = [{"account_id": r["account_id"], "code": r["code"], "name": r["name"], "closing_debit": r["closing_debit"],
             "closing_credit": r["closing_credit"], "adj_debit": None, "adj_credit": None, "final": None} for r in tb["rows"]]
    return {"title": "Working Trial Balance", "subtitle": f"As of {p['to']} - blank columns for the accountant's adjustments",
            "columns": [C("code", "Account ID", link="account", id_field="account_id"), C("name", "Description"),
                        C("closing_debit", "Debit", "money"), C("closing_credit", "Credit", "money"),
                        C("adj_debit", "Adjustment Dr", "money"), C("adj_credit", "Adjustment Cr", "money"), C("final", "Final balance", "money")],
            "rows": rows, "totals": _tot(rows, "closing_debit", "closing_credit")}


@report("account-register")
def account_register(conn, e, p):
    if not p.get("account_id"):
        raise invalid("Choose an account (e.g. a bank account) for the register")
    from src.fin import books_ledger
    a = q1(conn, "SELECT code FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (p["account_id"], e))
    g = books_ledger.gl_account(conn, e, a["code"], p["from"], p["to"])
    rows = [{**l, "journal_date": l["date"], "ref": l["reference"], "running_balance": l["balance"],
             "txn_id": f"{l['date']}|{l.get('jrnl') or ''}|{l.get('reference') or ''}"} for m in g["months"] for l in m["lines"]]
    acct = g["account"]
    return {"title": f"Account Register - {acct['code']} {acct['name']}",
            "subtitle": f"{p['from']} to {p['to']} · opening {g['opening']:,.2f} · closing {g['closing']:,.2f}",
            "columns": [C("journal_date", "Date", "date"), C("ref", "Reference", link="txn", id_field="txn_id"), C("jrnl", "Jrnl"),
                        C("description", "Trans Description"), C("debit", "Debit", "money"), C("credit", "Credit", "money"),
                        C("running_balance", "Balance", "money"), C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "debit", "credit")}


# ---------------------------------------------------------------------------
# Revenue lineage: Revenue -> month -> customer -> invoice -> journal
# ---------------------------------------------------------------------------

@report("sales-analysis")
def sales_analysis(conn, e, p):
    """Drillable revenue: by month, then a month by customer, then a customer's invoices."""
    where, prm = ["i.legal_entity_id=%s", "i.status NOT IN ('DRAFT','VOID')", "NOT i.is_opening",
                  "i.invoice_date BETWEEN %s AND %s"], [e, p["from"], p["to"]]
    if p.get("month"):
        y, m = map(int, str(p["month"]).split("-"))
        start = dt.date(y, m, 1)
        end = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        where.append("i.invoice_date BETWEEN %s AND %s")
        prm += [start, end]
    if p.get("customer_id"):
        where.append("i.customer_id=%s")
        prm.append(int(p["customer_id"]))
    w = " AND ".join(where)
    level = "invoice" if p.get("customer_id") else ("customer" if p.get("month") else "month")
    base = f"""FROM fin_sales_invoices i LEFT JOIN customers c ON c.id=i.customer_id
               LEFT JOIN fin_journals j ON j.id=i.journal_id
               LEFT JOIN LATERAL (SELECT COALESCE(SUM(l.cost_amount),0) cost FROM fin_sales_invoice_lines l WHERE l.invoice_id=i.id) k ON TRUE
               WHERE {w}"""
    if level == "month":
        rows = q(conn, f"""SELECT to_char(i.invoice_date,'YYYY-MM') AS month, COUNT(*) AS invoices,
                                  COUNT(DISTINCT i.customer_id) AS customers, SUM(i.total) AS sales, SUM(k.cost) AS cost,
                                  SUM(i.total) - SUM(k.cost) AS margin {base} GROUP BY 1 ORDER BY 1""", prm)
        cols = [C("month", "Month", link="drill:month", id_field="month"), C("invoices", "Invoices", "qty"), C("customers", "Customers", "qty"),
                C("sales", "Sales", "money", link="drill:month", id_field="month"), C("cost", "Cost of sales", "money"), C("margin", "Gross margin", "money")]
        title = "Sales analysis - by month"
    elif level == "customer":
        rows = q(conn, f"""SELECT i.customer_id, c.name AS customer, c.customer_code, COUNT(*) AS invoices, SUM(i.total) AS sales,
                                  SUM(k.cost) AS cost, SUM(i.total) - SUM(k.cost) AS margin, %s AS month
                           {base} GROUP BY i.customer_id, c.name, c.customer_code ORDER BY sales DESC""", [p["month"]] + prm)
        cols = [C("customer", "Customer", link="drill:customer", id_field="customer_id"), C("customer_code", "Code"),
                C("invoices", "Invoices", "qty"), C("sales", "Sales", "money", link="drill:customer", id_field="customer_id"),
                C("cost", "Cost of sales", "money"), C("margin", "Gross margin", "money")]
        title = f"Sales analysis - {p['month']} by customer"
    else:
        rows = q(conn, f"""SELECT i.id AS invoice_id, i.invoice_number, i.invoice_date, i.customer_id, c.name AS customer, i.total AS sales,
                                  k.cost, i.total - k.cost AS margin, i.status, i.journal_id, j.journal_number
                           {base}
                           ORDER BY i.invoice_date, i.invoice_number""", prm)
        cols = [C("invoice_date", "Date", "date"), C("invoice_number", "Invoice", link="invoice", id_field="invoice_id"),
                C("customer", "Customer", link="customer", id_field="customer_id"), C("sales", "Sales", "money", link="invoice", id_field="invoice_id"),
                C("cost", "Cost of sales", "money"), C("margin", "Gross margin", "money"), C("status", "Status"),
                C("journal_number", "Journal", link="journal", id_field="journal_id")]
        title = "Sales analysis - invoices"
    return {"title": title, "subtitle": f"{p['from']} to {p['to']}", "level": level, "columns": cols, "rows": rows,
            "totals": _tot(rows, "sales", "cost", "margin")}


# ---------------------------------------------------------------------------
# Accounts receivable
# ---------------------------------------------------------------------------

@report("invoice-register")
def invoice_register(conn, e, p):
    rows = q(conn, """SELECT i.id AS invoice_id, i.invoice_number, i.invoice_date, i.due_date, i.customer_id, c.name AS customer,
                             i.source_type, i.total, i.amount_settled, i.total - i.amount_settled AS balance, i.status,
                             i.journal_id, j.journal_number
                      FROM fin_sales_invoices i LEFT JOIN customers c ON c.id=i.customer_id LEFT JOIN fin_journals j ON j.id=i.journal_id
                      WHERE i.legal_entity_id=%s AND i.invoice_date BETWEEN %s AND %s AND i.status <> 'DRAFT'
                      ORDER BY i.invoice_date, i.invoice_number""", (e, p["from"], p["to"]))
    return {"title": "Invoice Register", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("invoice_date", "Date", "date"), C("invoice_number", "Invoice", link="invoice", id_field="invoice_id"),
                        C("customer", "Customer", link="customer", id_field="customer_id"), C("source_type", "Source"),
                        C("due_date", "Due", "date"), C("total", "Amount", "money", link="invoice", id_field="invoice_id"),
                        C("amount_settled", "Paid", "money"), C("balance", "Balance", "money"), C("status", "Status"),
                        C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "total", "amount_settled", "balance")}


@report("receipts-register")
def receipts_register(conn, e, p):
    rows = q(conn, """SELECT r.id AS receipt_id, r.receipt_number, r.receipt_date, r.customer_id, c.name AS customer, r.method,
                             r.reference, b.name AS bank, r.amount, r.wht_amount, r.status, r.journal_id, j.journal_number
                      FROM fin_customer_receipts r LEFT JOIN customers c ON c.id=r.customer_id
                      LEFT JOIN fin_bank_accounts b ON b.id=r.bank_account_id LEFT JOIN fin_journals j ON j.id=r.journal_id
                      WHERE r.legal_entity_id=%s AND r.receipt_date BETWEEN %s AND %s ORDER BY r.receipt_date, r.receipt_number""",
             (e, p["from"], p["to"]))
    return {"title": "Receipts Register / Bank Deposit Report", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("receipt_date", "Date", "date"), C("receipt_number", "Receipt", link="receipt", id_field="receipt_id"),
                        C("customer", "Customer", link="customer", id_field="customer_id"), C("method", "Method"), C("reference", "Cheque / ref"),
                        C("bank", "Deposited to"), C("amount", "Amount", "money", link="receipt", id_field="receipt_id"),
                        C("wht_amount", "WHT", "money"), C("status", "Status"), C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "amount", "wht_amount")}


def _party_ledger(conn, e, p, kind: str):
    """Customer / vendor ledgers: every party's opening, documents and running balance."""
    if kind == "customer":
        docs = """SELECT i.customer_id AS pid, i.invoice_date AS date, 'Invoice' AS type, i.invoice_number AS number, i.id::text AS doc_id,
                         'invoice' AS link, i.total AS debit, 0::numeric AS credit FROM fin_sales_invoices i
                  WHERE i.legal_entity_id=%(e)s AND i.status <> 'DRAFT'
                  UNION ALL SELECT i.customer_id, i.voided_at::date, 'Invoice void', i.invoice_number, i.id::text, 'invoice', 0, i.total
                  FROM fin_sales_invoices i WHERE i.legal_entity_id=%(e)s AND i.status='VOID' AND i.journal_id IS NOT NULL
                  UNION ALL SELECT r.customer_id, r.receipt_date, 'Receipt', r.receipt_number, r.id::text, 'receipt', 0, r.amount + r.wht_amount
                  FROM fin_customer_receipts r WHERE r.legal_entity_id=%(e)s
                  UNION ALL SELECT r.customer_id, r.receipt_date, 'Receipt reversed', r.receipt_number, r.id::text, 'receipt', r.amount + r.wht_amount, 0
                  FROM fin_customer_receipts r WHERE r.legal_entity_id=%(e)s AND r.status='VOID'
                  UNION ALL SELECT n.customer_id, n.note_date, 'Credit note', n.credit_note_number, n.id::text, 'creditnote', 0, n.total
                  FROM fin_credit_notes n WHERE n.legal_entity_id=%(e)s"""
        names = "SELECT id::text AS pid, name, customer_code AS code FROM customers"
    else:
        docs = """SELECT b.supplier_id::text AS pid, b.bill_date AS date, 'Bill ' || b.supplier_invoice_number AS type, b.bill_number AS number,
                         b.id::text AS doc_id, 'bill' AS link, 0::numeric AS debit, b.total AS credit FROM fin_supplier_bills b
                  WHERE b.legal_entity_id=%(e)s
                  UNION ALL SELECT b.supplier_id::text, b.bill_date, 'Bill voided', b.bill_number, b.id::text, 'bill', b.total, 0
                  FROM fin_supplier_bills b WHERE b.legal_entity_id=%(e)s AND b.status='VOID' AND b.journal_id IS NOT NULL
                  UNION ALL SELECT p.supplier_id::text, p.payment_date, 'Payment', p.payment_number, p.id::text, 'payment', p.amount + p.wht_amount, 0
                  FROM fin_supplier_payments p WHERE p.legal_entity_id=%(e)s
                  UNION ALL SELECT p.supplier_id::text, p.payment_date, 'Payment reversed', p.payment_number, p.id::text, 'payment', 0, p.amount + p.wht_amount
                  FROM fin_supplier_payments p WHERE p.legal_entity_id=%(e)s AND p.status='VOID'
                  UNION ALL SELECT d.supplier_id::text, d.note_date, 'Debit note', d.debit_note_number, d.id::text, 'debitnote', d.total, 0
                  FROM fin_debit_notes d WHERE d.legal_entity_id=%(e)s"""
        names = "SELECT id::text AS pid, name, external_vendor_id AS code FROM suppliers"
    sign = "debit - credit" if kind == "customer" else "credit - debit"
    party_filter = " AND d.pid::text = %(pid)s" if p.get("party_id") else ""
    rows = q(conn, f"""
        WITH d AS ({docs}), n AS ({names}),
        o AS (SELECT pid::text pid, SUM({sign}) opening FROM d WHERE date < %(f)s GROUP BY 1),
        m AS (SELECT d.*, d.pid::text AS p2 FROM d WHERE date BETWEEN %(f)s AND %(t)s {party_filter})
        SELECT m.p2 AS party_id, n.name AS party, n.code, m.date, m.type, m.number, m.doc_id, m.link, m.debit, m.credit,
               COALESCE(o.opening,0) + SUM({sign.replace('debit', 'm.debit').replace('credit', 'm.credit')})
                   OVER (PARTITION BY m.p2 ORDER BY m.date, m.number ROWS UNBOUNDED PRECEDING) AS balance,
               COALESCE(o.opening,0) AS opening
        FROM m LEFT JOIN n ON n.pid=m.p2 LEFT JOIN o ON o.pid=m.p2
        ORDER BY n.name, m.date, m.number""", {"e": e, "f": p["from"], "t": p["to"], "pid": str(p.get("party_id") or "")})
    party_link = "customer" if kind == "customer" else "supplier"
    return rows, party_link


def _sage_ledger(conn, e, p, kind: str):
    from src.fin import ledger_reports
    pid = p.get("customer_id") if kind == "CUSTOMER" else p.get("supplier_id")
    led = ledger_reports.party_ledger(conn, e, kind, p["from"], p["to"], str(pid) if pid else None)
    for r in led["rows"]:
        r["number"] = r["trans_no"]
        if r.get("source") == "sage" and r.get("trans_no"):
            # Sage rows open the Sage document: a sale (SJ), a receipt (CRJ) or a supplier invoice (PJ)
            r["link"] = {"SJ": "sageinvoice", "CRJ": "sagereceipt", "PJ": "sagebill", "CDJ": "sagetxn"}.get(r.get("type") or "")
            r["doc_id"] = r["trans_no"] if r["link"] in ("sageinvoice", "sagebill") else f"{r['date']}|{r['trans_no']}|{r['party']}"
    return led


@report("customer-ledgers")
def customer_ledgers(conn, e, p):
    led = _sage_ledger(conn, e, p, "CUSTOMER")
    return {"title": "Customer Ledgers", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("party_code", "Customer ID", link="customer", id_field="party_id"), C("party", "Customer", link="customer", id_field="party_id"),
                        C("date", "Date", "date"), C("trans_no", "Trans No", link="doc", id_field="doc_id"), C("type", "Type"),
                        C("debit", "Debit Amt", "money"), C("credit", "Credit Amt", "money"), C("balance", "Balance", "money")],
            "rows": led["rows"], "totals": {"debit": led["total_debit"], "credit": led["total_credit"]}}


@report("vendor-ledgers")
def vendor_ledgers(conn, e, p):
    led = _sage_ledger(conn, e, p, "VENDOR")
    return {"title": "Vendor Ledgers", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("party_code", "Vendor ID", link="supplier", id_field="party_id"), C("party", "Vendor", link="supplier", id_field="party_id"),
                        C("date", "Date", "date"), C("trans_no", "Trans No", link="doc", id_field="doc_id"), C("type", "Type"), C("paid", "Paid"),
                        C("debit", "Debit Amt", "money"), C("credit", "Credit Amt", "money"), C("balance", "Balance", "money")],
            "rows": led["rows"], "totals": {"debit": led["total_debit"], "credit": led["total_credit"]}}


@report("customer-sales-history")
def customer_sales_history(conn, e, p):
    rows = q(conn, """SELECT i.customer_id, c.name AS customer, c.customer_code, COUNT(DISTINCT i.id) AS invoices,
                             COALESCE(SUM(l.quantity) FILTER (WHERE l.line_type='ITEM'),0) AS units, SUM(l.line_total) AS sales,
                             COALESCE(SUM(l.cost_amount),0) AS cost, SUM(l.line_total) - COALESCE(SUM(l.cost_amount),0) AS margin,
                             MAX(i.invoice_date) AS last_sale
                      FROM fin_sales_invoices i JOIN fin_sales_invoice_lines l ON l.invoice_id=i.id LEFT JOIN customers c ON c.id=i.customer_id
                      WHERE i.legal_entity_id=%s AND i.status NOT IN ('DRAFT','VOID') AND NOT i.is_opening AND i.invoice_date BETWEEN %s AND %s
                      GROUP BY i.customer_id, c.name, c.customer_code ORDER BY sales DESC""", (e, p["from"], p["to"]))
    return {"title": "Customer Sales History", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("customer", "Customer", link="customer", id_field="customer_id"), C("customer_code", "Code"),
                        C("invoices", "Invoices", "qty"), C("units", "Units", "qty"), C("sales", "Sales", "money"),
                        C("cost", "Cost", "money"), C("margin", "Margin", "money"), C("last_sale", "Last sale", "date")],
            "rows": rows, "totals": _tot(rows, "sales", "cost", "margin")}


@report("items-sold-to-customers")
def items_sold(conn, e, p):
    rows = q(conn, """SELECT l.sku, p.name AS product, i.customer_id, c.name AS customer, SUM(l.quantity) AS quantity,
                             SUM(l.line_total) AS amount, COALESCE(SUM(l.cost_amount),0) AS cost,
                             SUM(l.line_total) - COALESCE(SUM(l.cost_amount),0) AS margin,
                             string_agg(DISTINCT i.invoice_number, ', ') AS invoices, MIN(i.id::text) AS invoice_id
                      FROM fin_sales_invoice_lines l JOIN fin_sales_invoices i ON i.id=l.invoice_id
                      LEFT JOIN fin_products p ON p.legal_entity_id=i.legal_entity_id AND p.sku=l.sku LEFT JOIN customers c ON c.id=i.customer_id
                      WHERE i.legal_entity_id=%s AND l.sku IS NOT NULL AND i.status NOT IN ('DRAFT','VOID') AND NOT i.is_opening
                        AND i.invoice_date BETWEEN %s AND %s
                      GROUP BY l.sku, p.name, i.customer_id, c.name ORDER BY l.sku, amount DESC""", (e, p["from"], p["to"]))
    return {"title": "Items Sold to Customers", "subtitle": f"{p['from']} to {p['to']} - who bought what",
            "columns": [C("sku", "Item ID", link="product", id_field="sku"), C("product", "Description"),
                        C("customer", "Customer", link="customer", id_field="customer_id"), C("quantity", "Qty", "qty"),
                        C("amount", "Amount", "money"), C("cost", "Cost", "money"), C("margin", "Margin", "money"), C("invoices", "Invoices")],
            "rows": rows, "totals": _tot(rows, "amount", "cost", "margin")}


@report("customer-list")
def customer_list(conn, e, p):
    open_ = {}
    for it in reports.ar_open_items(conn, e, p["as_of"]):
        open_[it["customer_id"]] = open_.get(it["customer_id"], ZERO) + money(it["open_amount"])
    rows = q(conn, """SELECT id AS customer_id, customer_code, name, client_type, facility_type, credit_limit, payment_terms_days,
                             contact_details->>'phone' AS phone, contact_details->>'email' AS email, contact_details->>'address' AS address
                      FROM customers ORDER BY name""")
    for r in rows:
        r["balance"] = open_.get(r["customer_id"], ZERO)
    if p.get("with_balance"):
        rows = [r for r in rows if r["balance"] != 0]
    return {"title": "Customer List / Master File", "subtitle": f"Balances as of {p['as_of']}",
            "columns": [C("customer_code", "Customer ID"), C("name", "Name", link="customer", id_field="customer_id"), C("client_type", "Type"),
                        C("phone", "Phone"), C("email", "Email"), C("address", "Address"), C("payment_terms_days", "Terms (days)", "qty"),
                        C("credit_limit", "Credit limit", "money"), C("balance", "Balance", "money", link="customer", id_field="customer_id")],
            "rows": rows, "totals": _tot(rows, "balance")}


# ---------------------------------------------------------------------------
# Accounts payable
# ---------------------------------------------------------------------------

@report("purchase-register")
def purchase_register(conn, e, p):
    rows = q(conn, """SELECT b.id AS bill_id, b.bill_number, b.supplier_invoice_number, b.bill_date, b.due_date, b.supplier_id::text AS supplier_id,
                             s.name AS supplier, b.total, b.amount_settled, b.total - b.amount_settled AS balance, b.status, b.journal_id, j.journal_number
                      FROM fin_supplier_bills b LEFT JOIN suppliers s ON s.id=b.supplier_id LEFT JOIN fin_journals j ON j.id=b.journal_id
                      WHERE b.legal_entity_id=%s AND b.bill_date BETWEEN %s AND %s ORDER BY b.bill_date, b.bill_number""", (e, p["from"], p["to"]))
    return {"title": "Purchase Register", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("bill_date", "Date", "date"), C("bill_number", "Bill", link="bill", id_field="bill_id"),
                        C("supplier_invoice_number", "Vendor invoice"), C("supplier", "Vendor", link="supplier", id_field="supplier_id"),
                        C("due_date", "Due", "date"), C("total", "Amount", "money"), C("amount_settled", "Paid", "money"),
                        C("balance", "Balance", "money"), C("status", "Status"), C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "total", "amount_settled", "balance")}


@report("check-register")
def check_register(conn, e, p):
    rows = q(conn, """SELECT * FROM (
                        SELECT p.payment_date AS date, p.payment_number AS number, p.id::text AS doc_id, 'payment' AS link, p.method,
                               p.reference, s.name AS payee, b.name AS bank, p.amount, p.status, p.journal_id, j.journal_number
                        FROM fin_supplier_payments p LEFT JOIN suppliers s ON s.id=p.supplier_id
                        LEFT JOIN fin_bank_accounts b ON b.id=p.bank_account_id LEFT JOIN fin_journals j ON j.id=p.journal_id
                        WHERE p.legal_entity_id=%s AND p.payment_date BETWEEN %s AND %s
                        UNION ALL
                        SELECT v.voucher_date, v.voucher_number, v.id::text, 'voucher', 'VOUCHER', v.reference, COALESCE(v.payee, v.description),
                               b.name, v.amount, v.status, v.journal_id, j.journal_number
                        FROM fin_cash_vouchers v LEFT JOIN fin_bank_accounts b ON b.id=v.bank_account_id LEFT JOIN fin_journals j ON j.id=v.journal_id
                        WHERE v.legal_entity_id=%s AND v.kind='SPEND' AND v.voucher_date BETWEEN %s AND %s) x
                      ORDER BY date, number""", (e, p["from"], p["to"], e, p["from"], p["to"]))
    return {"title": "Check / Payment Register", "subtitle": f"{p['from']} to {p['to']} - supplier payments and payment vouchers",
            "columns": [C("date", "Date", "date"), C("number", "Number", link="doc", id_field="doc_id"), C("method", "Method"),
                        C("reference", "Cheque / ref"), C("payee", "Payee"), C("bank", "Paid from"), C("amount", "Amount", "money"),
                        C("status", "Status"), C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "amount")}


@report("cash-requirements")
def cash_requirements(conn, e, p):
    names = {str(r["id"]): r["name"] for r in q(conn, "SELECT id, name FROM suppliers")}
    rows = []
    for it in reports.ap_open_items(conn, e, p["as_of"]):
        if it["doc_type"] != "BILL":
            continue
        days = (it["due_date"] - p["as_of"]).days
        rows.append({"supplier_id": str(it["supplier_id"]), "supplier": names.get(str(it["supplier_id"])), "bill_id": it["doc_id"],
                     "bill_number": it["doc_number"], "supplier_ref": it["supplier_ref"], "doc_date": it["doc_date"], "due_date": it["due_date"],
                     "days": days, "when": "Overdue" if days < 0 else ("Due within 7 days" if days <= 7 else ("Within 30 days" if days <= 30 else "Later")),
                     "amount": it["open_amount"]})
    rows.sort(key=lambda r: r["due_date"])
    return {"title": "Cash Requirements", "subtitle": f"Unpaid supplier bills by due date, as of {p['as_of']}",
            "columns": [C("due_date", "Due", "date"), C("when", "When"), C("supplier", "Vendor", link="supplier", id_field="supplier_id"),
                        C("bill_number", "Bill", link="bill", id_field="bill_id"), C("supplier_ref", "Vendor invoice"),
                        C("doc_date", "Invoice date", "date"), C("amount", "Amount due", "money")],
            "rows": rows, "totals": _tot(rows, "amount")}


@report("items-purchased-from-vendors")
def items_purchased(conn, e, p):
    rows = q(conn, """SELECT l.sku, pr.name AS product, b.supplier_id::text AS supplier_id, s.name AS supplier, SUM(l.quantity) AS quantity,
                             SUM(l.line_total) AS amount, ROUND(SUM(l.line_total)/NULLIF(SUM(l.quantity),0), 2) AS avg_cost,
                             string_agg(DISTINCT b.bill_number, ', ') AS bills
                      FROM fin_supplier_bill_lines l JOIN fin_supplier_bills b ON b.id=l.bill_id
                      LEFT JOIN fin_products pr ON pr.legal_entity_id=b.legal_entity_id AND pr.sku=l.sku LEFT JOIN suppliers s ON s.id=b.supplier_id
                      WHERE b.legal_entity_id=%s AND l.sku IS NOT NULL AND b.status <> 'VOID' AND b.bill_date BETWEEN %s AND %s
                      GROUP BY l.sku, pr.name, b.supplier_id, s.name ORDER BY l.sku""", (e, p["from"], p["to"]))
    return {"title": "Items Purchased from Vendors", "subtitle": f"{p['from']} to {p['to']}",
            "columns": [C("sku", "Item ID", link="product", id_field="sku"), C("product", "Description"),
                        C("supplier", "Vendor", link="supplier", id_field="supplier_id"), C("quantity", "Qty", "qty"),
                        C("avg_cost", "Avg unit cost", "money"), C("amount", "Amount", "money"), C("bills", "Bills")],
            "rows": rows, "totals": _tot(rows, "amount")}


@report("vendor-list")
def vendor_list(conn, e, p):
    owed: Dict[str, Decimal] = {}
    for it in reports.ap_open_items(conn, e, p["as_of"]):
        owed[str(it["supplier_id"])] = owed.get(str(it["supplier_id"]), ZERO) + money(it["open_amount"])
    rows = q(conn, """SELECT id::text AS supplier_id, external_vendor_id AS code, name, category, contact_name, phone, contact_email,
                             address, payment_terms, tax_id, status FROM suppliers ORDER BY name""")
    for r in rows:
        r["balance"] = owed.get(r["supplier_id"], ZERO)
    return {"title": "Vendor List / Master File", "subtitle": f"Balances as of {p['as_of']}",
            "columns": [C("code", "Vendor ID"), C("name", "Name", link="supplier", id_field="supplier_id"), C("category", "Category"),
                        C("contact_name", "Contact"), C("phone", "Phone"), C("contact_email", "Email"), C("payment_terms", "Terms"),
                        C("tax_id", "TIN"), C("balance", "Balance owed", "money", link="supplier", id_field="supplier_id")],
            "rows": rows, "totals": _tot(rows, "balance")}


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@report("item-costing")
def item_costing(conn, e, p):
    sf = " AND t.sku=%s" if p.get("sku") else ""
    prm: List[Any] = [e, p["from"], p["to"]] + ([p["sku"]] if p.get("sku") else [])
    rows = q(conn, f"""SELECT t.id, t.txn_date, t.sku, pr.name AS product, t.txn_type, t.reference, t.source_type, t.source_id,
                              b.id AS batch_id, b.batch_number, t.quantity, t.unit_cost, t.total_cost,
                              COALESCE(c.name, s.name) AS party, t.customer_id, t.supplier_id::text AS supplier_id, t.journal_id, j.journal_number
                       FROM fin_inventory_transactions t LEFT JOIN fin_batches b ON b.id=t.batch_id
                       LEFT JOIN fin_products pr ON pr.legal_entity_id=t.legal_entity_id AND pr.sku=t.sku
                       LEFT JOIN customers c ON c.id=t.customer_id LEFT JOIN suppliers s ON s.id=t.supplier_id
                       LEFT JOIN fin_journals j ON j.id=t.journal_id
                       WHERE t.legal_entity_id=%s AND t.txn_date BETWEEN %s AND %s {sf}
                       ORDER BY t.sku, t.txn_date, t.created_at""", prm)
    for r in rows:
        r["txn_type"] = r["txn_type"].replace("_", " ").title()
    return {"title": "Item Costing Report", "subtitle": f"{p['from']} to {p['to']} - every stock movement at cost",
            "columns": [C("txn_date", "Date", "date"), C("sku", "Item ID", link="product", id_field="sku"), C("txn_type", "Type"),
                        C("reference", "Reference", link="source", id_field="source_id"), C("party", "Customer / vendor"),
                        C("batch_number", "Batch", link="batch", id_field="batch_id"), C("quantity", "Qty", "qty"),
                        C("unit_cost", "Unit cost", "money"), C("total_cost", "Cost", "money"),
                        C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "total_cost")}


@report("item-master")
def item_master(conn, e, p):
    rows = q(conn, """SELECT p.sku, p.name, p.product_type, p.uom, p.standard_price, p.reorder_level, p.status, p.legacy_class,
                             ra.code AS sales_gl, ia.code AS inventory_gl, ca.code AS cogs_gl,
                             COALESCE(SUM(l.qty_remaining),0) AS on_hand, COALESCE(SUM(l.qty_remaining*l.unit_cost),0) AS value
                      FROM fin_products p LEFT JOIN fin_accounts ra ON ra.id=p.revenue_account_id
                      LEFT JOIN fin_accounts ia ON ia.id=p.inventory_account_id LEFT JOIN fin_accounts ca ON ca.id=p.cogs_account_id
                      LEFT JOIN fin_cost_layers l ON l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku
                      WHERE p.legal_entity_id=%s GROUP BY p.id, ra.code, ia.code, ca.code ORDER BY p.sku""", (e,))
    return {"title": "Item Master List / Price List", "subtitle": "Products with their GL accounts, price and stock",
            "columns": [C("sku", "Item ID", link="product", id_field="sku"), C("name", "Description"), C("product_type", "Type"),
                        C("uom", "UoM"), C("standard_price", "Sales price", "money"), C("reorder_level", "Reorder at", "qty"),
                        C("on_hand", "On hand", "qty"), C("value", "Value", "money"), C("sales_gl", "Sales GL"),
                        C("inventory_gl", "Inventory GL"), C("cogs_gl", "COGS GL"), C("status", "Status")],
            "rows": rows, "totals": _tot(rows, "value")}


@report("inventory-profitability")
def inventory_profitability(conn, e, p):
    rows = q(conn, """SELECT l.sku, pr.name AS product, SUM(l.quantity) AS units, SUM(l.line_total) AS sales,
                             COALESCE(SUM(l.cost_amount),0) AS cost, SUM(l.line_total) - COALESCE(SUM(l.cost_amount),0) AS margin,
                             COUNT(DISTINCT i.customer_id) AS customers
                      FROM fin_sales_invoice_lines l JOIN fin_sales_invoices i ON i.id=l.invoice_id
                      LEFT JOIN fin_products pr ON pr.legal_entity_id=i.legal_entity_id AND pr.sku=l.sku
                      WHERE i.legal_entity_id=%s AND l.sku IS NOT NULL AND i.status NOT IN ('DRAFT','VOID') AND NOT i.is_opening
                        AND i.invoice_date BETWEEN %s AND %s GROUP BY l.sku, pr.name ORDER BY margin DESC""", (e, p["from"], p["to"]))
    for r in rows:
        r["margin_pct"] = (money(r["margin"]) / money(r["sales"]) * 100).quantize(Decimal("0.1")) if money(r["sales"]) else None
    return {"title": "Inventory Profitability", "subtitle": f"{p['from']} to {p['to']} - margin per item",
            "columns": [C("sku", "Item ID", link="product", id_field="sku"), C("product", "Description"), C("units", "Units sold", "qty"),
                        C("customers", "Customers", "qty"), C("sales", "Sales", "money"), C("cost", "Cost", "money"),
                        C("margin", "Margin", "money"), C("margin_pct", "Margin %", "qty")],
            "rows": rows, "totals": _tot(rows, "sales", "cost", "margin")}


@report("reorder-worksheet")
def reorder_worksheet(conn, e, p):
    rows = [r for r in reports.stock_status(conn, e) if r["reorder_level"] is not None and money(r["on_hand"]) <= money(r["reorder_level"])]
    for r in rows:
        r["shortfall"] = money(r["reorder_level"]) - money(r["on_hand"])
    return {"title": "Inventory Reorder Worksheet", "subtitle": "Items at or below their reorder level",
            "columns": [C("sku", "Item ID", link="product", id_field="sku"), C("name", "Description"), C("on_hand", "On hand", "qty"),
                        C("reorder_level", "Reorder at", "qty"), C("shortfall", "Shortfall", "qty"), C("nearest_expiry", "Nearest expiry", "date")],
            "rows": rows}


@report("physical-inventory-list")
def physical_inventory_list(conn, e, p):
    rows = q(conn, """SELECT l.sku, pr.name AS product, b.id AS batch_id, b.batch_number, b.expiry_date, SUM(l.qty_remaining) AS system_qty
                      FROM fin_cost_layers l LEFT JOIN fin_batches b ON b.id=l.batch_id
                      LEFT JOIN fin_products pr ON pr.legal_entity_id=l.legal_entity_id AND pr.sku=l.sku
                      WHERE l.legal_entity_id=%s GROUP BY l.sku, pr.name, b.id HAVING SUM(l.qty_remaining) <> 0
                      ORDER BY l.sku, b.expiry_date""", (e,))
    for r in rows:
        r["counted"] = None
    return {"title": "Physical Inventory List", "subtitle": "Count sheet - print or download and fill in the counted column",
            "columns": [C("sku", "Item ID", link="product", id_field="sku"), C("product", "Description"),
                        C("batch_number", "Batch", link="batch", id_field="batch_id"), C("expiry_date", "Expiry", "date"),
                        C("system_qty", "System qty", "qty"), C("counted", "Counted", "qty")],
            "rows": rows}


# ---------------------------------------------------------------------------
# Account reconciliation
# ---------------------------------------------------------------------------

@report("outstanding-items")
def outstanding_items(conn, e, p):
    af = " AND b.id=%s" if p.get("bank_account_id") else ""
    prm: List[Any] = [e, p["as_of"]] + ([p["bank_account_id"]] if p.get("bank_account_id") else [])
    rows = q(conn, f"""SELECT b.name AS bank, g.journal_date, g.journal_number, g.journal_id, g.source_type, g.source_id, g.source_ref,
                              COALESCE(g.description, g.journal_description) AS description,
                              CASE WHEN g.debit > 0 THEN 'Deposit in transit' ELSE 'Outstanding payment' END AS kind,
                              g.debit - g.credit AS amount, (%s::date - g.journal_date) AS days
                       FROM fin_v_general_ledger g JOIN fin_bank_accounts b ON b.gl_account_id=g.account_id
                       WHERE g.legal_entity_id=%s AND g.journal_date <= %s AND g.journal_type <> 'OPENING' {af}
                         AND NOT EXISTS (SELECT 1 FROM fin_cleared_lines c WHERE c.journal_line_id=g.line_id)
                       ORDER BY b.name, g.journal_date""", [p["as_of"]] + prm)
    return {"title": "Outstanding Items (Deposits in Transit / Outstanding Payments)", "subtitle": f"Uncleared bank entries as of {p['as_of']}",
            "columns": [C("bank", "Bank account"), C("journal_date", "Date", "date"), C("kind", "Kind"),
                        C("source_ref", "Reference", link="source", id_field="source_id"), C("description", "Description"),
                        C("amount", "Amount", "money"), C("days", "Days outstanding", "qty"),
                        C("journal_number", "Journal", link="journal", id_field="journal_id")],
            "rows": rows, "totals": _tot(rows, "amount")}


@report("reconciliation-history")
def reconciliation_history(conn, e, p):
    rows = q(conn, """SELECT r.reconciliation_number, b.name AS bank, r.as_of, r.statement_balance, r.book_balance, r.cleared_balance,
                             r.difference, r.status, r.completed_by, r.completed_at::date AS completed
                      FROM fin_reconciliations r JOIN fin_bank_accounts b ON b.id=r.bank_account_id
                      WHERE r.legal_entity_id=%s ORDER BY r.as_of DESC""", (e,))
    return {"title": "Account Reconciliation History", "subtitle": "Completed bank reconciliations",
            "columns": [C("reconciliation_number", "Number"), C("bank", "Bank account"), C("as_of", "Statement date", "date"),
                        C("statement_balance", "Statement balance", "money"), C("book_balance", "Book balance", "money"),
                        C("difference", "Difference", "money"), C("completed_by", "By"), C("completed", "Completed", "date")],
            "rows": rows}


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

@report("audit-trail")
def audit_trail(conn, e, p):
    rows = q(conn, """SELECT created_at, actor_name, action, entity_type, entity_ref, entity_id, reason
                      FROM fin_audit_events WHERE legal_entity_id=%s AND created_at::date BETWEEN %s AND %s
                      ORDER BY id DESC LIMIT 20000""", (e, p["from"], p["to"]))
    for r in rows:
        r["action"] = r["action"].replace("_", " ").lower()
        r["entity_type"] = (r["entity_type"] or "").replace("_", " ")
        r["link_type"] = {"journal": "journal", "sales invoice": "invoice", "supplier bill": "bill"}.get(r["entity_type"])
    return {"title": "Audit Trail Report", "subtitle": f"{p['from']} to {p['to']} - who did what, when",
            "columns": [C("created_at", "When", "datetime"), C("actor_name", "User"), C("action", "Action"), C("entity_type", "Record"),
                        C("entity_ref", "Reference"), C("reason", "Reason")],
            "rows": rows}


# ---------------------------------------------------------------------------
# Financial statements (tabular variants)
# ---------------------------------------------------------------------------

@report("income-12-period")
def income_12_period(conn, e, p):
    """Income statement month by month (Sage 'Income - 12 Period')."""
    from src.fin import books_ledger
    accs = books_ledger.accounts(conn, e)
    months: List[str] = []
    rows = []
    d = p["from"].replace(day=1)
    while d <= p["to"]:
        months.append(d.strftime("%Y-%m"))
        end = min(dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1) - dt.timedelta(days=1), p["to"])
        for code, v in books_ledger.movement(conn, e, max(d, p["from"]), end).items():
            a = accs.get(code)
            if a and a["account_type"] in ("REVENUE", "EXPENSE"):
                rows.append({"account_id": a["id"], "code": code, "name": a["name"], "account_type": a["account_type"],
                             "subtype": a["subtype"], "m": d.strftime("%Y-%m"), "v": -v if a["account_type"] == "REVENUE" else v})
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    order = {"SALES": 0, "OTHER_INCOME": 1, "COST_OF_SALES": 2, "OPERATING_EXPENSE": 3, "OTHER_EXPENSE": 4}
    acc: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        a = acc.setdefault(str(r["account_id"]), {"account_id": r["account_id"], "code": r["code"], "name": r["name"],
                                                    "section": r["subtype"].replace("_", " ").title(), "_o": order.get(r["subtype"], 9), "total": ZERO})
        a[r["m"]] = money(r["v"])
        a["total"] += money(r["v"])
    out = sorted(acc.values(), key=lambda x: (x["_o"], x["code"]))
    net = {"code": "", "name": "NET INCOME", "section": "", "total": ZERO}
    for a in out:
        sign = 1 if a["_o"] <= 1 else -1
        for m in months + ["total"]:
            net[m] = net.get(m, ZERO) + sign * money(a.get(m))
    out.append(net)
    return {"title": "Income Statement - 12 Period", "subtitle": f"{p['from']} to {p['to']} month by month (excludes the migrated opening balance)",
            "columns": [C("section", "Section"), C("code", "Account", link="account", id_field="account_id"), C("name", "Description")]
            + [C(m, dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b %Y"), "money", link="account", id_field="account_id") for m in months]
            + [C("total", "Total", "money")],
            "rows": out}


@report("financial-position")
def financial_position(conn, e, p):
    bs = reports.balance_sheet(conn, e, p["as_of"])
    rows = []
    for s in bs["assets"]:
        rows.append({"line": s["title"], "amount": s["total"]})
    rows.append({"line": "TOTAL ASSETS", "amount": bs["total_assets"]})
    for s in bs["liabilities"]:
        rows.append({"line": s["title"], "amount": s["total"]})
    rows.append({"line": "Equity", "amount": bs["total_equity"]})
    rows.append({"line": "TOTAL LIABILITIES & EQUITY", "amount": bs["total_liabilities_and_equity"]})
    return {"title": "Statement of Financial Position (condensed)", "subtitle": f"As of {p['as_of']}",
            "columns": [C("line", "Line"), C("amount", "Amount", "money")], "rows": rows}
