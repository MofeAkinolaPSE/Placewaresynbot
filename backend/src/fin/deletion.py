"""Deleting a record entered by mistake (Maintain: items, lots, batches, vendors, customers, GL accounts).

The rule is Sage's: a record can be deleted only while nothing has been recorded against it - no stock,
invoice, bill, payment, journal, Sage history, QC registration or stock order. Once it has history it stays,
so the books, the audit trail and past invoices never lose what they point at; it is made inactive instead
(it then drops out of the pick lists).

`check(kind, id)` says what, if anything, still uses a record (the screen shows it before asking to delete);
`delete(kind, id)` deletes it, re-checking inside the transaction, with an audit entry that keeps a copy
of the deleted row.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.fin import audit
from src.fin.db import ex, q, q1
from src.fin.errors import FinError, not_found

# (what it is called on screen, table, condition on %(k)s - the record's key)
Check = Tuple[str, str, str]

ITEM: List[Check] = [
    ("stock on hand or stock received", "fin_cost_layers", "sku = %(k)s"),
    ("stock movements", "fin_inventory_transactions", "sku = %(k)s"),
    ("sales invoice lines", "fin_sales_invoice_lines", "sku = %(k)s"),
    ("Frontdesk invoices", "frontdesk_invoices", "items @> jsonb_build_array(jsonb_build_object('sku', %(k)s::text))"),
    ("supplier bill lines", "fin_supplier_bill_lines", "sku = %(k)s"),
    ("goods received", "fin_goods_receipts", "sku = %(k)s"),
    ("credit note lines", "fin_credit_note_lines", "sku = %(k)s"),
    ("debit note lines", "fin_debit_note_lines", "sku = %(k)s"),
    ("stock adjustments", "fin_stock_adjustment_lines", "sku = %(k)s"),
    ("stock counts", "fin_stock_count_lines", "sku = %(k)s"),
    ("stock on loan", "fin_stock_loans", "sku = %(k)s"),
    ("recalls", "fin_recalls", "sku = %(k)s"),
    ("recall lines", "fin_recall_items", "sku = %(k)s"),
    ("journal lines", "fin_journal_lines", "product_sku = %(k)s"),
    ("Sage sales history", "fin_sage_sales_lines", "sku = %(k)s"),
    ("Sage purchase history", "fin_sage_purchase_lines", "sku = %(k)s"),
    ("Sage stock history", "fin_sage_item_costing", "sku = %(k)s"),
    ("stock orders", "replenishment_requests", "sku = %(k)s"),
    ("QC batch registrations", "nafdac_batch_registry", "sku = %(k)s"),
]

BATCH: List[Check] = [
    ("stock received into it", "fin_cost_layers", "batch_id::text = %(k)s"),
    ("stock movements", "fin_inventory_transactions", "batch_id::text = %(k)s"),
    ("sales invoice lines", "fin_sales_invoice_lines", "batch_id::text = %(k)s"),
    ("supplier bill lines", "fin_supplier_bill_lines", "batch_id::text = %(k)s"),
    ("goods received", "fin_goods_receipts", "batch_id::text = %(k)s"),
    ("credit note lines", "fin_credit_note_lines", "batch_id::text = %(k)s"),
    ("debit note lines", "fin_debit_note_lines", "batch_id::text = %(k)s"),
    ("stock adjustments", "fin_stock_adjustment_lines", "batch_id::text = %(k)s"),
    ("stock counts", "fin_stock_count_lines", "batch_id::text = %(k)s"),
    ("stock on loan", "fin_stock_loans", "batch_id::text = %(k)s"),
    ("loan returns", "fin_stock_loan_returns", "batch_id::text = %(k)s"),
    ("recalls", "fin_recalls", "batch_id::text = %(k)s"),
    ("Sage sales history", "fin_sage_sales_lines", "batch_id::text = %(k)s"),
    ("Sage purchase history", "fin_sage_purchase_lines", "batch_id::text = %(k)s"),
    ("Sage stock history", "fin_sage_item_costing", "batch_id::text = %(k)s"),
    ("QC batch registrations", "nafdac_batch_registry", "fin_batch_id::text = %(k)s"),
    ("QC holds", "batch_status_locks", "batch_id = %(k)s"),
]

VENDOR: List[Check] = [
    ("supplier bills", "fin_supplier_bills", "supplier_id::text = %(k)s"),
    ("supplier payments", "fin_supplier_payments", "supplier_id::text = %(k)s"),
    ("debit notes", "fin_debit_notes", "supplier_id::text = %(k)s"),
    ("goods received", "fin_goods_receipts", "supplier_id::text = %(k)s"),
    ("batches", "fin_batches", "supplier_id::text = %(k)s"),
    ("stock movements", "fin_inventory_transactions", "supplier_id::text = %(k)s"),
    ("journal lines", "fin_journal_lines", "supplier_id::text = %(k)s"),
    ("recall returns", "fin_recall_supplier_returns", "supplier_id::text = %(k)s"),
    ("Sage ledger history", "fin_sage_party_ledger", "supplier_id::text = %(k)s"),
    ("Sage purchase history", "fin_sage_purchase_lines", "supplier_id::text = %(k)s"),
    ("stock orders", "replenishment_requests", "supplier_id::text = %(k)s"),
    ("QC batch registrations", "nafdac_batch_registry", "supplier_id::text = %(k)s"),
    ("deliveries", "supplier_deliveries", "supplier_id::text = %(k)s"),
    ("shipments", "placeware_shipments", "supplier_id::text = %(k)s"),
    ("payment requests", "fin_vendor_payment_requests",
     "vendor_id IN (%(k)s, (SELECT external_vendor_id FROM suppliers WHERE id::text = %(k)s))"),
]

CUSTOMER: List[Check] = [
    ("sales invoices", "fin_sales_invoices", "customer_id::text = %(k)s"),
    ("receipts", "fin_customer_receipts", "customer_id::text = %(k)s"),
    ("credit notes", "fin_credit_notes", "customer_id::text = %(k)s"),
    ("stock movements", "fin_inventory_transactions", "customer_id::text = %(k)s"),
    ("journal lines", "fin_journal_lines", "customer_id::text = %(k)s"),
    ("stock on loan", "fin_stock_loans", "customer_id::text = %(k)s"),
    ("recall lines", "fin_recall_items", "customer_id::text = %(k)s"),
    ("Sage ledger history", "fin_sage_party_ledger", "customer_id::text = %(k)s"),
    ("Sage sales history", "fin_sage_sales_lines", "customer_id::text = %(k)s"),
    ("Frontdesk walk-ins", "frontdesk_walk_ins", "customer_id::text = %(k)s"),
    ("AR receipts", "ar_receipts", "customer_id = %(k)s"),
    ("invoices", "placeware_invoices", "customer_id = %(k)s"),
    ("deals", "opportunities", "customer_id::text = %(k)s"),
    ("CRM activities", "crm_activities", "customer_id::text = %(k)s"),
]

ACCOUNT: List[Check] = [
    ("journal lines", "fin_journal_lines", "account_id::text = %(k)s"),
    ("sales invoice lines", "fin_sales_invoice_lines", "account_id::text = %(k)s"),
    ("supplier bill lines", "fin_supplier_bill_lines", "account_id::text = %(k)s"),
    ("credit note lines", "fin_credit_note_lines", "account_id::text = %(k)s"),
    ("debit note lines", "fin_debit_note_lines", "account_id::text = %(k)s"),
    ("cash voucher lines", "fin_cash_voucher_lines", "account_id::text = %(k)s"),
    ("budget lines", "fin_budget_lines", "account_id::text = %(k)s"),
    ("posting rules", "fin_account_mappings", "account_id::text = %(k)s"),
    ("bank accounts", "fin_bank_accounts", "gl_account_id::text = %(k)s"),
    ("fixed asset categories", "fin_asset_categories",
     "%(k)s IN (asset_account_id::text, disposal_account_id::text, dep_expense_account_id::text, accum_dep_account_id::text)"),
    ("inventory items", "fin_products",
     "%(k)s IN (revenue_account_id::text, inventory_account_id::text, cogs_account_id::text)"),
    ("accounts under it", "fin_accounts", "parent_id::text = %(k)s"),
    ("vendors (expense account)", "suppliers", "expense_account_code = (SELECT code FROM fin_accounts WHERE id::text = %(k)s)"),
    ("Sage journal history", "fin_sage_journal_lines", "account_code = (SELECT code FROM fin_accounts WHERE id::text = %(k)s)"),
    ("Sage ledger history", "fin_sage_gl_lines", "account_code = (SELECT code FROM fin_accounts WHERE id::text = %(k)s)"),
    ("Sage balances", "fin_sage_gl_balances", "account_code = (SELECT code FROM fin_accounts WHERE id::text = %(k)s)"),
]

_tables: Dict[str, bool] = {}


def _exists(conn, table: str) -> bool:
    if table not in _tables:
        _tables[table] = bool(q1(conn, "SELECT to_regclass(%s) AS t", (table,))["t"])
    return _tables[table]


def uses(conn, checks: List[Check], key: str) -> List[Dict[str, Any]]:
    """What still uses the record: [{what, count}], empty when it can be deleted."""
    out = []
    for what, table, cond in checks:
        if not _exists(conn, table):
            continue
        n = q1(conn, f"SELECT count(*) AS n FROM (SELECT 1 FROM {table} WHERE {cond} LIMIT 1000) x", {"k": key})["n"]
        if n:
            out.append({"what": what, "count": int(n)})
    return out


INACTIVE = "Make it inactive instead - it then drops out of the pick lists, and its history stays in the books."
INSTEAD = {
    "item": INACTIVE,
    "vendor": INACTIVE,
    "account": INACTIVE,
    "batch": "Its stock comes out by voiding the supplier's bill it was received on (or a stock adjustment); "
             "a wrong batch number or date is corrected in place.",
    "customer": "Correct its details instead - its invoices and history stay with it.",
}


def _verdict(used: List[Dict[str, Any]], name: str, kind: str) -> Dict[str, Any]:
    if not used:
        return {"can_delete": True, "used_by": [], "message": f"Nothing has been recorded against {name} - it can be deleted."}
    listed = ", ".join(f"{u['count']}{'+' if u['count'] >= 1000 else ''} {u['what']}" for u in used)
    return {"can_delete": False, "used_by": used, "instead": INSTEAD[kind],
            "message": f"{name} cannot be deleted: it is used on {listed}. {INSTEAD[kind]}"}


def _refuse(v: Dict[str, Any]) -> None:
    if not v["can_delete"]:
        raise FinError("INVALID_STATE_TRANSITION", v["message"], {"used_by": v["used_by"]})


# ---------------------------------------------------------------------------
# One function pair per record: what it is (the row, its name) and how it is deleted.
# ---------------------------------------------------------------------------

def _item(conn, ctx, sku: str) -> Dict[str, Any]:
    p = q1(conn, "SELECT * FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku))
    if not p:
        raise not_found("Item", sku)
    return p


def _item_uses(conn, ctx, sku: str) -> List[Dict[str, Any]]:
    used = uses(conn, ITEM, sku)
    # its batches are deleted with it - but only when none of them has history either
    n = sum(1 for b in q(conn, "SELECT id::text AS id FROM fin_batches WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku))
            if uses(conn, BATCH, b["id"]))
    if n:
        used.append({"what": "batch(es) with stock or history", "count": n})
    return used


def _batch(conn, ctx, batch_id: str) -> Dict[str, Any]:
    b = q1(conn, "SELECT * FROM fin_batches WHERE legal_entity_id=%s AND id::text=%s", (ctx.entity_id, batch_id))
    if not b:
        raise not_found("Batch", batch_id)
    return b


def _vendor(conn, ctx, vendor_id: str) -> Dict[str, Any]:
    v = q1(conn, "SELECT * FROM suppliers WHERE id::text=%s", (vendor_id,))
    if not v:
        raise not_found("Vendor", vendor_id)
    return v


def _customer(conn, ctx, customer_id: str) -> Dict[str, Any]:
    c = q1(conn, "SELECT * FROM customers WHERE id::text=%s", (str(customer_id),))
    if not c:
        raise not_found("Customer", customer_id)
    return c


def _account(conn, ctx, account_id: str) -> Dict[str, Any]:
    a = q1(conn, "SELECT * FROM fin_accounts WHERE legal_entity_id=%s AND id::text=%s", (ctx.entity_id, account_id))
    if not a:
        raise not_found("Account", account_id)
    return a


KINDS: Dict[str, Dict[str, Any]] = {
    "item": {"perm": "inventory.product.delete", "get": _item, "uses": _item_uses,
             "name": lambda r: f"Item {r['sku']}", "ref": lambda r: r["sku"], "entity": "product", "event": "ITEM_DELETED"},
    "batch": {"perm": "inventory.batch.delete", "get": _batch, "uses": lambda c, x, k: uses(c, BATCH, k),
              "name": lambda r: f"Batch {r.get('pack_batch_number') or r.get('lot_code') or r['batch_number']} of {r['sku']}",
              "ref": lambda r: r["batch_number"], "entity": "batch", "event": "BATCH_DELETED"},
    "vendor": {"perm": "payables.vendor.delete", "get": _vendor, "uses": lambda c, x, k: uses(c, VENDOR, k),
               "name": lambda r: f"Vendor {r['name']}", "ref": lambda r: r.get("external_vendor_id") or r["name"], "entity": "supplier",
               "event": "VENDOR_DELETED"},
    "customer": {"perm": "receivables.customer.delete", "get": _customer, "uses": lambda c, x, k: uses(c, CUSTOMER, k),
                 "name": lambda r: f"Customer {r['name']}", "ref": lambda r: r.get("customer_code") or r["name"], "entity": "customer",
                 "event": "CUSTOMER_DELETED"},
    "account": {"perm": "accounting.account.delete", "get": _account, "uses": lambda c, x, k: uses(c, ACCOUNT, k),
                "name": lambda r: f"Account {r['code']} {r['name']}", "ref": lambda r: r["code"], "entity": "account",
                "event": "ACCOUNT_DELETED"},
}


def _kind(kind: str) -> Dict[str, Any]:
    if kind not in KINDS:
        raise not_found("Record type", kind)
    return KINDS[kind]


def check(conn, ctx, kind: str, key: str) -> Dict[str, Any]:
    k = _kind(kind)
    row = k["get"](conn, ctx, key)
    v = _verdict(k["uses"](conn, ctx, key), k["name"](row), kind)
    v["allowed"] = ctx.can(k["perm"])
    return v


_REMOVE: Dict[str, Callable[[Any, Any, Dict[str, Any]], None]] = {
    "item": lambda c, x, r: (ex(c, "DELETE FROM fin_batches WHERE legal_entity_id=%s AND sku=%s", (x.entity_id, r["sku"])),
                             ex(c, "DELETE FROM fin_products WHERE id=%s", (r["id"],))),
    "batch": lambda c, x, r: ex(c, "DELETE FROM fin_batches WHERE id=%s", (r["id"],)),
    # a vendor named as an item's preferred vendor is only a preference: it is cleared
    "vendor": lambda c, x, r: (ex(c, "UPDATE fin_products SET preferred_supplier_id=NULL WHERE preferred_supplier_id=%s", (r["id"],)),
                               ex(c, "DELETE FROM suppliers WHERE id=%s", (r["id"],))),
    "customer": lambda c, x, r: ex(c, "DELETE FROM customers WHERE id=%s", (r["id"],)),
    "account": lambda c, x, r: ex(c, "DELETE FROM fin_accounts WHERE id=%s", (r["id"],)),
}


def delete(conn, ctx, kind: str, key: str, reason: Optional[str] = None) -> Dict[str, Any]:
    k = _kind(kind)
    ctx.require(k["perm"])
    row = k["get"](conn, ctx, key)
    v = _verdict(k["uses"](conn, ctx, key), k["name"](row), kind)
    _refuse(v)
    _REMOVE[kind](conn, ctx, row)
    audit.record(conn, ctx, k["event"], k["entity"], str(row["id"]), ref=k["ref"](row),
                 before={kk: vv for kk, vv in row.items() if kk not in ("embedding",)}, reason=reason)
    return {"deleted": True, "kind": kind, "id": str(row["id"]), "message": f"{k['name'](row)} deleted"}
