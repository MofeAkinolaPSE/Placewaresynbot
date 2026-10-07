"""Sales & Accounts Receivable.

Invoice posting (one transaction):
    DR AR control                 total                (customer dimension)
    CR product revenue            gross line value
    DR Sales discount             line / invoice discounts  (own head - meeting 2)
    CR Delivery / charge income   delivery & other charges  (not product sales - meeting 2)
    CR Output tax                 only if configured (tax rules are a research gate)
    DR COGS / CR Inventory        FIFO / batch cost of goods shipped
Receipts:
    DR Bank/Cash  amount  +  DR WHT suffered  wht  /  CR AR control  amount+wht
Credit notes: the mirror, optionally bringing stock back at its original cost.
Customer balances are never stored: open items = invoice total - allocations.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, inventory, posting, rules
from src.fin.db import ZERO, ex, jsonb, money, q, q1, qty
from src.fin.errors import FinError, invalid, not_found
from src.fin.numbering import next_number

LINE_TYPES = ("ITEM", "SERVICE", "CHARGE", "DISCOUNT")
METHODS = ("CASH", "TRANSFER", "CHEQUE", "POS", "OTHER")


# ---------------------------------------------------------------------------
# Customers & exposure
# ---------------------------------------------------------------------------

def customer(conn, customer_id: Any) -> Dict[str, Any]:
    c = q1(conn, "SELECT id, name, customer_code, credit_limit, payment_terms_days, contact_details FROM customers WHERE id=%s",
           (int(customer_id),))
    if not c:
        raise not_found("Customer", customer_id)
    return c


def customer_exposure(conn, entity_id: str, customer_id: int) -> Decimal:
    """What the customer owes right now: open invoices minus unapplied credits."""
    inv = q1(conn, """SELECT COALESCE(SUM(total - amount_settled),0) v FROM fin_sales_invoices
                      WHERE legal_entity_id=%s AND customer_id=%s AND status IN ('POSTED','PARTIALLY_PAID')""",
             (entity_id, customer_id))["v"]
    rc = q1(conn, """SELECT COALESCE(SUM(amount + wht_amount - amount_allocated),0) v FROM fin_customer_receipts
                     WHERE legal_entity_id=%s AND customer_id=%s AND status='POSTED'""", (entity_id, customer_id))["v"]
    cn = q1(conn, """SELECT COALESCE(SUM(total - amount_settled),0) v FROM fin_credit_notes
                     WHERE legal_entity_id=%s AND customer_id=%s AND status='POSTED'""", (entity_id, customer_id))["v"]
    return money(inv) - money(rc) - money(cn)


def credit_check(conn, entity_id: str, customer_id: int, amount: Decimal) -> Dict[str, Any]:
    c = customer(conn, customer_id)
    limit = money(c["credit_limit"]) if c["credit_limit"] is not None else ZERO
    exposure = customer_exposure(conn, entity_id, customer_id)
    projected = exposure + amount
    return {"customer": c["name"], "credit_limit": str(limit), "current_exposure": str(exposure),
            "this_invoice": str(amount), "projected_exposure": str(projected),
            "exceeds": bool(limit > 0 and projected > limit),
            "excess": str(max(projected - limit, ZERO)) if limit > 0 else "0.00"}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def _line_account(conn, entity_id: str, l: Dict[str, Any]) -> Optional[str]:
    if l.get("account_id"):
        a = q1(conn, "SELECT id FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (l["account_id"], entity_id))
        if not a:
            raise not_found("Account", l["account_id"])
        return str(a["id"])
    t = l["line_type"]
    if t == "ITEM":
        return rules.product_accounts(conn, entity_id, l["sku"])["revenue_account_id"]
    if t == "SERVICE":
        return str(rules.account(conn, entity_id, "SERVICE_INCOME")["id"])
    if t == "CHARGE":
        key = "DELIVERY_INCOME" if "deliver" in (l.get("description") or "").lower() or l.get("charge_kind") == "DELIVERY" \
            else "OTHER_CHARGE_INCOME"
        acct = rules.optional(conn, entity_id, key) or rules.account(conn, entity_id, "DELIVERY_INCOME")
        return str(acct["id"])
    return str(rules.account(conn, entity_id, "SALES_DISCOUNT")["id"])


def _price_lines(conn, entity_id: str, raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for i, l in enumerate(raw, start=1):
        t = str(l.get("line_type") or ("ITEM" if l.get("sku") else "SERVICE")).upper()
        if t not in LINE_TYPES:
            raise invalid(f"Line {i}: unknown line type {t}")
        quantity = qty(l.get("quantity") if l.get("quantity") not in (None, "") else 1)
        price = money(l.get("unit_price"))
        disc = money(l.get("discount_amount"))
        if t in ("ITEM", "SERVICE") and quantity <= 0:
            raise invalid(f"Line {i}: quantity must be positive")
        if price < 0 or disc < 0:
            raise invalid(f"Line {i}: prices and discounts are entered as positive amounts")
        if t == "ITEM":
            if not l.get("sku"):
                raise invalid(f"Line {i}: a stock line needs a product")
            p = rules.product(conn, entity_id, str(l["sku"]).strip())
            l = {**l, "sku": p["sku"], "description": l.get("description") or p["name"]}
        gross = money(quantity * price)
        if disc > gross and t != "DISCOUNT":
            raise invalid(f"Line {i}: discount is larger than the line value")
        net = gross - disc
        if t == "DISCOUNT":
            net = -(gross if gross > 0 else disc)
            gross, disc = ZERO, -net
        row = {**l, "line_no": i, "line_type": t, "quantity": quantity, "unit_price": price, "gross": gross,
               "discount_amount": disc, "line_total": net}
        row["account_id"] = _line_account(conn, entity_id, row)
        out.append(row)
    return out


def create_invoice(conn, ctx, data: Dict[str, Any], *, source_type: str = "MANUAL", source_id: Optional[str] = None,
                   number: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("sales.invoice.create")
    c = customer(conn, data["customer_id"])
    lines = _price_lines(conn, ctx.entity_id, data.get("lines") or [])
    if not lines:
        raise invalid("An invoice needs at least one line")
    inv_date = data["invoice_date"]
    terms = int(data["terms_days"]) if data.get("terms_days") not in (None, "") else int(c["payment_terms_days"] or 30)
    due = data.get("due_date") or inv_date + dt.timedelta(days=terms)
    subtotal = sum((l["gross"] for l in lines if l["line_type"] in ("ITEM", "SERVICE")), ZERO)
    discount = sum((l["discount_amount"] for l in lines), ZERO)
    charges = sum((l["line_total"] for l in lines if l["line_type"] == "CHARGE"), ZERO)
    tax = money(data.get("tax_total"))
    total = subtotal - discount + charges + tax
    if total <= 0:
        raise invalid("Invoice total must be positive")
    if tax > 0:
        rules.account(conn, ctx.entity_id, "OUTPUT_TAX")  # refuse until tax treatment is configured
    number = number or next_number(conn, ctx.entity_id, "SALES_INVOICE")
    ship_to = data.get("ship_to")
    if isinstance(ship_to, dict):
        ship_to = ", ".join(str(v) for v in ship_to.values() if v)
    inv = q1(conn, """
        INSERT INTO fin_sales_invoices (legal_entity_id, invoice_number, customer_id, invoice_date, due_date, terms_days,
            subtotal, discount_total, charge_total, tax_total, total, source_type, source_id, reference, notes, created_by,
            customer_po, shipping_method, ship_to, sales_rep)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
    """, (ctx.entity_id, number, c["id"], inv_date, due, terms, subtotal, discount, charges, tax, total,
          source_type, source_id, data.get("reference"), data.get("notes"), ctx.actor_id,
          data.get("customer_po") or data.get("reference"), data.get("shipping_method"), ship_to or None, data.get("sales_rep")))
    for l in lines:
        batch_id = l.get("batch_id") or (inventory.ensure_batch(conn, ctx.entity_id, l["sku"], l.get("batch_number"))
                                         if l["line_type"] == "ITEM" and l.get("batch_number") else None)
        ex(conn, """INSERT INTO fin_sales_invoice_lines (invoice_id, line_no, line_type, sku, batch_id, description,
                    quantity, unit_price, discount_amount, line_total, account_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
           (inv["id"], l["line_no"], l["line_type"], l.get("sku"), batch_id, l.get("description"), l["quantity"],
            l["unit_price"], l["discount_amount"], l["line_total"], l["account_id"]))
    audit.record(conn, ctx, "INVOICE_CREATED", "sales_invoice", inv["id"], ref=number,
                 after={"customer": c["name"], "total": total})
    return get_invoice(conn, ctx.entity_id, inv["id"])


