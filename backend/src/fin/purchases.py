"""Purchases & Accounts Payable.

The client's Sage practice posts a supplier invoice straight against
inventory (Purchases Journal: DR item inventory / CR AP), so a bill with
stock lines *is* the goods receipt: it creates the batch (with expiry), the
FIFO cost layer and the journal in one step. PO / GRN / three-way match are a
research gate (R4) and can be layered on later without changing this.

    Bill:     DR Inventory (stock) / DR Expense / DR Fixed asset   CR AP control
    Payment:  DR AP control  amount+wht     CR Bank amount, CR WHT payable wht
    Debit note (return outward): DR AP control / CR Inventory at the cost received
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2

from src.fin import audit, inventory, posting, rules
from src.fin.db import ZERO, ex, money, q, q1, qty
from src.fin.errors import FinError, invalid, not_found
from src.fin.numbering import next_number
from src.fin.sales import bank_account, duplicate_reference


def supplier(conn, supplier_id: Any) -> Dict[str, Any]:
    s = q1(conn, "SELECT id, name, external_vendor_id AS supplier_code, payment_terms, phone, contact_email FROM suppliers WHERE id=%s",
           (str(supplier_id),))
    if not s:
        raise not_found("Supplier", supplier_id)
    return s


def _terms_days(text: Optional[str]) -> int:
    import re
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else 30


def create_bill(conn, ctx, data: Dict[str, Any], *, is_opening: bool = False) -> Dict[str, Any]:
    ctx.require("payables.bill.create")
    s = supplier(conn, data["supplier_id"])
    inv_no = str(data.get("supplier_invoice_number") or "").strip()
    if not inv_no:
        raise invalid("Enter the supplier's invoice number")
    lines = data.get("lines") or []
    if not lines and not is_opening:
        raise invalid("A bill needs at least one line")
    bill_date = data["bill_date"]
    due = data.get("due_date") or bill_date + dt.timedelta(days=_terms_days(s["payment_terms"]))
    priced = []
    for i, l in enumerate(lines, start=1):
        t = str(l.get("line_type") or ("ITEM" if l.get("sku") else "EXPENSE")).upper()
        if t not in ("ITEM", "EXPENSE", "ASSET"):
            raise invalid(f"Line {i}: line type must be item, expense or asset")
        quantity = qty(l.get("quantity") if l.get("quantity") not in (None, "") else 1)
        unit_cost = Decimal(str(l.get("unit_cost") or 0))
        if quantity <= 0 or unit_cost < 0:
            raise invalid(f"Line {i}: quantity must be positive and cost cannot be negative")
        total = money(l["line_total"]) if l.get("line_total") not in (None, "") else money(quantity * unit_cost)
        if t == "ITEM":
            p = rules.product(conn, ctx.entity_id, str(l["sku"]).strip())
            account_id = rules.product_accounts(conn, ctx.entity_id, p["sku"])["inventory_account_id"]
            desc = l.get("description") or p["name"]
        else:
            if not l.get("account_id"):
                if t == "ASSET":
                    raise invalid(f"Line {i}: choose the fixed-asset account")
                account_id = str(rules.account(conn, ctx.entity_id, "PURCHASE_EXPENSE_DEFAULT")["id"])
            else:
                account_id = l["account_id"]
            desc = l.get("description")
        priced.append({**l, "line_no": i, "line_type": t, "quantity": quantity, "unit_cost": unit_cost,
                       "line_total": total, "account_id": account_id, "description": desc})
    subtotal = sum((p["line_total"] for p in priced), ZERO)
    tax = money(data.get("tax_total"))
    total = money(data["total"]) if is_opening else subtotal + tax
    if total <= 0:
        raise invalid("Bill total must be positive")
    if tax > 0:
        rules.account(conn, ctx.entity_id, "INPUT_TAX")
    number = next_number(conn, ctx.entity_id, "BILL")
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT bill_ins")
        b = q1(conn, """INSERT INTO fin_supplier_bills (legal_entity_id, bill_number, supplier_id, supplier_invoice_number,
                        bill_date, due_date, subtotal, tax_total, total, is_opening, notes, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
               (ctx.entity_id, number, s["id"], inv_no, bill_date, due, subtotal, tax, total, is_opening,
                data.get("notes"), ctx.actor_id))
        with conn.cursor() as cur:
            cur.execute("RELEASE SAVEPOINT bill_ins")
    except psycopg2.errors.UniqueViolation:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT bill_ins")
        dup = q1(conn, """SELECT bill_number FROM fin_supplier_bills WHERE legal_entity_id=%s AND supplier_id=%s
                          AND lower(regexp_replace(supplier_invoice_number,'[^[:alnum:]]','','g'))
                              = lower(regexp_replace(%s,'[^[:alnum:]]','','g'))
                          AND status<>'VOID'""", (ctx.entity_id, s["id"], inv_no))
        raise FinError("DUPLICATE_INVOICE", f"{s['name']} invoice {inv_no} is already recorded as {dup['bill_number'] if dup else 'a bill'}",
                       {"supplier": s["name"], "supplier_invoice_number": inv_no})
    if is_opening:
        audit.record(conn, ctx, "OPENING_BILL_LOADED", "supplier_bill", b["id"], ref=number, after={"total": total})
        return get_bill(conn, ctx.entity_id, b["id"])
    ap = rules.account(conn, ctx.entity_id, "AP_CONTROL")
    jl: List[Dict[str, Any]] = []
    txns = []
    for p in priced:
        txn_id = None
        batch_id = None
        if p["line_type"] == "ITEM":
            batch_id = inventory.ensure_batch(conn, ctx.entity_id, p["sku"], p.get("batch_number"),
                                              expiry_date=_d(p.get("expiry_date")), manufacture_date=_d(p.get("manufacture_date")),
                                              supplier_id=str(s["id"]))
            unit = p["line_total"] / p["quantity"]
            t = inventory.receive(conn, ctx, sku=p["sku"], quantity=p["quantity"], unit_cost=unit, txn_type="PURCHASE",
                                  txn_date=bill_date, batch_id=batch_id, source_type="SUPPLIER_BILL", source_id=b["id"],
                                  reference=number, supplier_id=str(s["id"]), total_cost=p["line_total"])
            txn_id = str(t["id"])
            txns.append(txn_id)
        jl.append({"account_id": p["account_id"], "debit": p["line_total"], "supplier_id": str(s["id"]),
                   "product_sku": p.get("sku"), "description": p["description"]})
        ex(conn, """INSERT INTO fin_supplier_bill_lines (bill_id, line_no, line_type, sku, batch_id, description, quantity,
                    unit_cost, line_total, account_id, inventory_txn_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
           (b["id"], p["line_no"], p["line_type"], p.get("sku"), batch_id, p["description"], p["quantity"], p["unit_cost"],
            p["line_total"], p["account_id"], txn_id))
    if tax > 0:
        jl.append({"account_id": rules.account(conn, ctx.entity_id, "INPUT_TAX")["id"], "debit": tax,
                   "supplier_id": str(s["id"]), "description": "Tax on purchase"})
    jl.append({"account_id": ap["id"], "credit": total, "supplier_id": str(s["id"]),
               "description": f"{s['name']} inv {inv_no}"})
    j = posting.post_system(conn, ctx, event_type="PURCHASE_INVOICE_POSTED", journal_date=bill_date, lines=jl,
                            description=f"Bill {number} - {s['name']} invoice {inv_no}", source_type="SUPPLIER_BILL",
                            source_id=b["id"], source_ref=number)
    inventory.link_journal(conn, txns, j["id"])
    ex(conn, "UPDATE fin_supplier_bills SET journal_id=%s WHERE id=%s", (j["id"], b["id"]))
    audit.record(conn, ctx, "BILL_POSTED", "supplier_bill", b["id"], ref=number,
                 metadata={"supplier": s["name"], "total": str(total), "journal": j["journal_number"]})
    return get_bill(conn, ctx.entity_id, b["id"])


def _d(v: Any) -> Optional[dt.date]:
    if not v:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def get_bill(conn, entity_id: str, bill_id: str) -> Dict[str, Any]:
    b = q1(conn, """SELECT b.*, s.name AS supplier_name, (b.total - b.amount_settled) AS balance_due, j.journal_number
                    FROM fin_supplier_bills b LEFT JOIN suppliers s ON s.id=b.supplier_id
                    LEFT JOIN fin_journals j ON j.id=b.journal_id WHERE b.id=%s AND b.legal_entity_id=%s""",
           (bill_id, entity_id))
    if not b:
        raise not_found("Bill", bill_id)
    b["lines"] = q(conn, """SELECT l.*, a.code AS account_code, a.name AS account_name, bt.batch_number, bt.expiry_date
                            FROM fin_supplier_bill_lines l LEFT JOIN fin_accounts a ON a.id=l.account_id
                            LEFT JOIN fin_batches bt ON bt.id=l.batch_id WHERE l.bill_id=%s ORDER BY l.line_no""", (bill_id,))
    b["allocations"] = q(conn, """SELECT a.*, COALESCE(p.payment_number, d.debit_note_number) AS source_number
                                  FROM fin_ap_allocations a
                                  LEFT JOIN fin_supplier_payments p ON a.source_type='PAYMENT' AND p.id=a.source_id
                                  LEFT JOIN fin_debit_notes d ON a.source_type='DEBIT_NOTE' AND d.id=a.source_id
                                  WHERE a.bill_id=%s ORDER BY a.created_at""", (bill_id,))
    if b["is_opening"]:
        # Line detail of a migrated bill comes from the Sage Purchase Journal (display only).
        from src.fin import sage_history
        b["history_lines"] = sage_history.bill_lines(conn, entity_id, b["supplier_invoice_number"], str(b["supplier_id"]))
    return b


def list_bills(conn, entity_id: str, *, supplier_id: Any = None, search: Optional[str] = None, open_only: bool = False,
               date_from=None, date_to=None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = ["b.legal_entity_id=%s"], [entity_id]
    if supplier_id:
        where.append("b.supplier_id=%s")
        params.append(str(supplier_id))
    if open_only:
        where.append("b.status IN ('POSTED','PARTIALLY_PAID')")
    if date_from:
        where.append("b.bill_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("b.bill_date <= %s")
        params.append(date_to)
    if search:
        where.append("(b.bill_number ILIKE %s OR s.name ILIKE %s OR b.supplier_invoice_number ILIKE %s)")
        params += [f"%{search}%"] * 3
    w = " AND ".join(where)
    total = q1(conn, f"SELECT COUNT(*) n FROM fin_supplier_bills b LEFT JOIN suppliers s ON s.id=b.supplier_id WHERE {w}", params)["n"]
    rows = q(conn, f"""SELECT b.id, b.bill_number, b.supplier_invoice_number, b.bill_date, b.due_date, b.supplier_id,
                              s.name AS supplier_name, b.total, b.amount_settled, (b.total - b.amount_settled) AS balance_due,
                              b.status, b.is_opening
                       FROM fin_supplier_bills b LEFT JOIN suppliers s ON s.id=b.supplier_id
                       WHERE {w} ORDER BY b.bill_date DESC, b.bill_number DESC LIMIT %s OFFSET %s""",
             params + [limit, offset])
    return {"items": rows, "total": total}


def void_bill(conn, ctx, bill_id: str, reason: str) -> Dict[str, Any]:
    ctx.require("payables.bill.void")
    b = q1(conn, "SELECT * FROM fin_supplier_bills WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (bill_id, ctx.entity_id))
    if not b:
        raise not_found("Bill", bill_id)
    if b["status"] == "VOID":
        raise FinError("INVALID_STATE_TRANSITION", "Bill is already void")
    if not (reason or "").strip():
        raise invalid("A reason is required to void a bill")
    if money(b["amount_settled"]) > 0:
        raise FinError("INVALID_STATE_TRANSITION", "Payments are applied to this bill; void those first or raise a debit note")
    if b["is_opening"]:
        raise FinError("INVALID_STATE_TRANSITION", "Opening-balance bills are corrected with a debit note")
    # Stock received on this bill must still be on hand to take it back out.
    for l in q(conn, "SELECT * FROM fin_supplier_bill_lines WHERE bill_id=%s AND inventory_txn_id IS NOT NULL", (bill_id,)):
        layer = q1(conn, "SELECT qty_in, qty_remaining FROM fin_cost_layers WHERE inventory_txn_id=%s", (l["inventory_txn_id"],))
        if layer and layer["qty_remaining"] < layer["qty_in"]:
            raise FinError("INVALID_STATE_TRANSITION",
                           f"Some of {l['sku']} from this bill has already been sold; use a debit note for what is left")
    rev = posting.reverse(conn, ctx, str(b["journal_id"]), reversal_date=b["bill_date"],
                          reason=f"Void bill {b['bill_number']}: {reason}", allow_system=True)
    for l in q(conn, "SELECT * FROM fin_supplier_bill_lines WHERE bill_id=%s AND inventory_txn_id IS NOT NULL", (bill_id,)):
        t = inventory.issue(conn, ctx, sku=l["sku"], quantity=l["quantity"], txn_type="RETURN_OUT", txn_date=b["bill_date"],
                            batch_id=str(l["batch_id"]) if l["batch_id"] else None, source_type="SUPPLIER_BILL_VOID",
                            source_id=bill_id, reference=b["bill_number"], supplier_id=str(b["supplier_id"]), reason="Bill voided")
        inventory.link_journal(conn, [str(t["id"])], rev["id"])
    ex(conn, "UPDATE fin_supplier_bills SET status='VOID', void_journal_id=%s, void_reason=%s WHERE id=%s",
       (rev["id"], reason, bill_id))
    audit.record(conn, ctx, "BILL_VOIDED", "supplier_bill", bill_id, ref=b["bill_number"], reason=reason)
    return get_bill(conn, ctx.entity_id, bill_id)


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

def _refresh_bill_status(conn, bill_id: str) -> None:
    ex(conn, """UPDATE fin_supplier_bills SET status = CASE WHEN amount_settled >= total THEN 'PAID'
                    WHEN amount_settled > 0 THEN 'PARTIALLY_PAID' ELSE 'POSTED' END
                WHERE id=%s AND status <> 'VOID'""", (bill_id,))


def _apply(conn, ctx, *, source_type: str, source_id: str, supplier_id: str, allocations: List[Dict[str, Any]],
           available: Decimal, on: dt.date) -> Decimal:
    used = ZERO
    for a in allocations or []:
        amt = money(a.get("amount"))
        if amt <= 0:
            continue
        b = q1(conn, "SELECT * FROM fin_supplier_bills WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (a["bill_id"], ctx.entity_id))
        if not b:
            raise not_found("Bill", a["bill_id"])
        if str(b["supplier_id"]) != str(supplier_id):
            raise invalid(f"Bill {b['bill_number']} belongs to another supplier")
        if b["status"] not in ("POSTED", "PARTIALLY_PAID"):
            raise FinError("INVALID_STATE_TRANSITION", f"Bill {b['bill_number']} is {b['status'].lower()}")
        open_amt = money(b["total"]) - money(b["amount_settled"])
        if amt > open_amt:
            raise FinError("OVER_ALLOCATION", f"Only ₦{open_amt:,.2f} is outstanding on {b['bill_number']}")
        if used + amt > available:
            raise FinError("OVER_ALLOCATION", f"Allocations exceed the ₦{available:,.2f} available")
        ex(conn, """INSERT INTO fin_ap_allocations (legal_entity_id, source_type, source_id, bill_id, amount, allocation_date,
                    created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""", (ctx.entity_id, source_type, source_id, b["id"], amt, on, ctx.actor_id))
        ex(conn, "UPDATE fin_supplier_bills SET amount_settled = amount_settled + %s WHERE id=%s", (amt, b["id"]))
        _refresh_bill_status(conn, str(b["id"]))
        used += amt
    return used


def _unapply(conn, source_type: str, source_id: str) -> None:
    for a in q(conn, "SELECT * FROM fin_ap_allocations WHERE source_type=%s AND source_id=%s AND NOT reversed", (source_type, source_id)):
        ex(conn, "UPDATE fin_ap_allocations SET reversed=TRUE WHERE id=%s", (a["id"],))
        ex(conn, "UPDATE fin_supplier_bills SET amount_settled = amount_settled - %s WHERE id=%s", (a["amount"], a["bill_id"]))
        _refresh_bill_status(conn, str(a["bill_id"]))


# ---------------------------------------------------------------------------
# Supplier payments
# ---------------------------------------------------------------------------

def create_payment(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("payables.payment.create")
    s = supplier(conn, data["supplier_id"])
    method = str(data.get("method") or "TRANSFER").upper()
    if method not in ("CASH", "TRANSFER", "CHEQUE", "OTHER"):
        raise invalid("Payment method must be cash, transfer, cheque or other")
    bank = bank_account(conn, ctx.entity_id, data["bank_account_id"])
    amount, wht = money(data.get("amount")), money(data.get("wht_amount"))
    if amount <= 0:
        raise invalid("Payment amount must be positive")
    reference = (data.get("reference") or "").strip() or None
    dup = duplicate_reference(conn, ctx.entity_id, "fin_supplier_payments", reference)
    if dup and not data.get("confirm_duplicate"):
        raise FinError("DUPLICATE_REFERENCE", f"Cheque/reference {reference} was already used on {dup['payment_number']}",
                       {"existing": dup["payment_number"], "reference": reference})
    number = next_number(conn, ctx.entity_id, "SUPPLIER_PAYMENT")
    p = q1(conn, """INSERT INTO fin_supplier_payments (legal_entity_id, payment_number, supplier_id, payment_date, method,
                    bank_account_id, amount, wht_amount, reference, notes, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
           (ctx.entity_id, number, s["id"], data["payment_date"], method, bank["id"], amount, wht, reference,
            data.get("notes"), ctx.actor_id))
    if dup:
        ex(conn, """INSERT INTO fin_validation_events (legal_entity_id, entity_type, entity_id, entity_ref, check_code,
                    severity, message, status, created_by) VALUES (%s,'supplier_payment',%s,%s,'DUPLICATE_REFERENCE',
                    'WARNING',%s,'ACCEPTED',%s)""",
           (ctx.entity_id, p["id"], number, f"Reference {reference} also used on {dup['payment_number']}", ctx.actor_id))
    ap = rules.account(conn, ctx.entity_id, "AP_CONTROL")
    jl = [{"account_id": ap["id"], "debit": amount + wht, "supplier_id": str(s["id"]), "description": f"Payment {number}"},
          {"account_id": bank["gl_account_id"], "credit": amount, "supplier_id": str(s["id"]),
           "description": f"{s['name']} {reference or ''}".strip()}]
    if wht > 0:
        jl.append({"account_id": rules.account(conn, ctx.entity_id, "WHT_PAYABLE")["id"], "credit": wht,
                   "supplier_id": str(s["id"]), "description": f"WHT withheld from {s['name']}"})
    j = posting.post_system(conn, ctx, event_type="SUPPLIER_PAYMENT_POSTED", journal_date=data["payment_date"], lines=jl,
                            description=f"Payment {number} to {s['name']}", source_type="SUPPLIER_PAYMENT",
                            source_id=p["id"], source_ref=number)
    used = _apply(conn, ctx, source_type="PAYMENT", source_id=str(p["id"]), supplier_id=str(s["id"]),
                  allocations=data.get("allocations") or [], available=amount + wht, on=data["payment_date"])
    ex(conn, "UPDATE fin_supplier_payments SET journal_id=%s, amount_allocated=%s WHERE id=%s", (j["id"], used, p["id"]))
    audit.record(conn, ctx, "SUPPLIER_PAYMENT_POSTED", "supplier_payment", p["id"], ref=number,
                 metadata={"amount": str(amount), "wht": str(wht), "allocated": str(used), "journal": j["journal_number"]})
    return get_payment(conn, ctx.entity_id, p["id"])


def get_payment(conn, entity_id: str, payment_id: str) -> Dict[str, Any]:
    p = q1(conn, """SELECT p.*, s.name AS supplier_name, b.name AS bank_account_name, j.journal_number,
                           (p.amount + p.wht_amount - p.amount_allocated) AS unapplied
                    FROM fin_supplier_payments p LEFT JOIN suppliers s ON s.id=p.supplier_id
                    LEFT JOIN fin_bank_accounts b ON b.id=p.bank_account_id LEFT JOIN fin_journals j ON j.id=p.journal_id
                    WHERE p.id=%s AND p.legal_entity_id=%s""", (payment_id, entity_id))
    if not p:
        raise not_found("Payment", payment_id)
    p["allocations"] = q(conn, """SELECT a.*, b.bill_number, b.supplier_invoice_number FROM fin_ap_allocations a
                                  JOIN fin_supplier_bills b ON b.id=a.bill_id WHERE a.source_type='PAYMENT' AND a.source_id=%s
                                  ORDER BY a.created_at""", (payment_id,))
    return p


def allocate_payment(conn, ctx, payment_id: str, allocations: List[Dict[str, Any]]) -> Dict[str, Any]:
    ctx.require("payables.payment.create")
    p = q1(conn, "SELECT * FROM fin_supplier_payments WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (payment_id, ctx.entity_id))
    if not p or p["status"] != "POSTED":
        raise not_found("Payment", payment_id)
    avail = money(p["amount"]) + money(p["wht_amount"]) - money(p["amount_allocated"])
    used = _apply(conn, ctx, source_type="PAYMENT", source_id=payment_id, supplier_id=str(p["supplier_id"]),
                  allocations=allocations, available=avail, on=dt.date.today())
    ex(conn, "UPDATE fin_supplier_payments SET amount_allocated = amount_allocated + %s WHERE id=%s", (used, payment_id))
    audit.record(conn, ctx, "SUPPLIER_PAYMENT_ALLOCATED", "supplier_payment", payment_id, ref=p["payment_number"],
                 metadata={"allocated": str(used)})
    return get_payment(conn, ctx.entity_id, payment_id)


def void_payment(conn, ctx, payment_id: str, reason: str) -> Dict[str, Any]:
    ctx.require("payables.payment.void")
    p = q1(conn, "SELECT * FROM fin_supplier_payments WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (payment_id, ctx.entity_id))
    if not p:
        raise not_found("Payment", payment_id)
    if p["status"] != "POSTED":
        raise FinError("INVALID_STATE_TRANSITION", "Payment is already void")
    if not (reason or "").strip():
        raise invalid("A reason is required to void a payment")
    rev = posting.reverse(conn, ctx, str(p["journal_id"]), reversal_date=p["payment_date"],
                          reason=f"Void payment {p['payment_number']}: {reason}", allow_system=True)
    _unapply(conn, "PAYMENT", payment_id)
    ex(conn, "UPDATE fin_supplier_payments SET status='VOID', void_journal_id=%s, void_reason=%s, amount_allocated=0 WHERE id=%s",
       (rev["id"], reason, payment_id))
    audit.record(conn, ctx, "SUPPLIER_PAYMENT_VOIDED", "supplier_payment", payment_id, ref=p["payment_number"], reason=reason)
    return get_payment(conn, ctx.entity_id, payment_id)


def list_payments(conn, entity_id: str, *, supplier_id: Any = None, search: Optional[str] = None,
                  date_from=None, date_to=None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = ["p.legal_entity_id=%s"], [entity_id]
    if supplier_id:
        where.append("p.supplier_id=%s")
        params.append(str(supplier_id))
    if date_from:
        where.append("p.payment_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("p.payment_date <= %s")
        params.append(date_to)
    if search:
        where.append("(p.payment_number ILIKE %s OR s.name ILIKE %s OR p.reference ILIKE %s)")
        params += [f"%{search}%"] * 3
    w = " AND ".join(where)
    total = q1(conn, f"SELECT COUNT(*) n FROM fin_supplier_payments p LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE {w}", params)["n"]
    rows = q(conn, f"""SELECT p.id, p.payment_number, p.payment_date, p.supplier_id, s.name AS supplier_name, p.method,
                              b.name AS bank_account_name, p.amount, p.wht_amount, p.amount_allocated,
                              (p.amount + p.wht_amount - p.amount_allocated) AS unapplied, p.reference, p.status
                       FROM fin_supplier_payments p LEFT JOIN suppliers s ON s.id=p.supplier_id
                       LEFT JOIN fin_bank_accounts b ON b.id=p.bank_account_id
                       WHERE {w} ORDER BY p.payment_date DESC, p.payment_number DESC LIMIT %s OFFSET %s""",
             params + [limit, offset])
    return {"items": rows, "total": total}


# ---------------------------------------------------------------------------
# Debit notes / returns outward
# ---------------------------------------------------------------------------

def create_debit_note(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("payables.debit_note.create")
    s = supplier(conn, data["supplier_id"])
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise invalid("A debit note needs a reason")
    bill = None
    if data.get("bill_id"):
        bill = q1(conn, "SELECT * FROM fin_supplier_bills WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (data["bill_id"], ctx.entity_id))
        if not bill or str(bill["supplier_id"]) != str(s["id"]):
            raise invalid("The referenced bill was not found for this supplier")
    sage_no = (data.get("sage_bill_number") or "").strip() or None
    if not bill and sage_no:
        # a Sage supplier invoice still open in ACE Books (brought forward) is reduced directly
        bill = q1(conn, """SELECT * FROM fin_supplier_bills WHERE legal_entity_id=%s AND supplier_id=%s
                           AND supplier_invoice_number=%s AND status <> 'VOID' LIMIT 1 FOR UPDATE""", (ctx.entity_id, s["id"], sage_no))
    on = data["note_date"]
    number = next_number(conn, ctx.entity_id, "DEBIT_NOTE")
    dn = q1(conn, """INSERT INTO fin_debit_notes (legal_entity_id, debit_note_number, supplier_id, bill_id, note_date, reason,
                     created_by, sage_bill_number) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (ctx.entity_id, number, s["id"], bill["id"] if bill else None, on, reason, ctx.actor_id,
             sage_no or (bill["supplier_invoice_number"] if bill else None)))
    ap = rules.account(conn, ctx.entity_id, "AP_CONTROL")
    jl, txns, total = [], [], ZERO
    for i, l in enumerate(data.get("lines") or [], start=1):
        t_ = str(l.get("line_type") or ("ITEM" if l.get("sku") else "EXPENSE")).upper()
        quantity = qty(l.get("quantity") or 1)
        if t_ == "ITEM":
            sku = str(l["sku"]).strip()
            batch_id = l.get("batch_id") or inventory.ensure_batch(conn, ctx.entity_id, sku, l.get("batch_number"))
            t = inventory.issue(conn, ctx, sku=sku, quantity=quantity, txn_type="RETURN_OUT", txn_date=on, batch_id=batch_id,
                                source_type="DEBIT_NOTE", source_id=dn["id"], reference=number, supplier_id=str(s["id"]),
                                reason=reason)
            # Supplier credits us at the price they charged; the stock leaves at its book cost.
            value = money(l["line_total"]) if l.get("line_total") not in (None, "") else t["cost"]
            acc = rules.product_accounts(conn, ctx.entity_id, sku)
            jl.append({"account_id": acc["inventory_account_id"], "credit": t["cost"], "product_sku": sku,
                       "supplier_id": str(s["id"]), "description": f"Returned to {s['name']}"})
            if value != t["cost"]:
                jl.append({"account_id": rules.account(conn, ctx.entity_id, "INVENTORY_ADJUSTMENT")["id"],
                           "credit" if value > t["cost"] else "debit": abs(value - t["cost"]), "product_sku": sku,
                           "description": "Difference between supplier credit and book cost"})
            txns.append(str(t["id"]))
            ex(conn, """INSERT INTO fin_debit_note_lines (debit_note_id, line_no, line_type, sku, batch_id, description, quantity,
                        unit_cost, line_total, account_id, inventory_txn_id) VALUES (%s,%s,'ITEM',%s,%s,%s,%s,%s,%s,%s,%s)""",
               (dn["id"], i, sku, batch_id, l.get("description") or sku, quantity, t["unit_cost"], value,
                acc["inventory_account_id"], t["id"]))
        else:
            if not l.get("account_id"):
                raise invalid(f"Line {i}: choose the account being credited")
            value = money(l.get("line_total"))
            jl.append({"account_id": l["account_id"], "credit": value, "supplier_id": str(s["id"]), "description": l.get("description")})
            ex(conn, """INSERT INTO fin_debit_note_lines (debit_note_id, line_no, line_type, description, quantity, line_total,
                        account_id) VALUES (%s,%s,'EXPENSE',%s,1,%s,%s)""", (dn["id"], i, l.get("description"), value, l["account_id"]))
        total += value
    if total <= 0:
        raise invalid("Debit note total must be positive")
    jl.insert(0, {"account_id": ap["id"], "debit": total, "supplier_id": str(s["id"]), "description": f"Debit note {number}"})
    j = posting.post_system(conn, ctx, event_type="SUPPLIER_RETURN_POSTED", journal_date=on, lines=jl,
                            description=f"Debit note {number} to {s['name']}: {reason}", source_type="DEBIT_NOTE",
                            source_id=dn["id"], source_ref=number)
    inventory.link_journal(conn, txns, j["id"])
    used = ZERO
    if bill and bill["status"] in ("POSTED", "PARTIALLY_PAID"):
        open_amt = money(bill["total"]) - money(bill["amount_settled"])
        used = _apply(conn, ctx, source_type="DEBIT_NOTE", source_id=str(dn["id"]), supplier_id=str(s["id"]),
                      allocations=[{"bill_id": bill["id"], "amount": min(open_amt, total)}], available=total, on=on)
    ex(conn, "UPDATE fin_debit_notes SET total=%s, amount_settled=%s, journal_id=%s WHERE id=%s", (total, used, j["id"], dn["id"]))
    audit.record(conn, ctx, "DEBIT_NOTE_POSTED", "debit_note", dn["id"], ref=number, reason=reason, metadata={"total": str(total)})
    return get_debit_note(conn, ctx.entity_id, dn["id"])


def returnable_bills(conn, entity_id: str, supplier_id: str, search: Optional[str] = None, limit: int = 40) -> List[Dict[str, Any]]:
    """A supplier's invoices - ACE Books bills and the Sage purchase history - with what was
    bought on each (item, batch, quantity, unit cost), for a return outward."""
    s = f"%{search}%" if search else None
    ace = q(conn, """SELECT b.id::text AS bill_id, b.bill_number, b.supplier_invoice_number, b.bill_date, b.total,
                            b.total - b.amount_settled AS balance, b.status, FALSE AS sage
                     FROM fin_supplier_bills b WHERE b.legal_entity_id=%s AND b.supplier_id=%s::uuid AND b.status <> 'VOID'
                       AND NOT b.is_opening AND (%s::text IS NULL OR b.supplier_invoice_number ILIKE %s OR b.bill_number ILIKE %s)
                     ORDER BY b.bill_date DESC LIMIT %s""", (entity_id, supplier_id, s, s, s, limit))
    for b in ace:
        b["lines"] = q(conn, """SELECT l.sku, l.description, l.quantity, l.unit_cost, l.batch_id::text AS return_batch_id, bt.batch_number
                                FROM fin_supplier_bill_lines l LEFT JOIN fin_batches bt ON bt.id=l.batch_id
                                WHERE l.bill_id=%s AND l.sku IS NOT NULL ORDER BY l.line_no""", (b["bill_id"],))
    sage = q(conn, """SELECT p.bill_number AS supplier_invoice_number, MIN(p.bill_date) AS bill_date, SUM(p.amount) AS total, TRUE AS sage,
                             (SELECT o.id::text FROM fin_supplier_bills o WHERE o.legal_entity_id=p.legal_entity_id AND o.is_opening
                                AND o.supplier_invoice_number=p.bill_number AND o.supplier_id=p.supplier_id LIMIT 1) AS bill_id
                      FROM fin_sage_purchase_lines p WHERE p.legal_entity_id=%s AND p.supplier_id=%s::uuid
                        AND (%s::text IS NULL OR p.bill_number ILIKE %s)
                      GROUP BY p.legal_entity_id, p.supplier_id, p.bill_number ORDER BY MIN(p.bill_date) DESC LIMIT %s""",
             (entity_id, supplier_id, s, s, limit))
    for b in sage:
        b["lines"] = q(conn, """SELECT p.sku, COALESCE(pr.name, p.description) AS description, p.quantity,
                                       CASE WHEN p.quantity <> 0 THEN round(p.amount / p.quantity, 2) END AS unit_cost,
                                       bt.id::text AS return_batch_id, bt.batch_number
                                FROM fin_sage_purchase_lines p LEFT JOIN fin_products pr ON pr.legal_entity_id=p.legal_entity_id AND pr.sku=p.sku
                                LEFT JOIN LATERAL (SELECT id, batch_number FROM fin_batches x WHERE x.legal_entity_id=p.legal_entity_id
                                                   AND x.sku=p.sku ORDER BY created_at LIMIT 1) bt ON TRUE
                                WHERE p.legal_entity_id=%s AND p.bill_number=%s AND p.supplier_id=%s::uuid AND p.sku IS NOT NULL
                                ORDER BY p.line_no""", (entity_id, b["supplier_invoice_number"], supplier_id))
    out = sorted(ace + sage, key=lambda r: r["bill_date"] or dt.date.min, reverse=True)
    return out[:limit]


def get_debit_note(conn, entity_id: str, dn_id: str) -> Dict[str, Any]:
    d = q1(conn, """SELECT d.*, s.name AS supplier_name, b.bill_number, j.journal_number FROM fin_debit_notes d
                    LEFT JOIN suppliers s ON s.id=d.supplier_id LEFT JOIN fin_supplier_bills b ON b.id=d.bill_id
                    LEFT JOIN fin_journals j ON j.id=d.journal_id WHERE d.id=%s AND d.legal_entity_id=%s""", (dn_id, entity_id))
    if not d:
        raise not_found("Debit note", dn_id)
    d["lines"] = q(conn, "SELECT * FROM fin_debit_note_lines WHERE debit_note_id=%s ORDER BY line_no", (dn_id,))
    return d


def list_debit_notes(conn, entity_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    total = q1(conn, "SELECT COUNT(*) n FROM fin_debit_notes WHERE legal_entity_id=%s", (entity_id,))["n"]
    rows = q(conn, """SELECT d.id, d.debit_note_number, d.note_date, s.name AS supplier_name, b.bill_number, d.reason,
                             d.total, d.amount_settled, d.status FROM fin_debit_notes d
                      LEFT JOIN suppliers s ON s.id=d.supplier_id LEFT JOIN fin_supplier_bills b ON b.id=d.bill_id
                      WHERE d.legal_entity_id=%s ORDER BY d.note_date DESC LIMIT %s OFFSET %s""", (entity_id, limit, offset))
    return {"items": rows, "total": total}
