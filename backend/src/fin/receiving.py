"""Goods received before the supplier's bill - Sage's Receive Inventory with "Waiting on bill" (28 Oct 2026).

QC registers an incoming batch (supplier, item, batch, dates); when it arrives, "Confirm arrived" receives
it here: the stock goes into its batch at once (QUARANTINED until QC releases it - quality_hub.sync_batches)
and the books record goods received with the bill to come:

    Dr  inventory (the item's account)      Cr  goods-received accrual (GOODS_RECEIVED_ACCRUAL)

Purchases & Payables lists the receipt as "Received - waiting on the supplier's bill" until finance records
the bill; the bill's line for it clears the accrual (Dr accrual, Cr accounts payable) instead of receiving the
stock again - any difference between the bill and the receipt cost goes to the item's cost of sales.
"""
import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, inventory, posting, rules
from src.fin.db import ZERO, ex, money, q, q1, qty
from src.fin.errors import FinError, invalid, not_found


def _d(v: Any) -> Optional[dt.date]:
    if not v:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def receive_arrival(conn, ctx, registry_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Receive a registered incoming batch that has arrived."""
    if not (ctx.can("inventory.receipt.create") or ctx.can("payables.bill.create")):
        ctx.require("inventory.receipt.create")
    r = q1(conn, "SELECT * FROM nafdac_batch_registry WHERE id::text=%s FOR UPDATE", (registry_id,))
    if not r:
        raise not_found("Incoming batch", registry_id)
    if r.get("goods_receipt_id"):
        raise FinError("INVALID_STATE_TRANSITION", f"Batch {r['batch_number']} has already been received")
    supplier_id = data.get("supplier_id") or r.get("supplier_id")
    if not supplier_id:
        raise invalid("Choose the supplier it came from")
    s = q1(conn, "SELECT id, name FROM suppliers WHERE id::text=%s", (str(supplier_id),))
    if not s:
        raise invalid("That supplier is not in the vendor list")
    sku = r["sku"]
    rules.product(conn, ctx.entity_id, sku)
    quantity = qty(data.get("quantity") if data.get("quantity") not in (None, "") else r.get("quantity"))
    if not quantity or quantity <= 0:
        raise invalid("Give the quantity that arrived")
    unit_cost = data.get("unit_cost") if data.get("unit_cost") not in (None, "") else r.get("unit_cost")
    if unit_cost in (None, ""):
        unit_cost = inventory.last_unit_cost(conn, ctx.entity_id, sku)
    if unit_cost in (None, ""):
        raise invalid("Give the unit cost (as on the supplier's invoice)")
    unit_cost = Decimal(str(unit_cost))
    if unit_cost < 0:
        raise invalid("The unit cost cannot be negative")
    on = _d(data.get("received_date")) or dt.date.today()
    batch_number = str(data.get("batch_number") or r["batch_number"]).strip()
    if not batch_number or batch_number.startswith("TBC-"):
        raise invalid("Give the batch number printed on the pack")
    if batch_number != r["batch_number"]:
        ex(conn, "UPDATE nafdac_batch_registry SET batch_number=%s WHERE id::text=%s", (batch_number, registry_id))
    expiry = _d(data.get("expiry_date")) or r.get("expiry_date")
    mfd = _d(data.get("manufacture_date")) or r.get("manufacture_date")
    if expiry and mfd and mfd >= expiry:
        raise invalid("The manufacture date must be before the expiry date")
    inv_no = (data.get("supplier_invoice_number") or r.get("supplier_invoice_number") or "").strip() or None
    batch_id = inventory.ensure_batch(conn, ctx.entity_id, sku, batch_number, expiry_date=expiry, manufacture_date=mfd,
                                      supplier_id=str(s["id"]))
    # the number on the pack and the dates show on the batch (Maintain -> Inventory Items -> Batches) at once
    ex(conn, """UPDATE fin_batches SET pack_batch_number=COALESCE(pack_batch_number, %s), manufacture_date=COALESCE(manufacture_date, %s),
                expiry_date=COALESCE(expiry_date, %s), supplier_id=COALESCE(supplier_id, %s) WHERE id=%s""",
       (batch_number, mfd, expiry, str(s["id"]), batch_id))
    total = money(quantity * unit_cost)
    gr = q1(conn, """INSERT INTO fin_goods_receipts (legal_entity_id, registry_id, supplier_id, supplier_invoice_number, sku, batch_id,
                     quantity, unit_cost, total, received_date, notes, created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (ctx.entity_id, registry_id, str(s["id"]), inv_no, sku, batch_id, quantity, unit_cost, total, on, data.get("notes"), ctx.actor_id))
    t = inventory.receive(conn, ctx, sku=sku, quantity=quantity, unit_cost=unit_cost, txn_type="PURCHASE", txn_date=on, batch_id=batch_id,
                          source_type="GOODS_RECEIPT", source_id=gr["id"], reference=inv_no or batch_number,
                          supplier_id=str(s["id"]), total_cost=total, reason="Received - waiting on the supplier's bill")
    acc = rules.product_accounts(conn, ctx.entity_id, sku)
    grni = rules.account(conn, ctx.entity_id, "GOODS_RECEIVED_ACCRUAL")
    j = posting.post_system(conn, ctx, event_type="GOODS_RECEIVED", journal_date=on, lines=[
        {"account_id": acc["inventory_account_id"], "debit": total, "product_sku": sku, "supplier_id": str(s["id"]),
         "description": f"{sku} batch {batch_number} received from {s['name']}"},
        {"account_id": grni["id"], "credit": total, "supplier_id": str(s["id"]),
         "description": f"{s['name']}{' inv ' + inv_no if inv_no else ''} - bill to come"}],
        description=f"Goods received: {quantity:f} {sku} from {s['name']} (bill to come)", source_type="GOODS_RECEIPT",
        source_id=gr["id"], source_ref=inv_no or batch_number)
    inventory.link_journal(conn, [str(t["id"])], j["id"])
    ex(conn, "UPDATE fin_goods_receipts SET inventory_txn_id=%s, journal_id=%s WHERE id=%s", (t["id"], j["id"], gr["id"]))
    ex(conn, """UPDATE nafdac_batch_registry SET arrived_at=now(), goods_receipt_id=%s, fin_batch_id=%s, quantity=%s, unit_cost=%s,
                supplier_id=%s, supplier=%s, supplier_invoice_number=COALESCE(%s, supplier_invoice_number), updated_at=now() WHERE id::text=%s""",
       (gr["id"], batch_id, quantity, unit_cost, str(s["id"]), s["name"], inv_no, registry_id))
    # held until QC releases it (a registered batch is pending until then)
    if r.get("status") in ("pending", None):
        ex(conn, "UPDATE fin_batches SET status='QUARANTINED' WHERE id=%s AND status='AVAILABLE'", (batch_id,))
    audit.record(conn, ctx, "GOODS_RECEIVED", "goods_receipt", str(gr["id"]), ref=inv_no or batch_number,
                 metadata={"sku": sku, "quantity": str(quantity), "total": str(total), "journal": j["journal_number"]})
    return get_receipt(conn, ctx.entity_id, str(gr["id"]))


def get_receipt(conn, e: str, gr_id: str) -> Dict[str, Any]:
    gr = q1(conn, """SELECT g.*, g.id::text AS id, s.name AS supplier_name, s.external_vendor_id AS vendor_id, p.name AS product_name,
                            b.batch_number, b.pack_batch_number, b.manufacture_date, b.expiry_date, b.status AS batch_status,
                            j.journal_number, sb.bill_number
                     FROM fin_goods_receipts g LEFT JOIN suppliers s ON s.id=g.supplier_id
                     LEFT JOIN fin_products p ON p.legal_entity_id=g.legal_entity_id AND p.sku=g.sku
                     LEFT JOIN fin_batches b ON b.id=g.batch_id LEFT JOIN fin_journals j ON j.id=g.journal_id
                     LEFT JOIN fin_supplier_bills sb ON sb.id=g.bill_id
                     WHERE g.id::text=%s AND g.legal_entity_id=%s""", (gr_id, e))
    if not gr:
        raise not_found("Goods received", gr_id)
    return gr


def awaiting_bill(conn, e: str, supplier_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Goods received with the supplier's bill still to come (newest first)."""
    return q(conn, """SELECT g.id::text AS id, g.supplier_id::text AS supplier_id, s.name AS supplier_name, s.external_vendor_id AS vendor_id,
                             g.supplier_invoice_number, g.sku, p.name AS product_name, g.quantity, g.unit_cost, g.total, g.received_date,
                             g.batch_id::text AS batch_id, b.batch_number, b.manufacture_date, b.expiry_date, b.status AS batch_status
                      FROM fin_goods_receipts g LEFT JOIN suppliers s ON s.id=g.supplier_id
                      LEFT JOIN fin_products p ON p.legal_entity_id=g.legal_entity_id AND p.sku=g.sku
                      LEFT JOIN fin_batches b ON b.id=g.batch_id
                      WHERE g.legal_entity_id=%s AND g.status='RECEIVED' AND (%s::text IS NULL OR g.supplier_id::text=%s)
                      ORDER BY g.received_date DESC, g.created_at DESC""", (e, supplier_id, supplier_id))


def bill_line_for_receipt(conn, ctx, gr_id: str, supplier_id: str) -> Dict[str, Any]:
    """The receipt a bill line clears (it must be this supplier's and still waiting)."""
    gr = q1(conn, "SELECT * FROM fin_goods_receipts WHERE id::text=%s AND legal_entity_id=%s FOR UPDATE", (gr_id, ctx.entity_id))
    if not gr or gr["status"] != "RECEIVED":
        raise invalid("That delivery is not waiting for a bill (already billed or undone)")
    if str(gr["supplier_id"]) != str(supplier_id):
        raise invalid("That delivery came from another supplier")
    return gr


def undo_arrival(conn, ctx, gr_id: str, reason: str) -> Dict[str, Any]:
    """An arrival confirmed by mistake: the stock comes back out and the accrual is reversed (not once billed or sold)."""
    if not (ctx.can("inventory.receipt.create") or ctx.can("payables.bill.create")):
        ctx.require("inventory.receipt.create")
    if not (reason or "").strip():
        raise invalid("Say why the arrival is being undone")
    gr = q1(conn, "SELECT * FROM fin_goods_receipts WHERE id::text=%s AND legal_entity_id=%s FOR UPDATE", (gr_id, ctx.entity_id))
    if not gr:
        raise not_found("Goods received", gr_id)
    if gr["status"] != "RECEIVED":
        raise FinError("INVALID_STATE_TRANSITION", "Only a delivery still waiting for its bill can be undone - void the bill first")
    layer = q1(conn, "SELECT qty_in, qty_remaining FROM fin_cost_layers WHERE inventory_txn_id=%s", (gr["inventory_txn_id"],))
    if layer and layer["qty_remaining"] < layer["qty_in"]:
        raise FinError("INVALID_STATE_TRANSITION", "Some of this delivery has already been sold or used")
    rev = posting.reverse(conn, ctx, str(gr["journal_id"]), reversal_date=gr["received_date"], reason=f"Arrival undone: {reason}",
                          allow_system=True)
    t = inventory.issue(conn, ctx, sku=gr["sku"], quantity=gr["quantity"], txn_type="RETURN_OUT", txn_date=gr["received_date"],
                        batch_id=str(gr["batch_id"]) if gr["batch_id"] else None, source_type="GOODS_RECEIPT_VOID", source_id=gr["id"],
                        reference=gr["supplier_invoice_number"], supplier_id=str(gr["supplier_id"]), reason=reason)
    inventory.link_journal(conn, [str(t["id"])], rev["id"])
    ex(conn, "UPDATE fin_goods_receipts SET status='VOID', notes=COALESCE(notes,'') || %s WHERE id=%s", (f" [undone: {reason}]", gr["id"]))
    ex(conn, "UPDATE nafdac_batch_registry SET arrived_at=NULL, goods_receipt_id=NULL, updated_at=now() WHERE goods_receipt_id=%s", (gr["id"],))
    audit.record(conn, ctx, "GOODS_RECEIPT_UNDONE", "goods_receipt", str(gr["id"]), reason=reason)
    return get_receipt(conn, ctx.entity_id, str(gr["id"]))