def get_invoice(conn, entity_id: str, invoice_id: str) -> Dict[str, Any]:
    inv = q1(conn, """SELECT i.*, c.name AS customer_name, c.customer_code, (i.total - i.amount_settled) AS balance_due,
                             j.journal_number
                      FROM fin_sales_invoices i LEFT JOIN customers c ON c.id=i.customer_id
                      LEFT JOIN fin_journals j ON j.id=i.journal_id
                      WHERE i.id=%s AND i.legal_entity_id=%s""", (invoice_id, entity_id))
    if not inv:
        raise not_found("Invoice", invoice_id)
    inv["lines"] = q(conn, """SELECT l.*, a.code AS account_code, a.name AS account_name, b.batch_number, b.lot_code,
                                     b.manufacture_date, b.expiry_date,
                                     COALESCE(b.batch_number, cb.batch_number) AS shipped_batch,
                                     COALESCE(b.manufacture_date, cb.manufacture_date) AS shipped_mfg,
                                     COALESCE(b.expiry_date, cb.expiry_date) AS shipped_expiry,
                                     CASE WHEN l.quantity <> 0 THEN round(l.cost_amount / l.quantity, 2) END AS unit_cost
                              FROM fin_sales_invoice_lines l LEFT JOIN fin_accounts a ON a.id=l.account_id
                              LEFT JOIN fin_batches b ON b.id=l.batch_id
                              LEFT JOIN LATERAL (SELECT bb.batch_number, bb.manufacture_date, bb.expiry_date
                                                 FROM fin_layer_consumptions lc JOIN fin_cost_layers cl ON cl.id=lc.layer_id
                                                 JOIN fin_batches bb ON bb.id=cl.batch_id
                                                 WHERE lc.inventory_txn_id=l.inventory_txn_id ORDER BY lc.quantity DESC LIMIT 1) cb ON TRUE
                              WHERE l.invoice_id=%s ORDER BY l.line_no""", (invoice_id,))
    inv["customer"] = q1(conn, """SELECT id, name, customer_code, contact_details, credit_limit, payment_terms_days
                                  FROM customers WHERE id=%s""", (inv["customer_id"],))
    inv["allocations"] = q(conn, """
        SELECT a.*, COALESCE(r.receipt_number, n.credit_note_number) AS source_number
        FROM fin_ar_allocations a
        LEFT JOIN fin_customer_receipts r ON a.source_type='RECEIPT' AND r.id=a.source_id
        LEFT JOIN fin_credit_notes n ON a.source_type='CREDIT_NOTE' AND n.id=a.source_id
        WHERE a.invoice_id=%s ORDER BY a.allocation_date, a.created_at""", (invoice_id,))
    if inv["is_opening"]:
        # What was sold and how it was paid, from Sage's own journals (display only).
        from src.fin import ledger_reports
        sage_no = (inv.get("source_id") or "").split(":")[-1] or inv["invoice_number"]
        full = ledger_reports.sage_invoice(conn, entity_id, sage_no)
        inv["history_lines"] = [l for l in full["lines"] if l["customer_id"] in (None, inv["customer_id"])]
        inv["sage_payments"] = full["payments"]
        inv["sage_number"] = sage_no
    return inv


