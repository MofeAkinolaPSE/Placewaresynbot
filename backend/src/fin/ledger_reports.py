"""Sage-layout reports across the Sage years and ACE Books: the journals and the customer /
vendor ledgers, plus the lineage reads behind them (a Sage receipt, an invoice's payments).

Up to ``history_until`` the rows are Sage's own (fin_sage_* tables); after it they are ACE
Books documents and journals. Column layouts follow the client's Sage exports exactly.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin.books_ledger import ONE, accounts, history_until
from src.fin.db import ZERO, money, q, q1


def _c(key: str, label: str, type_: str = "text") -> Dict[str, str]:
    return {"key": key, "label": label, "type": type_}


# ---------------------------------------------------------------------------
# Journals (Sales, Cash Receipts, Cash Disbursements, Purchase, COGS, General, Inventory Adj.)
# ---------------------------------------------------------------------------

JOURNAL_LAYOUT = {
    "SJ": ("Sales Journal", [_c("date", "Date", "date"), _c("account", "Account ID"), _c("reference", "Invoice/CM #"),
                             _c("description", "Line Description"), _c("debit", "Debit Amnt", "money"), _c("credit", "Credit Amnt", "money")]),
    "CRJ": ("Cash Receipts Journal", [_c("date", "Date", "date"), _c("account", "Account ID"), _c("reference", "Transaction Ref"),
                                      _c("description", "Line Description"), _c("debit", "Debit Amnt", "money"), _c("credit", "Credit Amnt", "money")]),
    "CDJ": ("Cash Disbursements Journal", [_c("date", "Date", "date"), _c("reference", "Check #"), _c("account", "Account ID"),
                                           _c("description", "Line Description"), _c("debit", "Debit Amount", "money"),
                                           _c("credit", "Credit Amount", "money")]),
    "PJ": ("Purchase Journal", [_c("date", "Date", "date"), _c("account", "Account ID"), _c("account_name", "Account Description"),
                                _c("reference", "Invoice/CM #"), _c("description", "Line Description"), _c("debit", "Debit Amount", "money"),
                                _c("credit", "Credit Amount", "money")]),
    "COGS": ("Cost of Goods Sold Journal", [_c("date", "Date", "date"), _c("account", "GL Acct ID"), _c("reference", "Reference"),
                                            _c("qty", "Qty", "qty"), _c("um", "U/M ID"), _c("description", "Line Description"),
                                            _c("debit", "Debit Amount", "money"), _c("credit", "Credit Amount", "money")]),
    "GENJ": ("General Journal", [_c("date", "Date", "date"), _c("account", "Account ID"), _c("reference", "Reference"),
                                 _c("description", "Trans Description"), _c("debit", "Debit Amt", "money"), _c("credit", "Credit Amt", "money")]),
    "INAJ": ("Inventory Adjustment Journal", [_c("date", "Date", "date"), _c("account", "Account ID"), _c("reference", "Reference"),
                                              _c("description", "Trans Description"), _c("debit", "Debit Amt", "money"),
                                              _c("credit", "Credit Amt", "money")]),
}
JOURNAL_KEYS = {"sales": "SJ", "cash-receipts": "CRJ", "cash-disbursements": "CDJ", "purchases": "PJ", "cogs": "COGS",
                "general": "GENJ", "inventory-adjustments": "INAJ"}
_LOAD_KIND = {"SJ": "SALES_JOURNAL", "CRJ": "CASH_RECEIPTS_JOURNAL", "CDJ": "CASH_DISBURSEMENTS_JOURNAL",
              "PJ": "PURCHASE_JOURNAL", "COGS": "COGS_JOURNAL", "GENJ": "GENERAL_JOURNAL"}


def journal(conn, entity_id: str, key: str, f: dt.date, t: dt.date, search: Optional[str] = None,
            limit: int = 60000) -> Dict[str, Any]:
    from src.fin import reports
    from src.fin.errors import invalid
    code = JOURNAL_KEYS.get(key, key)
    if code not in JOURNAL_LAYOUT:
        raise invalid(f"Unknown journal {key}", allowed=sorted(JOURNAL_KEYS))
    title, columns = JOURNAL_LAYOUT[code]
    h = history_until(conn, entity_id)
    names = {c: a["name"] for c, a in accounts(conn, entity_id).items()}
    rows: List[Dict[str, Any]] = []
    sp = [f"%{search}%"] * 3 if search else []
    if h and f <= h:
        hf, ht = f, min(t, h)
        cov = q1(conn, "SELECT MIN(date_from) d FROM fin_sage_loads WHERE legal_entity_id=%s AND kind=%s",
                 (entity_id, _LOAD_KIND.get(code, "-")))
        if cov and cov["d"] and cov["d"] <= hf:
            # the journal exactly as Sage exported it (order of entry, qty and U/M)
            sf = " AND (description ILIKE %s OR reference ILIKE %s OR account_code ILIKE %s)" if search else ""
            src = q(conn, f"""SELECT txn_date, account_code, account_description, reference, description, qty, um, debit, credit
                              FROM fin_sage_journal_lines WHERE legal_entity_id=%s AND kind=%s AND txn_date BETWEEN %s AND %s {sf}
                              ORDER BY txn_date, seq LIMIT %s""", [entity_id, code, hf, ht] + sp + [limit])
        else:
            # before the exported journal starts: the same lines, from Sage's General Ledger
            sf = " AND (description ILIKE %s OR reference ILIKE %s OR account_code ILIKE %s)" if search else ""
            src = q(conn, f"""SELECT txn_date, account_code, NULL AS account_description, reference, description, NULL::numeric AS qty,
                                     NULL AS um, debit, credit
                              FROM fin_sage_gl_lines WHERE legal_entity_id=%s AND jrnl=%s AND txn_date BETWEEN %s AND %s {sf}
                              ORDER BY txn_date, reference, debit DESC, seq LIMIT %s""", [entity_id, code, hf, ht] + sp + [limit])
        for r in src:
            rows.append({"date": r["txn_date"], "account": r["account_code"],
                         "account_name": r["account_description"] or names.get(r["account_code"]),
                         "reference": r["reference"], "description": r["description"], "qty": r["qty"], "um": r["um"],
                         "debit": r["debit"], "credit": r["credit"], "source": "sage", "jrnl": code})
    a_from = max(f, h + ONE) if h else f
    if a_from <= t:
        ace_key = {v: k for k, v in JOURNAL_KEYS.items()}[code]
        for r in reports.journal_report(conn, entity_id, ace_key, a_from, t)["rows"]:
            if search and not any(search.lower() in str(r.get(k) or "").lower() for k in ("description", "reference", "account_code")):
                continue
            rows.append({"date": r["date"], "account": r["account_code"], "account_name": r["account_name"],
                         "reference": r["reference"] or r["journal_number"], "description": r["description"],
                         "qty": None, "um": None, "debit": r["debit"], "credit": r["credit"], "source": "ace",
                         "journal_id": r["journal_id"], "journal_number": r["journal_number"],
                         "source_type": r["source_type"], "source_id": r["source_id"], "sku": r.get("product_sku"), "jrnl": code})
    return {"key": key, "code": code, "title": title, "columns": columns, "date_from": f, "date_to": t,
            "history_until": h, "rows": rows, "truncated": len(rows) >= limit,
            "total_debit": sum((money(r["debit"]) for r in rows), ZERO),
            "total_credit": sum((money(r["credit"]) for r in rows), ZERO)}


# ---------------------------------------------------------------------------
# Customer / vendor ledgers
# ---------------------------------------------------------------------------

def _ace_party_docs(conn, entity_id: str, kind: str, after: dt.date, t: dt.date, party: Optional[str]) -> List[Dict[str, Any]]:
    """ACE Books documents dated after the hand-over (anything brought forward from Sage is
    already in Sage's own ledger, so opening items are left out)."""
    p = {"e": entity_id, "a": after, "t": t, "pid": party}
    pf = " AND x.pid = %(pid)s" if party else ""
    if kind == "CUSTOMER":
        sql = f"""SELECT * FROM (
            SELECT i.customer_id::text AS pid, i.invoice_date AS date, i.invoice_number AS trans_no, 'SJ' AS jrnl, 'invoice' AS link,
                   i.id::text AS doc_id, i.total AS debit, 0::numeric AS credit FROM fin_sales_invoices i
            WHERE i.legal_entity_id=%(e)s AND i.status <> 'DRAFT' AND NOT i.is_opening
            UNION ALL SELECT i.customer_id::text, i.voided_at::date, i.invoice_number, 'SJ', 'invoice', i.id::text, 0, i.total
            FROM fin_sales_invoices i WHERE i.legal_entity_id=%(e)s AND i.status='VOID' AND i.journal_id IS NOT NULL AND NOT i.is_opening
            UNION ALL SELECT r.customer_id::text, r.receipt_date, COALESCE(r.reference, r.receipt_number), 'CRJ', 'receipt', r.id::text,
                   0, r.amount + r.wht_amount FROM fin_customer_receipts r WHERE r.legal_entity_id=%(e)s
            UNION ALL SELECT r.customer_id::text, r.receipt_date, COALESCE(r.reference, r.receipt_number), 'CRJ', 'receipt', r.id::text,
                   r.amount + r.wht_amount, 0 FROM fin_customer_receipts r WHERE r.legal_entity_id=%(e)s AND r.status='VOID'
            UNION ALL SELECT n.customer_id::text, n.note_date, n.credit_note_number, 'SJ', 'creditnote', n.id::text, 0, n.total
            FROM fin_credit_notes n WHERE n.legal_entity_id=%(e)s AND n.journal_id IS NOT NULL
        ) x WHERE x.date > %(a)s AND x.date <= %(t)s {pf} ORDER BY x.date, x.trans_no"""
    else:
        sql = f"""SELECT * FROM (
            SELECT b.supplier_id::text AS pid, b.bill_date AS date, COALESCE(b.supplier_invoice_number, b.bill_number) AS trans_no,
                   'PJ' AS jrnl, 'bill' AS link, b.id::text AS doc_id, 0::numeric AS debit, b.total AS credit
            FROM fin_supplier_bills b WHERE b.legal_entity_id=%(e)s AND NOT b.is_opening
            UNION ALL SELECT b.supplier_id::text, b.bill_date, COALESCE(b.supplier_invoice_number, b.bill_number), 'PJ', 'bill', b.id::text,
                   b.total, 0 FROM fin_supplier_bills b WHERE b.legal_entity_id=%(e)s AND b.status='VOID' AND b.journal_id IS NOT NULL
                   AND NOT b.is_opening
            UNION ALL SELECT p.supplier_id::text, p.payment_date, COALESCE(p.reference, p.payment_number), 'CDJ', 'payment', p.id::text,
                   p.amount + p.wht_amount, 0 FROM fin_supplier_payments p WHERE p.legal_entity_id=%(e)s
            UNION ALL SELECT p.supplier_id::text, p.payment_date, COALESCE(p.reference, p.payment_number), 'CDJ', 'payment', p.id::text,
                   0, p.amount + p.wht_amount FROM fin_supplier_payments p WHERE p.legal_entity_id=%(e)s AND p.status='VOID'
            UNION ALL SELECT d.supplier_id::text, d.note_date, d.debit_note_number, 'PJ', 'debitnote', d.id::text, d.total, 0
            FROM fin_debit_notes d WHERE d.legal_entity_id=%(e)s AND d.journal_id IS NOT NULL
        ) x WHERE x.date > %(a)s AND x.date <= %(t)s {pf} ORDER BY x.date, x.trans_no"""
    return q(conn, sql, p)


def party_ledger(conn, entity_id: str, kind: str, f: dt.date, t: dt.date, party_id: Optional[str] = None,
                 search: Optional[str] = None, only_activity: bool = False) -> Dict[str, Any]:
    """Sage 'Customer Ledgers' / 'Vendor Ledgers': per party a Balance Fwd at the start of the
    range, then every transaction (Date, Trans No, Type, Debit, Credit, Balance)."""
    kind = kind.upper()
    vendor = kind == "VENDOR"
    idcol = "supplier_id" if vendor else "customer_id"
    h = history_until(conn, entity_id)
    if vendor:
        parties = {r["id"]: r for r in q(conn, "SELECT id::text AS id, name, external_vendor_id AS code FROM suppliers")}
    else:
        parties = {r["id"]: r for r in q(conn, "SELECT id::text AS id, name, customer_code AS code FROM customers")}
    pf = f" AND {idcol}::text = %s" if party_id else ""
    pp = [str(party_id)] if party_id else []
    sign = (lambda d, c: c - d) if vendor else (lambda d, c: d - c)
    unmatched: Dict[str, Dict[str, Any]] = {}

    def key_of(r):
        if r.get("pid"):
            return r["pid"]
        k = f"sage:{r['party_code']}"
        unmatched.setdefault(k, {"name": r.get("party_name") or r["party_code"], "code": r["party_code"]})
        return k

    # Balance brought forward: Sage's running balance on each party's last row before the range
    # (capped at the hand-over), then ACE Books documents between the hand-over and the range.
    opening: Dict[str, Decimal] = {}
    if h:
        cut = min(f - ONE, h)
        for r in q(conn, f"""SELECT DISTINCT ON (party_code) party_code, party_name, {idcol}::text AS pid, balance
                             FROM fin_sage_party_ledger WHERE legal_entity_id=%s AND party_kind=%s AND txn_date <= %s {pf}
                             ORDER BY party_code, txn_date DESC, seq DESC""", [entity_id, kind, cut] + pp):
            k = key_of(r)
            opening[k] = opening.get(k, ZERO) + money(r["balance"])
    if not h or f - ONE > h:
        for d in _ace_party_docs(conn, entity_id, kind, h or dt.date(1900, 1, 1), f - ONE, str(party_id) if party_id else None):
            opening[d["pid"]] = opening.get(d["pid"], ZERO) + sign(money(d["debit"]), money(d["credit"]))
    groups: Dict[str, List[Dict[str, Any]]] = {}
    if h and f <= h:
        for r in q(conn, f"""SELECT party_code, party_name, {idcol}::text AS pid, txn_date, trans_no, jrnl, paid, debit, credit, balance
                             FROM fin_sage_party_ledger WHERE legal_entity_id=%s AND party_kind=%s
                             AND txn_date BETWEEN %s AND %s AND row_kind='TXN' {pf}
                             ORDER BY party_code, txn_date, seq""", [entity_id, kind, f, min(t, h)] + pp):
            groups.setdefault(key_of(r), []).append({
                "date": r["txn_date"], "trans_no": r["trans_no"], "type": r["jrnl"], "paid": r["paid"], "debit": r["debit"],
                "credit": r["credit"], "sage_balance": r["balance"], "source": "sage"})
    a_after = max(h, f - ONE) if h else f - ONE
    for d in _ace_party_docs(conn, entity_id, kind, a_after, t, str(party_id) if party_id else None):
        groups.setdefault(d["pid"], []).append({"date": d["date"], "trans_no": d["trans_no"], "type": d["jrnl"],
                                                "debit": d["debit"], "credit": d["credit"], "source": "ace",
                                                "link": d["link"], "doc_id": d["doc_id"]})
    keys = set(groups) | ({k for k, v in opening.items() if v != 0} if not only_activity else set())
    s = (search or "").strip().lower()

    def label(k):
        p = parties.get(k) or unmatched.get(k) or {}
        return p.get("name") or k, p.get("code")

    out_rows: List[Dict[str, Any]] = []
    tot_d = tot_c = ZERO
    for key in sorted(keys, key=lambda k: (label(k)[0] or "").lower()):
        name, code = label(key)
        rows = sorted(groups.get(key, []), key=lambda r: (r["date"], 0 if r["source"] == "sage" else 1))
        if s and s not in f"{name} {code or ''}".lower() and not any(s in str(r.get("trans_no") or "").lower() for r in rows):
            continue
        pid = None if key.startswith("sage:") else key
        bal = opening.get(key, ZERO)
        out_rows.append({"party_id": pid, "party": name, "party_code": code, "date": f, "trans_no": "Balance Fwd",
                         "type": "", "debit": None, "credit": None, "balance": bal, "row_kind": "BALFWD"})
        for r in rows:
            # Sage's own running balance where Sage gave one; ACE Books documents continue from it.
            if r.get("sage_balance") is not None:
                bal = money(r["sage_balance"])
            else:
                bal = bal + sign(money(r["debit"]), money(r["credit"]))
            tot_d += money(r["debit"])
            tot_c += money(r["credit"])
            out_rows.append({"party_id": pid, "party": name, "party_code": code, **r, "balance": bal, "row_kind": "TXN"})
    cols = ([_c("party_code", "Vendor ID"), _c("party", "Vendor"), _c("date", "Date", "date"), _c("trans_no", "Trans No"),
             _c("type", "Type"), _c("paid", "Paid"), _c("debit", "Debit Amt", "money"), _c("credit", "Credit Amt", "money"),
             _c("balance", "Balance", "money")] if vendor else
            [_c("party_code", "Customer ID"), _c("party", "Customer"), _c("date", "Date", "date"), _c("trans_no", "Trans No"),
             _c("type", "Type"), _c("debit", "Debit Amt", "money"), _c("credit", "Credit Amt", "money"),
             _c("balance", "Balance", "money")])
    return {"kind": kind, "date_from": f, "date_to": t, "history_until": h, "rows": out_rows, "columns": cols,
            "total_debit": tot_d, "total_credit": tot_c}


# ---------------------------------------------------------------------------
# Lineage reads: a Sage receipt, an invoice's payments, a Sage invoice in full
# ---------------------------------------------------------------------------

def _receipt_groups(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Cash Receipts Journal lines for one date + reference, split into receipts: each is its
    invoice credit lines followed by the bank / cash debit line naming who paid."""
    groups, cur = [], []
    for r in rows:
        cur.append(r)
        if money(r["debit"]) > 0:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _crj(conn, entity_id: str, date: dt.date, reference: Optional[str]) -> List[Dict[str, Any]]:
    return q(conn, """SELECT account_code, description, debit, credit, seq FROM fin_sage_journal_lines
                      WHERE legal_entity_id=%s AND kind='CRJ' AND txn_date=%s AND COALESCE(reference,'')=COALESCE(%s,'')
                      ORDER BY seq""", (entity_id, date, reference))


def invoice_payments(conn, entity_id: str, invoice_number: str) -> List[Dict[str, Any]]:
    """Every receipt Sage applied to an invoice (the Cash Receipts Journal 'Invoice: N' lines)."""
    names = {c: a["name"] for c, a in accounts(conn, entity_id).items()}
    out = []
    for hit in q(conn, """SELECT txn_date, reference, credit - debit AS amount, seq FROM fin_sage_journal_lines
                          WHERE legal_entity_id=%s AND kind='CRJ' AND description=%s ORDER BY txn_date, seq""",
                 (entity_id, f"Invoice: {invoice_number}")):
        grp = next((g for g in _receipt_groups(_crj(conn, entity_id, hit["txn_date"], hit["reference"]))
                    if any(x["seq"] == hit["seq"] for x in g)), [])
        bank = next((x for x in grp if money(x["debit"]) > 0), None)
        out.append({"date": hit["txn_date"], "reference": hit["reference"], "amount": money(hit["amount"]),
                    "deposited_to": bank["account_code"] if bank else None,
                    "deposited_to_name": names.get(bank["account_code"]) if bank else None,
                    "received_from": bank["description"] if bank else None,
                    "receipt_total": money(bank["debit"]) if bank else None,
                    "with_invoices": [x["description"].removeprefix("Invoice: ") for x in grp
                                      if x["seq"] != hit["seq"] and money(x["credit"]) > 0 and (x["description"] or "").startswith("Invoice:")]})
    # credit memos / returns Sage raised against it ("RIN:INVOICE:N", "RIN INV N", ...)
    credits = q(conn, """SELECT txn_date, reference, SUM(credit - debit) AS amount FROM fin_sage_journal_lines
                         WHERE legal_entity_id=%s AND kind='SJ' AND account_code IN
                               (SELECT a.code FROM fin_account_mappings m JOIN fin_accounts a ON a.id=m.account_id
                                WHERE m.legal_entity_id=%s AND m.mapping_key='AR_CONTROL')
                           AND reference ~* ('^RIN.*\\m' || %s || '\\M')
                         GROUP BY txn_date, reference ORDER BY txn_date""", (entity_id, entity_id, invoice_number))
    for c in credits:
        out.append({"date": c["txn_date"], "reference": c["reference"], "amount": money(c["amount"]), "kind": "credit memo"})
    return out


def sage_receipt(conn, entity_id: str, date: dt.date, reference: Optional[str], customer: Optional[str] = None) -> Dict[str, Any]:
    names = {c: a["name"] for c, a in accounts(conn, entity_id).items()}
    groups = _receipt_groups(_crj(conn, entity_id, date, reference))
    if customer:
        c = customer.lower()
        mine = [g for g in groups if any(money(x["debit"]) > 0 and c[:12] in str(x["description"] or "").lower() for x in g)]
        groups = mine or groups
    out = []
    for g in groups:
        bank = next((x for x in g if money(x["debit"]) > 0), None)
        out.append({"received_from": bank["description"] if bank else None,
                    "deposited_to": bank["account_code"] if bank else None,
                    "deposited_to_name": names.get(bank["account_code"]) if bank else None,
                    "amount": money(bank["debit"]) if bank else sum((money(x["credit"]) for x in g), ZERO),
                    "applied": [{"description": x["description"], "account": x["account_code"],
                                 "amount": money(x["credit"]) - money(x["debit"]),
                                 "invoice_number": (x["description"] or "")[len("Invoice: "):].strip()
                                 if (x["description"] or "").startswith("Invoice:") else None}
                                for x in g if x is not bank]})
    return {"date": date, "reference": reference, "receipts": out}


def sage_invoice(conn, entity_id: str, number: str) -> Dict[str, Any]:
    """A Sage invoice in full: who, when, what was sold (qty, unit price, amount, the lot and its
    expiry), cost, the invoice total from the Sales Journal, payments and credits against it."""
    lines = q(conn, """SELECT s.line_no, s.invoice_date, s.description, s.sku, s.account_code, s.quantity, s.amount, s.cost,
                              s.customer_id, COALESCE(c.name, s.customer_name) AS customer, c.customer_code,
                              p.name AS product_name, p.lot_expiry,
                              CASE WHEN s.quantity IS NOT NULL AND s.quantity <> 0 THEN round(s.amount / s.quantity, 2) END AS unit_price,
                              b.batch_number, b.manufacture_date, b.expiry_date AS batch_expiry
                       FROM fin_sage_sales_lines s LEFT JOIN customers c ON c.id=s.customer_id
                       LEFT JOIN fin_products p ON p.legal_entity_id=s.legal_entity_id AND p.sku=s.sku
                       LEFT JOIN LATERAL (SELECT batch_number, manufacture_date, expiry_date FROM fin_batches b
                                          WHERE b.legal_entity_id=s.legal_entity_id AND b.sku=s.sku ORDER BY b.created_at LIMIT 1) b ON TRUE
                       WHERE s.legal_entity_id=%s AND s.invoice_number=%s ORDER BY s.invoice_date, s.line_no""", (entity_id, number))
    ar = q1(conn, """SELECT txn_date, SUM(debit - credit) AS total, MAX(description) AS customer FROM fin_sage_journal_lines
                     WHERE legal_entity_id=%s AND kind='SJ' AND reference=%s AND account_code IN
                           (SELECT a.code FROM fin_account_mappings m JOIN fin_accounts a ON a.id=m.account_id
                            WHERE m.legal_entity_id=%s AND m.mapping_key='AR_CONTROL') GROUP BY txn_date ORDER BY txn_date LIMIT 1""",
             (entity_id, number, entity_id))
    journal = q(conn, """SELECT account_code, description, debit, credit FROM fin_sage_journal_lines
                         WHERE legal_entity_id=%s AND kind='SJ' AND reference=%s ORDER BY txn_date, seq""", (entity_id, number))
    payments = invoice_payments(conn, entity_id, number)
    total = money(ar["total"]) if ar else sum((money(l["amount"]) for l in lines), ZERO)
    paid = sum((money(p["amount"]) for p in payments), ZERO)
    ace = q1(conn, """SELECT id, total, amount_settled, status FROM fin_sales_invoices WHERE legal_entity_id=%s
                      AND invoice_number=%s""", (entity_id, number))
    for l in lines:
        l["expiry_date"] = l.pop("batch_expiry") or l.get("lot_expiry")
    return {"invoice_number": number, "lines": lines, "journal": journal,
            "invoice_date": (lines[0]["invoice_date"] if lines else (ar["txn_date"] if ar else None)),
            "customer_id": lines[0]["customer_id"] if lines else None,
            "customer_name": (lines[0]["customer"] if lines else (ar["customer"] if ar else None)),
            "customer_code": lines[0]["customer_code"] if lines else None,
            "total": total, "cost": sum((money(l["cost"]) for l in lines if l["cost"] is not None), ZERO),
            "payments": payments, "paid": paid, "balance": total - paid if not ace else money(ace["total"]) - money(ace["amount_settled"]),
            "ace_invoice_id": str(ace["id"]) if ace else None}


def sage_bill(conn, entity_id: str, number: str, supplier_id: Optional[str] = None) -> Dict[str, Any]:
    """A supplier invoice from the Sage Purchase Journal, with the payments Sage made against it."""
    lines = q(conn, """SELECT p.line_no, p.bill_date, p.description, p.sku, p.account_code, p.quantity, p.amount,
                              CASE WHEN p.quantity IS NOT NULL AND p.quantity <> 0 THEN round(p.amount / p.quantity, 2) END AS unit_cost,
                              p.supplier_id::text AS supplier_id, COALESCE(s.name, p.supplier_name) AS supplier
                       FROM fin_sage_purchase_lines p LEFT JOIN suppliers s ON s.id=p.supplier_id
                       WHERE p.legal_entity_id=%s AND p.bill_number=%s AND (%s::uuid IS NULL OR p.supplier_id=%s::uuid)
                       ORDER BY p.bill_date, p.line_no""", (entity_id, number, supplier_id, supplier_id))
    payments = q(conn, """SELECT txn_date AS date, reference, debit - credit AS amount FROM fin_sage_journal_lines
                          WHERE legal_entity_id=%s AND kind='CDJ' AND description=%s ORDER BY txn_date, seq""",
                 (entity_id, f"Invoice: {number}"))
    total = sum((money(l["amount"]) for l in lines), ZERO)
    return {"bill_number": number, "lines": lines, "payments": payments,
            "bill_date": lines[0]["bill_date"] if lines else None,
            "supplier_id": lines[0]["supplier_id"] if lines else None,
            "supplier_name": lines[0]["supplier"] if lines else None,
            "total": total, "paid": sum((money(p["amount"]) for p in payments), ZERO)}