def post_invoice(conn, ctx, invoice_id: str, *, override_credit: bool = False,
                 override_reason: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("sales.invoice.post")
    inv = q1(conn, "SELECT * FROM fin_sales_invoices WHERE id=%s AND legal_entity_id=%s FOR UPDATE",
             (invoice_id, ctx.entity_id))
    if not inv:
        raise not_found("Invoice", invoice_id)
    if inv["status"] != "DRAFT":
        if inv["journal_id"]:
            return get_invoice(conn, ctx.entity_id, invoice_id)  # already posted: idempotent
        raise FinError("INVALID_STATE_TRANSITION", f"A {inv['status'].lower()} invoice cannot be posted")
    total = money(inv["total"])

    # Credit control is a backend rule, not a UI hint (CM V2 §9).
    settings = q1(conn, "SELECT credit_limit_mode FROM fin_settings WHERE legal_entity_id=%s", (ctx.entity_id,))
    mode = (settings or {}).get("credit_limit_mode", "WARN")
    check = credit_check(conn, ctx.entity_id, inv["customer_id"], total)
    if mode != "OFF" and check["exceeds"]:
        if not override_credit:
            raise FinError("CREDIT_LIMIT_EXCEEDED",
                           f"{check['customer']}'s credit limit (₦{Decimal(check['credit_limit']):,.2f}) would be exceeded "
                           f"by ₦{Decimal(check['excess']):,.2f}", check)
        if mode == "BLOCK":
            ctx.require("sales.credit.override")
        if not (override_reason or "").strip():
            raise invalid("Give a reason for going over the credit limit")
        ex(conn, """INSERT INTO fin_validation_events (legal_entity_id, entity_type, entity_id, entity_ref, check_code,
                    severity, message, details, status, created_by) VALUES (%s,'sales_invoice',%s,%s,'CREDIT_LIMIT_EXCEEDED',
                    'WARNING',%s,%s,'ACCEPTED',%s)""",
           (ctx.entity_id, invoice_id, inv["invoice_number"], f"Credit limit exceeded by ₦{Decimal(check['excess']):,.2f}: {override_reason}",
            jsonb(check), ctx.actor_id))

    ar = rules.account(conn, ctx.entity_id, "AR_CONTROL")
    cust = inv["customer_id"]
    jl: List[Dict[str, Any]] = [{"account_id": ar["id"], "debit": total, "customer_id": cust,
                                 "description": f"Invoice {inv['invoice_number']}"}]
    txns: List[str] = []
    lines = q(conn, "SELECT * FROM fin_sales_invoice_lines WHERE invoice_id=%s ORDER BY line_no", (invoice_id,))
    disc_acct = None
    for l in lines:
        gross = money(Decimal(str(l["quantity"])) * Decimal(str(l["unit_price"])))
        disc = money(l["discount_amount"])
        if l["line_type"] in ("ITEM", "SERVICE"):
            jl.append({"account_id": l["account_id"], "credit": gross, "customer_id": cust, "product_sku": l["sku"],
                       "description": l["description"]})
            if disc > 0:
                disc_acct = disc_acct or rules.account(conn, ctx.entity_id, "SALES_DISCOUNT")
                jl.append({"account_id": disc_acct["id"], "debit": disc, "customer_id": cust, "product_sku": l["sku"],
                           "description": f"Discount on {l['description']}"})
        elif l["line_type"] == "CHARGE":
            jl.append({"account_id": l["account_id"], "credit": money(l["line_total"]), "customer_id": cust,
                       "description": l["description"]})
        else:  # DISCOUNT
            jl.append({"account_id": l["account_id"], "debit": -money(l["line_total"]), "customer_id": cust,
                       "description": l["description"] or "Discount"})
        if l["line_type"] == "ITEM":
            prod = rules.product(conn, ctx.entity_id, l["sku"])
            if prod["product_type"] == "INVENTORY":
                inventory.require_sellable(conn, ctx.entity_id, str(l["batch_id"]) if l["batch_id"] else None)
                t = inventory.issue(conn, ctx, sku=l["sku"], quantity=l["quantity"], txn_type="SALE",
                                    txn_date=inv["invoice_date"], batch_id=str(l["batch_id"]) if l["batch_id"] else None,
                                    source_type=inv["source_type"] if inv["source_type"] == "FRONTDESK" else "SALES_INVOICE",
                                    source_id=invoice_id, reference=inv["invoice_number"], customer_id=cust)
                cost = t["cost"]
                txns.append(str(t["id"]))
                ex(conn, "UPDATE fin_sales_invoice_lines SET cost_amount=%s, inventory_txn_id=%s WHERE id=%s",
                   (cost, t["id"], l["id"]))
                if cost > 0:
                    acc = rules.product_accounts(conn, ctx.entity_id, l["sku"])
                    jl += [{"account_id": acc["cogs_account_id"], "debit": cost, "product_sku": l["sku"],
                            "description": f"Cost of {l['description']}"},
                           {"account_id": acc["inventory_account_id"], "credit": cost, "product_sku": l["sku"]}]
    if money(inv["tax_total"]) > 0:
        jl.append({"account_id": rules.account(conn, ctx.entity_id, "OUTPUT_TAX")["id"], "credit": money(inv["tax_total"]),
                   "customer_id": cust, "description": "Tax on sales"})
    j = posting.post_system(conn, ctx, event_type="SALES_INVOICE_POSTED", journal_date=inv["invoice_date"], lines=jl,
                            description=f"Sales invoice {inv['invoice_number']}", source_type="SALES_INVOICE",
                            source_id=invoice_id, source_ref=inv["invoice_number"])
    inventory.link_journal(conn, txns, j["id"])
    ex(conn, """UPDATE fin_sales_invoices SET status='POSTED', journal_id=%s, posted_by=%s, posted_at=now(),
                credit_check=%s, credit_override_by=%s, credit_override_reason=%s WHERE id=%s""",
       (j["id"], ctx.actor_id, jsonb(check), ctx.actor_id if check["exceeds"] else None,
        override_reason if check["exceeds"] else None, invoice_id))
    audit.record(conn, ctx, "INVOICE_POSTED", "sales_invoice", invoice_id, ref=inv["invoice_number"],
                 metadata={"journal": j["journal_number"], "total": str(total), "credit_override": check["exceeds"]})
    return get_invoice(conn, ctx.entity_id, invoice_id)


def void_invoice(conn, ctx, invoice_id: str, reason: str, on: Optional[dt.date] = None) -> Dict[str, Any]:
    ctx.require("sales.invoice.void")
    inv = q1(conn, "SELECT * FROM fin_sales_invoices WHERE id=%s AND legal_entity_id=%s FOR UPDATE",
             (invoice_id, ctx.entity_id))
    if not inv:
        raise not_found("Invoice", invoice_id)
    if not (reason or "").strip():
        raise invalid("A reason is required to void an invoice")
    if inv["status"] == "DRAFT":
        ex(conn, "UPDATE fin_sales_invoices SET status='VOID', voided_by=%s, voided_at=now(), void_reason=%s WHERE id=%s",
           (ctx.actor_id, reason, invoice_id))
        audit.record(conn, ctx, "INVOICE_VOIDED", "sales_invoice", invoice_id, ref=inv["invoice_number"], reason=reason)
        return get_invoice(conn, ctx.entity_id, invoice_id)
    if inv["status"] == "VOID":
        raise FinError("INVALID_STATE_TRANSITION", "Invoice is already void")
    if inv["is_opening"]:
        raise FinError("INVALID_STATE_TRANSITION", "Opening-balance items are corrected with a credit note")
    if money(inv["amount_settled"]) > 0:
        raise FinError("INVALID_STATE_TRANSITION",
                       "Payments are applied to this invoice; unapply them or issue a credit note instead")
    rev = posting.reverse(conn, ctx, str(inv["journal_id"]), reversal_date=on or inv["invoice_date"],
                          reason=f"Void invoice {inv['invoice_number']}: {reason}", allow_system=True)
    for l in q(conn, "SELECT * FROM fin_sales_invoice_lines WHERE invoice_id=%s AND inventory_txn_id IS NOT NULL", (invoice_id,)):
        t = inventory.restore(conn, ctx, original_txn_id=str(l["inventory_txn_id"]), quantity=l["quantity"],
                              txn_type="RETURN_IN", txn_date=on or inv["invoice_date"], source_type="SALES_INVOICE_VOID",
                              source_id=invoice_id, reference=inv["invoice_number"], customer_id=inv["customer_id"],
                              reason="Invoice voided")
        inventory.link_journal(conn, [str(t["id"])], rev["id"])
    ex(conn, """UPDATE fin_sales_invoices SET status='VOID', void_journal_id=%s, voided_by=%s, voided_at=now(),
                void_reason=%s WHERE id=%s""", (rev["id"], ctx.actor_id, reason, invoice_id))
    audit.record(conn, ctx, "INVOICE_VOIDED", "sales_invoice", invoice_id, ref=inv["invoice_number"], reason=reason,
                 metadata={"reversal": rev["journal_number"]})
    return get_invoice(conn, ctx.entity_id, invoice_id)


def list_invoices(conn, entity_id: str, *, customer_id: Any = None, status: Optional[str] = None,
                  search: Optional[str] = None, date_from=None, date_to=None, open_only: bool = False,
                  limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = ["i.legal_entity_id=%s"], [entity_id]
    if customer_id:
        where.append("i.customer_id=%s")
        params.append(int(customer_id))
    if status:
        where.append("i.status = ANY(%s)")
        params.append(status.split(","))
    if open_only:
        where.append("i.status IN ('POSTED','PARTIALLY_PAID')")
    if date_from:
        where.append("i.invoice_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("i.invoice_date <= %s")
        params.append(date_to)
    if search:
        where.append("(i.invoice_number ILIKE %s OR c.name ILIKE %s OR i.reference ILIKE %s)")
        params += [f"%{search}%"] * 3
    w = " AND ".join(where)
    total = q1(conn, f"SELECT COUNT(*) n FROM fin_sales_invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE {w}", params)["n"]
    rows = q(conn, f"""SELECT i.id, i.invoice_number, i.invoice_date, i.due_date, i.customer_id, c.name AS customer_name,
                              i.total, i.amount_settled, (i.total - i.amount_settled) AS balance_due, i.status,
                              i.source_type, i.is_opening, i.reference
                       FROM fin_sales_invoices i LEFT JOIN customers c ON c.id=i.customer_id
                       WHERE {w} ORDER BY i.invoice_date DESC, i.invoice_number DESC LIMIT %s OFFSET %s""",
             params + [limit, offset])
    return {"items": rows, "total": total}


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

def _refresh_invoice_status(conn, invoice_id: str) -> None:
    ex(conn, """UPDATE fin_sales_invoices SET status = CASE
                    WHEN amount_settled >= total THEN 'PAID'
                    WHEN amount_settled > 0 THEN 'PARTIALLY_PAID' ELSE 'POSTED' END
                WHERE id=%s AND status IN ('POSTED','PARTIALLY_PAID','PAID')""", (invoice_id,))


def _apply(conn, ctx, *, source_type: str, source_id: str, customer_id: int, allocations: List[Dict[str, Any]],
           available: Decimal, on: dt.date) -> Decimal:
    used = ZERO
    for a in allocations or []:
        amt = money(a.get("amount"))
        if amt <= 0:
            continue
        inv = q1(conn, """SELECT * FROM fin_sales_invoices WHERE id=%s AND legal_entity_id=%s FOR UPDATE""",
                 (a["invoice_id"], ctx.entity_id))
        if not inv:
            raise not_found("Invoice", a["invoice_id"])
        if inv["customer_id"] != customer_id:
            raise invalid(f"Invoice {inv['invoice_number']} belongs to another customer")
        if inv["status"] not in ("POSTED", "PARTIALLY_PAID"):
            raise FinError("INVALID_STATE_TRANSITION", f"Invoice {inv['invoice_number']} is {inv['status'].lower()}")
        open_amt = money(inv["total"]) - money(inv["amount_settled"])
        if amt > open_amt:
            raise FinError("OVER_ALLOCATION", f"Only ₦{open_amt:,.2f} is outstanding on {inv['invoice_number']}",
                           {"invoice": inv["invoice_number"], "outstanding": str(open_amt)})
        if used + amt > available:
            raise FinError("OVER_ALLOCATION", f"Allocations exceed the ₦{available:,.2f} available",
                           {"available": str(available)})
        ex(conn, """INSERT INTO fin_ar_allocations (legal_entity_id, source_type, source_id, invoice_id, amount,
                    allocation_date, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
           (ctx.entity_id, source_type, source_id, inv["id"], amt, on, ctx.actor_id))
        ex(conn, "UPDATE fin_sales_invoices SET amount_settled = amount_settled + %s WHERE id=%s", (amt, inv["id"]))
        _refresh_invoice_status(conn, str(inv["id"]))
        used += amt
    return used


def _unapply(conn, source_type: str, source_id: str) -> None:
    for a in q(conn, """SELECT * FROM fin_ar_allocations WHERE source_type=%s AND source_id=%s AND NOT reversed""",
               (source_type, source_id)):
        ex(conn, "UPDATE fin_ar_allocations SET reversed=TRUE WHERE id=%s", (a["id"],))
        ex(conn, "UPDATE fin_sales_invoices SET amount_settled = amount_settled - %s WHERE id=%s", (a["amount"], a["invoice_id"]))
        _refresh_invoice_status(conn, str(a["invoice_id"]))


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def bank_account(conn, entity_id: str, bank_account_id: str) -> Dict[str, Any]:
    b = q1(conn, """SELECT b.*, a.code AS gl_code FROM fin_bank_accounts b JOIN fin_accounts a ON a.id=b.gl_account_id
                    WHERE b.id=%s AND b.legal_entity_id=%s""", (bank_account_id, entity_id))
    if not b:
        raise not_found("Bank/cash account", bank_account_id)
    if b["status"] != "ACTIVE":
        raise FinError("ACCOUNT_INACTIVE", f"{b['name']} is inactive")
    return b


def duplicate_reference(conn, entity_id: str, table: str, reference: Optional[str], exclude_id: Optional[str] = None):
    if not reference or not reference.strip():
        return None
    return q1(conn, f"""SELECT * FROM {table} WHERE legal_entity_id=%s AND lower(reference)=lower(%s)
                        AND status='POSTED' AND (%s::uuid IS NULL OR id <> %s::uuid) LIMIT 1""",
              (entity_id, reference.strip(), exclude_id, exclude_id))


def create_receipt(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("receivables.receipt.create")
    c = customer(conn, data["customer_id"])
    method = str(data.get("method") or "TRANSFER").upper()
    if method not in METHODS:
        raise invalid(f"Payment method must be one of {', '.join(METHODS)}")
    bank = bank_account(conn, ctx.entity_id, data["bank_account_id"])
    amount, wht = money(data.get("amount")), money(data.get("wht_amount"))
    if amount <= 0:
        raise invalid("Receipt amount must be positive")
    reference = (data.get("reference") or "").strip() or None
    dup = duplicate_reference(conn, ctx.entity_id, "fin_customer_receipts", reference)
    if dup and not data.get("confirm_duplicate"):
        # The accountant's "cheque 001 posted twice" problem (meeting 2).
        raise FinError("DUPLICATE_REFERENCE",
                       f"Reference {reference} was already used on receipt {dup['receipt_number']}",
                       {"existing": dup["receipt_number"], "reference": reference})
    number = next_number(conn, ctx.entity_id, "RECEIPT")
    r = q1(conn, """INSERT INTO fin_customer_receipts (legal_entity_id, receipt_number, customer_id, receipt_date, method,
                    bank_account_id, amount, wht_amount, reference, notes, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
           (ctx.entity_id, number, c["id"], data["receipt_date"], method, bank["id"], amount, wht, reference,
            data.get("notes"), ctx.actor_id))
    if dup:
        ex(conn, """INSERT INTO fin_validation_events (legal_entity_id, entity_type, entity_id, entity_ref, check_code,
                    severity, message, status, created_by) VALUES (%s,'customer_receipt',%s,%s,'DUPLICATE_REFERENCE',
                    'WARNING',%s,'ACCEPTED',%s)""",
           (ctx.entity_id, r["id"], number, f"Reference {reference} also used on {dup['receipt_number']}", ctx.actor_id))
    ar = rules.account(conn, ctx.entity_id, "AR_CONTROL")
    jl = [{"account_id": bank["gl_account_id"], "debit": amount, "customer_id": c["id"],
           "description": f"{c['name']} {reference or ''}".strip()}]
    if wht > 0:
        jl.append({"account_id": rules.account(conn, ctx.entity_id, "WHT_SUFFERED")["id"], "debit": wht,
                   "customer_id": c["id"], "description": f"WHT deducted by {c['name']}"})
    jl.append({"account_id": ar["id"], "credit": amount + wht, "customer_id": c["id"], "description": f"Receipt {number}"})
    j = posting.post_system(conn, ctx, event_type="CUSTOMER_PAYMENT_RECEIVED", journal_date=data["receipt_date"],
                            lines=jl, description=f"Receipt {number} from {c['name']}", source_type="CUSTOMER_RECEIPT",
                            source_id=r["id"], source_ref=number)
    used = _apply(conn, ctx, source_type="RECEIPT", source_id=str(r["id"]), customer_id=c["id"],
                  allocations=data.get("allocations") or [], available=amount + wht, on=data["receipt_date"])
    ex(conn, "UPDATE fin_customer_receipts SET journal_id=%s, amount_allocated=%s WHERE id=%s", (j["id"], used, r["id"]))
    audit.record(conn, ctx, "RECEIPT_POSTED", "customer_receipt", r["id"], ref=number,
                 metadata={"amount": str(amount), "wht": str(wht), "allocated": str(used), "journal": j["journal_number"]})
    return get_receipt(conn, ctx.entity_id, r["id"])


def get_receipt(conn, entity_id: str, receipt_id: str) -> Dict[str, Any]:
    r = q1(conn, """SELECT r.*, c.name AS customer_name, b.name AS bank_account_name, j.journal_number,
                           (r.amount + r.wht_amount - r.amount_allocated) AS unapplied
                    FROM fin_customer_receipts r LEFT JOIN customers c ON c.id=r.customer_id
                    LEFT JOIN fin_bank_accounts b ON b.id=r.bank_account_id LEFT JOIN fin_journals j ON j.id=r.journal_id
                    WHERE r.id=%s AND r.legal_entity_id=%s""", (receipt_id, entity_id))
    if not r:
        raise not_found("Receipt", receipt_id)
    r["allocations"] = q(conn, """SELECT a.*, i.invoice_number FROM fin_ar_allocations a JOIN fin_sales_invoices i
                                  ON i.id=a.invoice_id WHERE a.source_type='RECEIPT' AND a.source_id=%s
                                  ORDER BY a.created_at""", (receipt_id,))
    return r


def allocate_receipt(conn, ctx, receipt_id: str, allocations: List[Dict[str, Any]], on: Optional[dt.date] = None):
    ctx.require("receivables.receipt.create")
    r = q1(conn, "SELECT * FROM fin_customer_receipts WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (receipt_id, ctx.entity_id))
    if not r:
        raise not_found("Receipt", receipt_id)
    if r["status"] != "POSTED":
        raise FinError("INVALID_STATE_TRANSITION", "A void receipt cannot be allocated")
    available = money(r["amount"]) + money(r["wht_amount"]) - money(r["amount_allocated"])
    used = _apply(conn, ctx, source_type="RECEIPT", source_id=receipt_id, customer_id=r["customer_id"],
                  allocations=allocations, available=available, on=on or dt.date.today())
    ex(conn, "UPDATE fin_customer_receipts SET amount_allocated = amount_allocated + %s WHERE id=%s", (used, receipt_id))
    audit.record(conn, ctx, "RECEIPT_ALLOCATED", "customer_receipt", receipt_id, ref=r["receipt_number"],
                 metadata={"allocated": str(used)})
    return get_receipt(conn, ctx.entity_id, receipt_id)


def void_receipt(conn, ctx, receipt_id: str, reason: str, on: Optional[dt.date] = None) -> Dict[str, Any]:
    ctx.require("receivables.receipt.void")
    r = q1(conn, "SELECT * FROM fin_customer_receipts WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (receipt_id, ctx.entity_id))
    if not r:
        raise not_found("Receipt", receipt_id)
    if r["status"] != "POSTED":
        raise FinError("INVALID_STATE_TRANSITION", "Receipt is already void")
    if not (reason or "").strip():
        raise invalid("A reason is required to void a receipt (e.g. bounced cheque)")
    rev = posting.reverse(conn, ctx, str(r["journal_id"]), reversal_date=on or r["receipt_date"],
                          reason=f"Void receipt {r['receipt_number']}: {reason}", allow_system=True)
    _unapply(conn, "RECEIPT", receipt_id)
    ex(conn, "UPDATE fin_customer_receipts SET status='VOID', void_journal_id=%s, void_reason=%s, amount_allocated=0 WHERE id=%s",
       (rev["id"], reason, receipt_id))
    audit.record(conn, ctx, "RECEIPT_VOIDED", "customer_receipt", receipt_id, ref=r["receipt_number"], reason=reason)
    return get_receipt(conn, ctx.entity_id, receipt_id)


def list_receipts(conn, entity_id: str, *, customer_id: Any = None, search: Optional[str] = None,
                  date_from=None, date_to=None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = ["r.legal_entity_id=%s"], [entity_id]
    if customer_id:
        where.append("r.customer_id=%s")
        params.append(int(customer_id))
    if date_from:
        where.append("r.receipt_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("r.receipt_date <= %s")
        params.append(date_to)
    if search:
        where.append("(r.receipt_number ILIKE %s OR c.name ILIKE %s OR r.reference ILIKE %s)")
        params += [f"%{search}%"] * 3
    w = " AND ".join(where)
    total = q1(conn, f"SELECT COUNT(*) n FROM fin_customer_receipts r LEFT JOIN customers c ON c.id=r.customer_id WHERE {w}", params)["n"]
    rows = q(conn, f"""SELECT r.id, r.receipt_number, r.receipt_date, r.customer_id, c.name AS customer_name, r.method,
                              b.name AS bank_account_name, r.amount, r.wht_amount, r.amount_allocated,
                              (r.amount + r.wht_amount - r.amount_allocated) AS unapplied, r.reference, r.status
                       FROM fin_customer_receipts r LEFT JOIN customers c ON c.id=r.customer_id
                       LEFT JOIN fin_bank_accounts b ON b.id=r.bank_account_id
                       WHERE {w} ORDER BY r.receipt_date DESC, r.receipt_number DESC LIMIT %s OFFSET %s""",
             params + [limit, offset])
    return {"items": rows, "total": total}


# ---------------------------------------------------------------------------
# Credit notes / returns inward
# ---------------------------------------------------------------------------

def create_credit_note(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("sales.credit_note.create")
    c = customer(conn, data["customer_id"])
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise invalid("A credit note needs a reason")
    invoice = None
    sage_no = (data.get("sage_invoice_number") or "").strip() or None
    if not data.get("invoice_id") and sage_no:
        # a Sage invoice still open in ACE Books (brought forward) is credited directly
        ob = q1(conn, """SELECT id FROM fin_sales_invoices WHERE legal_entity_id=%s AND customer_id=%s
                         AND (invoice_number=%s OR split_part(source_id, ':', 3)=%s) AND status <> 'VOID' LIMIT 1""",
                (ctx.entity_id, c["id"], sage_no, sage_no))
        if ob:
            data = {**data, "invoice_id": ob["id"]}
    if data.get("invoice_id"):
        invoice = q1(conn, "SELECT * FROM fin_sales_invoices WHERE id=%s AND legal_entity_id=%s FOR UPDATE",
                     (data["invoice_id"], ctx.entity_id))
        if not invoice or invoice["customer_id"] != c["id"]:
            raise invalid("The credited invoice was not found for this customer")
        if invoice["status"] == "VOID":
            raise FinError("INVALID_STATE_TRANSITION", "That invoice is void")
        sage_no = sage_no or (invoice["invoice_number"] if invoice["is_opening"] else None)
    return_to_stock = bool(data.get("return_to_stock"))
    lines = _price_lines(conn, ctx.entity_id, data.get("lines") or [])
    if not lines:
        raise invalid("A credit note needs at least one line")
    total = sum((l["line_total"] for l in lines), ZERO)
    if total <= 0:
        raise invalid("Credit note total must be positive")
    number = next_number(conn, ctx.entity_id, "CREDIT_NOTE")
    on = data["note_date"]
    cn = q1(conn, """INSERT INTO fin_credit_notes (legal_entity_id, credit_note_number, customer_id, invoice_id, note_date,
                     reason, return_to_stock, total, created_by, sage_invoice_number, recall_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (ctx.entity_id, number, c["id"], invoice["id"] if invoice else None, on, reason, return_to_stock, total,
             ctx.actor_id, sage_no, data.get("recall_id")))
    ar = rules.account(conn, ctx.entity_id, "AR_CONTROL")
    returns_acct = rules.account(conn, ctx.entity_id, "SALES_RETURNS")
    jl: List[Dict[str, Any]] = [{"account_id": ar["id"], "credit": total, "customer_id": c["id"],
                                 "description": f"Credit note {number}"}]
    txns = []
    for l in lines:
        acct = returns_acct["id"] if l["line_type"] in ("ITEM", "SERVICE") else l["account_id"]
        amt = l["line_total"]
        if amt > 0:
            jl.append({"account_id": acct, "debit": amt, "customer_id": c["id"], "product_sku": l.get("sku"),
                       "description": f"{reason}: {l.get('description') or ''}".strip()})
        elif amt < 0:
            jl.append({"account_id": acct, "credit": -amt, "customer_id": c["id"], "description": reason})
        txn_id, cost = None, None
        if return_to_stock and l["line_type"] == "ITEM":
            prod = rules.product(conn, ctx.entity_id, l["sku"])
            if prod["product_type"] == "INVENTORY":
                src = None
                if invoice:
                    src = q1(conn, """SELECT inventory_txn_id FROM fin_sales_invoice_lines WHERE invoice_id=%s AND sku=%s
                                      AND inventory_txn_id IS NOT NULL ORDER BY line_no LIMIT 1""", (invoice["id"], l["sku"]))
                batch_id = l.get("batch_id") or inventory.ensure_batch(conn, ctx.entity_id, l["sku"], l.get("batch_number"))
                if src:
                    t = inventory.restore(conn, ctx, original_txn_id=str(src["inventory_txn_id"]), quantity=l["quantity"],
                                          txn_type="RETURN_IN", txn_date=on, batch_id=batch_id, source_type="CREDIT_NOTE",
                                          source_id=cn["id"], reference=number, customer_id=c["id"], reason=reason)
                else:
                    # back in at what it cost when it was sold (the Sage line's cost), else the last cost
                    unit = l.get("unit_cost")
                    t = inventory.receive(conn, ctx, sku=l["sku"], quantity=l["quantity"],
                                          unit_cost=unit if unit not in (None, "") else inventory.last_unit_cost(conn, ctx.entity_id, l["sku"]),
                                          txn_type="RETURN_IN", txn_date=on, batch_id=batch_id, source_type="CREDIT_NOTE",
                                          source_id=cn["id"], reference=number, customer_id=c["id"], reason=reason)
                txn_id, cost = str(t["id"]), money(t["total_cost"])
                txns.append(txn_id)
                if cost > 0:
                    acc = rules.product_accounts(conn, ctx.entity_id, l["sku"])
                    jl += [{"account_id": acc["inventory_account_id"], "debit": cost, "product_sku": l["sku"]},
                           {"account_id": acc["cogs_account_id"], "credit": cost, "product_sku": l["sku"],
                            "description": f"Cost reversed: {l.get('description')}"}]
        ex(conn, """INSERT INTO fin_credit_note_lines (credit_note_id, line_no, line_type, sku, batch_id, description,
                    quantity, unit_price, line_total, account_id, cost_amount, inventory_txn_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
           (cn["id"], l["line_no"], l["line_type"], l.get("sku"), l.get("batch_id"), l.get("description"),
            l["quantity"], l["unit_price"], l["line_total"], acct, cost, txn_id))
    j = posting.post_system(conn, ctx, event_type="CREDIT_NOTE_POSTED", journal_date=on, lines=jl,
                            description=f"Credit note {number} to {c['name']}: {reason}", source_type="CREDIT_NOTE",
                            source_id=cn["id"], source_ref=number)
    inventory.link_journal(conn, txns, j["id"])
    used = ZERO
    if invoice and invoice["status"] in ("POSTED", "PARTIALLY_PAID"):
        open_amt = money(invoice["total"]) - money(invoice["amount_settled"])
        used = _apply(conn, ctx, source_type="CREDIT_NOTE", source_id=str(cn["id"]), customer_id=c["id"],
                      allocations=[{"invoice_id": invoice["id"], "amount": min(open_amt, total)}], available=total, on=on)
    ex(conn, "UPDATE fin_credit_notes SET journal_id=%s, amount_settled=%s WHERE id=%s", (j["id"], used, cn["id"]))
    audit.record(conn, ctx, "CREDIT_NOTE_POSTED", "credit_note", cn["id"], ref=number, reason=reason,
                 metadata={"total": str(total), "return_to_stock": return_to_stock})
    return get_credit_note(conn, ctx.entity_id, cn["id"])


def returnable_invoices(conn, entity_id: str, customer_id: int, search: Optional[str] = None,
                        sku: Optional[str] = None, limit: int = 40) -> List[Dict[str, Any]]:
    """A customer's invoices - ACE Books and Sage history - with what was sold on each (item,
    lot / batch, quantity, unit price and unit cost), newest first, for a return inward."""
    s = f"%{search}%" if search else None
    ace = q(conn, """SELECT i.id::text AS invoice_id, i.invoice_number, i.invoice_date, i.total, i.total - i.amount_settled AS balance,
                            i.status, FALSE AS sage
                     FROM fin_sales_invoices i WHERE i.legal_entity_id=%s AND i.customer_id=%s AND i.status NOT IN ('DRAFT','VOID')
                       AND NOT i.is_opening AND (%s::text IS NULL OR i.invoice_number ILIKE %s)
                       AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM fin_sales_invoice_lines l WHERE l.invoice_id=i.id AND l.sku=%s))
                     ORDER BY i.invoice_date DESC LIMIT %s""", (entity_id, customer_id, s, s, sku, sku, limit))
    for i in ace:
        i["lines"] = q(conn, """SELECT l.sku, l.description, l.quantity, l.unit_price, l.batch_id::text AS batch_id,
                                       COALESCE(b.batch_number, cb.batch_number) AS batch_number,
                                       COALESCE(l.batch_id, cb.id)::text AS return_batch_id,
                                       CASE WHEN l.quantity <> 0 THEN round(l.cost_amount / l.quantity, 2) END AS unit_cost
                                FROM fin_sales_invoice_lines l LEFT JOIN fin_batches b ON b.id=l.batch_id
                                LEFT JOIN LATERAL (SELECT bb.id, bb.batch_number FROM fin_layer_consumptions lc
                                                   JOIN fin_cost_layers cl ON cl.id=lc.layer_id JOIN fin_batches bb ON bb.id=cl.batch_id
                                                   WHERE lc.inventory_txn_id=l.inventory_txn_id LIMIT 1) cb ON TRUE
                                WHERE l.invoice_id=%s AND l.line_type='ITEM' ORDER BY l.line_no""", (i["invoice_id"],))
    sage = q(conn, """SELECT s.invoice_number, MIN(s.invoice_date) AS invoice_date, SUM(s.amount) AS total, TRUE AS sage,
                             (SELECT o.id::text FROM fin_sales_invoices o WHERE o.legal_entity_id=s.legal_entity_id AND o.is_opening
                                AND split_part(o.source_id, ':', 3)=s.invoice_number AND o.customer_id=s.customer_id LIMIT 1) AS invoice_id,
                             (SELECT o.total - o.amount_settled FROM fin_sales_invoices o WHERE o.legal_entity_id=s.legal_entity_id
                                AND o.is_opening AND split_part(o.source_id, ':', 3)=s.invoice_number AND o.customer_id=s.customer_id
                                LIMIT 1) AS balance
                      FROM fin_sage_sales_lines s WHERE s.legal_entity_id=%s AND s.customer_id=%s
                        AND (%s::text IS NULL OR s.invoice_number ILIKE %s) AND (%s::text IS NULL OR s.sku=%s)
                      GROUP BY s.legal_entity_id, s.customer_id, s.invoice_number ORDER BY MIN(s.invoice_date) DESC LIMIT %s""",
             (entity_id, customer_id, s, s, sku, sku, limit))
    for i in sage:
        i["lines"] = q(conn, """SELECT s.sku, COALESCE(p.name, s.description) AS description, s.quantity,
                                       CASE WHEN s.quantity <> 0 THEN round(s.amount / s.quantity, 2) END AS unit_price,
                                       CASE WHEN s.quantity <> 0 THEN round(s.cost / s.quantity, 2) END AS unit_cost,
                                       b.id::text AS return_batch_id, b.batch_number
                                FROM fin_sage_sales_lines s
                                LEFT JOIN fin_products p ON p.legal_entity_id=s.legal_entity_id AND p.sku=s.sku
                                LEFT JOIN LATERAL (SELECT id, batch_number FROM fin_batches bb WHERE bb.legal_entity_id=s.legal_entity_id
                                                   AND bb.sku=s.sku ORDER BY created_at LIMIT 1) b ON TRUE
                                WHERE s.legal_entity_id=%s AND s.invoice_number=%s AND s.customer_id=%s AND s.sku IS NOT NULL
                                ORDER BY s.line_no""", (entity_id, i["invoice_number"], customer_id))
    out = sorted(ace + sage, key=lambda r: r["invoice_date"] or dt.date.min, reverse=True)
    return out[:limit]


def get_credit_note(conn, entity_id: str, cn_id: str) -> Dict[str, Any]:
    cn = q1(conn, """SELECT n.*, c.name AS customer_name, i.invoice_number, j.journal_number,
                            (n.total - n.amount_settled) AS unapplied
                     FROM fin_credit_notes n LEFT JOIN customers c ON c.id=n.customer_id
                     LEFT JOIN fin_sales_invoices i ON i.id=n.invoice_id LEFT JOIN fin_journals j ON j.id=n.journal_id
                     WHERE n.id=%s AND n.legal_entity_id=%s""", (cn_id, entity_id))
    if not cn:
        raise not_found("Credit note", cn_id)
    cn["lines"] = q(conn, "SELECT * FROM fin_credit_note_lines WHERE credit_note_id=%s ORDER BY line_no", (cn_id,))
    return cn


def list_credit_notes(conn, entity_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    total = q1(conn, "SELECT COUNT(*) n FROM fin_credit_notes WHERE legal_entity_id=%s", (entity_id,))["n"]
    rows = q(conn, """SELECT n.id, n.credit_note_number, n.note_date, n.customer_id, c.name AS customer_name,
                             i.invoice_number, n.reason, n.total, n.amount_settled, n.return_to_stock, n.status
                      FROM fin_credit_notes n LEFT JOIN customers c ON c.id=n.customer_id
                      LEFT JOIN fin_sales_invoices i ON i.id=n.invoice_id
                      WHERE n.legal_entity_id=%s ORDER BY n.note_date DESC, n.credit_note_number DESC LIMIT %s OFFSET %s""",
             (entity_id, limit, offset))
    return {"items": rows, "total": total}


def allocate_credit_note(conn, ctx, cn_id: str, allocations: List[Dict[str, Any]]) -> Dict[str, Any]:
    ctx.require("sales.credit_note.create")
    cn = q1(conn, "SELECT * FROM fin_credit_notes WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (cn_id, ctx.entity_id))
    if not cn or cn["status"] != "POSTED":
        raise not_found("Credit note", cn_id)
    used = _apply(conn, ctx, source_type="CREDIT_NOTE", source_id=cn_id, customer_id=cn["customer_id"],
                  allocations=allocations, available=money(cn["total"]) - money(cn["amount_settled"]), on=dt.date.today())
    ex(conn, "UPDATE fin_credit_notes SET amount_settled = amount_settled + %s WHERE id=%s", (used, cn_id))
    audit.record(conn, ctx, "CREDIT_NOTE_ALLOCATED", "credit_note", cn_id, ref=cn["credit_note_number"],
                 metadata={"allocated": str(used)})
    return get_credit_note(conn, ctx.entity_id, cn_id)


# ---------------------------------------------------------------------------
# Frontdesk -> ACE Books (operations become accounting automatically)
# ---------------------------------------------------------------------------

def post_from_frontdesk(conn, ctx, frontdesk_invoice_id: str) -> Dict[str, Any]:
    """Turn a finance-approved Frontdesk invoice into a posted sales invoice.

    Idempotent (one ACE Books invoice per Frontdesk invoice). The walk-in's CRM
    customer is used; unlinked walk-ins post to the default customer
    (Sage's 'Sundry'), exactly as the client's Sage practice does.
    """
    fd = q1(conn, """SELECT i.*, w.customer_id AS crm_customer_id,
                            (i.created_at AT TIME ZONE 'Africa/Lagos')::date AS inv_date
                     FROM frontdesk_invoices i LEFT JOIN frontdesk_walk_ins w ON w.id = i.walk_in_id
                     WHERE i.id=%s""", (frontdesk_invoice_id,))
    if not fd:
        raise not_found("Frontdesk invoice", frontdesk_invoice_id)
    existing = q1(conn, """SELECT id FROM fin_sales_invoices WHERE legal_entity_id=%s AND source_type='FRONTDESK'
                           AND source_id=%s AND status<>'VOID'""", (ctx.entity_id, str(fd["id"])))
    if existing:
        return get_invoice(conn, ctx.entity_id, existing["id"])
    customer_id = fd["crm_customer_id"]
    if not customer_id:
        s = q1(conn, "SELECT default_customer_code FROM fin_settings WHERE legal_entity_id=%s", (ctx.entity_id,))
        code = (s or {}).get("default_customer_code")
        row = q1(conn, "SELECT id FROM customers WHERE customer_code=%s", (code,)) if code else None
        if not row:
            raise FinError("MAPPING_MISSING", "Walk-in is not linked to a customer and no default customer is set",
                           {"frontdesk_invoice": fd["invoice_number"]})
        customer_id = row["id"]
    from src.routers.frontdesk import _resolve_item_sku  # reuse the dispatch matching rules
    lines = []
    for it in fd["items"] or []:
        q_ = float(it.get("quantity") or 0)
        if q_ <= 0:
            continue
        sku = _resolve_item_sku(it)
        if not sku or not q1(conn, "SELECT 1 FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku)):
            raise FinError("RESOURCE_NOT_FOUND", f"'{it.get('product')}' is not a product in ACE Books",
                           {"frontdesk_invoice": fd["invoice_number"], "product": it.get("product")})
        batch_id = None
        if it.get("batch_number"):
            batch_id = inventory.ensure_batch(conn, ctx.entity_id, sku, str(it["batch_number"]),
                                              expiry_date=_as_date(it.get("expiry_date")))
        lines.append({"line_type": "ITEM", "sku": sku, "quantity": q_, "unit_price": it.get("unit_price") or 0,
                      "description": it.get("product"), "batch_id": batch_id})
    if not lines:
        raise invalid("Frontdesk invoice has no priced lines")
    terms = None
    if (fd.get("payment_terms") or "").lower().startswith("due on receipt"):
        terms = 0
    # The Frontdesk invoice already carries its number in the client's sequence: keep it.
    number = str(fd["invoice_number"] or "")
    if not number.isdigit() or q1(conn, "SELECT 1 FROM fin_sales_invoices WHERE legal_entity_id=%s AND invoice_number=%s",
                                  (ctx.entity_id, number)):
        number = None
    inv = create_invoice(conn, ctx, {
        "customer_id": customer_id, "invoice_date": fd["inv_date"], "due_date": fd.get("due_date"), "terms_days": terms,
        "tax_total": fd.get("tax_amount") or 0, "reference": fd.get("customer_po"), "customer_po": fd.get("customer_po"),
        "shipping_method": fd.get("shipping_method"), "ship_to": fd.get("shipping_address"),
        "notes": None if number else f"From Frontdesk {fd['invoice_number']}", "lines": lines,
    }, source_type="FRONTDESK", source_id=str(fd["id"]), number=number)
    return post_invoice(conn, ctx, str(inv["id"]), override_credit=True,
                        override_reason="Approved by Finance on Frontdesk")


def _as_date(v: Any) -> Optional[dt.date]:
    if not v:
        return None
    try:
        return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
