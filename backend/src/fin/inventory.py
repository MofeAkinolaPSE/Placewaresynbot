"""Inventory accounting: every stock movement has a cost and, where it
changes what the business owns or spends, a journal (meeting 2: "everything
that goes in or out has to reflect on the account").

Valuation: FIFO by cost layer (the client's Sage items use FIFO), with
batch-specific consumption when a batch is named - pharma sales are batch
tracked, so the layer consumed is the batch actually shipped.

Movements are also mirrored into ACE's operational stock feed
(placeware_inventory_events) so the existing Inventory screens stay in step,
except sales raised from Frontdesk, which the dispatch step already records.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, posting, rules
from src.fin.db import ZERO, ex, money, q, q1, qty
from src.fin.errors import FinError, invalid, not_found
from src.fin.numbering import next_number

INBOUND = {"OPENING_BALANCE", "PURCHASE", "RETURN_IN", "LOAN_RETURN", "TRANSFER_IN"}
OUTBOUND = {"SALE", "RETURN_OUT", "DAMAGE", "EXPIRY", "LOAN_OUT", "TRANSFER_OUT", "RECALL"}
# ADJUSTMENT / STOCK_COUNT / BATCH_REPLACEMENT may go either way.

# fin movement -> operational event type (placeware_inventory_events CHECK)
_OPS_TYPE = {"PURCHASE": "RESTOCK", "RETURN_IN": "RESTOCK", "LOAN_RETURN": "RESTOCK", "SALE": "SALE",
             "DAMAGE": "DAMAGE", "EXPIRY": "EXPIRY", "RETURN_OUT": "ADJUSTMENT", "LOAN_OUT": "ADJUSTMENT",
             "ADJUSTMENT": "ADJUSTMENT", "STOCK_COUNT": "ADJUSTMENT", "RECALL": "ADJUSTMENT"}


# ---------------------------------------------------------------------------
# Batches & balances
# ---------------------------------------------------------------------------

def ensure_batch(conn, entity_id: str, sku: str, batch_number: Optional[str], *,
                 expiry_date: Optional[dt.date] = None, manufacture_date: Optional[dt.date] = None,
                 supplier_id: Optional[str] = None) -> Optional[str]:
    if not batch_number:
        return None
    b = q1(conn, "SELECT id, expiry_date FROM fin_batches WHERE legal_entity_id=%s AND sku=%s AND batch_number=%s",
           (entity_id, sku, batch_number.strip()))
    if b:
        if expiry_date and not b["expiry_date"]:
            ex(conn, "UPDATE fin_batches SET expiry_date=%s WHERE id=%s", (expiry_date, b["id"]))
        return str(b["id"])
    b = q1(conn, """INSERT INTO fin_batches (legal_entity_id, sku, batch_number, expiry_date, manufacture_date, supplier_id)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
           (entity_id, sku, batch_number.strip(), expiry_date, manufacture_date, supplier_id))
    return str(b["id"])


def on_hand(conn, entity_id: str, sku: str, batch_id: Optional[str] = None) -> Dict[str, Decimal]:
    params: List[Any] = [entity_id, sku]
    bf = ""
    if batch_id:
        bf = " AND batch_id=%s"
        params.append(batch_id)
    r = q1(conn, f"""SELECT COALESCE(SUM(qty_remaining),0) q, COALESCE(SUM(qty_remaining*unit_cost),0) v
                     FROM fin_cost_layers WHERE legal_entity_id=%s AND sku=%s {bf}""", params)
    return {"quantity": qty(r["q"]), "value": money(r["v"])}


def last_unit_cost(conn, entity_id: str, sku: str) -> Decimal:
    r = q1(conn, """SELECT unit_cost FROM fin_cost_layers WHERE legal_entity_id=%s AND sku=%s
                    ORDER BY layer_date DESC, inventory_txn_id DESC LIMIT 1""", (entity_id, sku))
    return Decimal(str(r["unit_cost"])) if r else Decimal("0")


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------

def _mirror_ops(conn, ctx, sku: str, quantity: Decimal, txn_type: str, reference: str, source_type: str) -> None:
    if source_type == "FRONTDESK" or txn_type in ("OPENING_BALANCE", "BATCH_REPLACEMENT", "TRANSFER_IN", "TRANSFER_OUT"):
        return
    ops = _OPS_TYPE.get(txn_type)
    if not ops:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT ops_mirror")
            cur.execute("""INSERT INTO placeware_inventory_events (sku, quantity_change, event_type, reference, performed_by)
                           VALUES (%s,%s,%s,%s,%s)""", (sku, quantity, ops, reference, ctx.actor_id))
            cur.execute("RELEASE SAVEPOINT ops_mirror")
    except Exception:
        # The operational feed is a convenience view; never let it block posting.
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT ops_mirror")


def receive(conn, ctx, *, sku: str, quantity: Any, unit_cost: Any, txn_type: str, txn_date: dt.date,
            batch_id: Optional[str] = None, source_type: str, source_id: Any, reference: Optional[str] = None,
            reason: Optional[str] = None, customer_id: Any = None, supplier_id: Any = None,
            mirror: bool = True, total_cost: Any = None) -> Dict[str, Any]:
    qn = qty(quantity)
    uc = Decimal(str(unit_cost or 0))
    if qn <= 0:
        raise invalid(f"Inbound quantity for {sku} must be positive")
    if uc < 0:
        raise invalid(f"Unit cost for {sku} cannot be negative")
    rules.product(conn, ctx.entity_id, sku)
    # An exact total (e.g. a supplier line or a migrated valuation) wins over qty x unit,
    # so the ledger carries the kobo the source document says.
    total = money(total_cost) if total_cost is not None else money(qn * uc)
    t = q1(conn, """
        INSERT INTO fin_inventory_transactions (legal_entity_id, txn_date, sku, batch_id, txn_type, quantity, unit_cost,
            total_cost, source_type, source_id, reference, reason, customer_id, supplier_id, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
    """, (ctx.entity_id, txn_date, sku, batch_id, txn_type, qn, uc, total, source_type, str(source_id),
          reference, reason, customer_id, supplier_id, ctx.actor_id))
    ex(conn, """INSERT INTO fin_cost_layers (legal_entity_id, sku, batch_id, inventory_txn_id, layer_date, qty_in,
                qty_remaining, unit_cost) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
       (ctx.entity_id, sku, batch_id, t["id"], txn_date, qn, qn, uc))
    if mirror:
        _mirror_ops(conn, ctx, sku, qn, txn_type, reference or str(source_id), source_type)
    return t


def issue(conn, ctx, *, sku: str, quantity: Any, txn_type: str, txn_date: dt.date, batch_id: Optional[str] = None,
          source_type: str, source_id: Any, reference: Optional[str] = None, reason: Optional[str] = None,
          customer_id: Any = None, supplier_id: Any = None, mirror: bool = True) -> Dict[str, Any]:
    """Take stock out at FIFO cost (from the named batch if given)."""
    qn = qty(quantity)
    if qn <= 0:
        raise invalid(f"Outbound quantity for {sku} must be positive")
    rules.product(conn, ctx.entity_id, sku)
    params: List[Any] = [ctx.entity_id, sku]
    bf = ""
    # Stock that leaves to a customer (sale, loan) never comes from a lot that is recalled,
    # quarantined (awaiting / failed QC release), damaged or past its expiry date. Write-offs,
    # returns to supplier and counts may still take those lots.
    to_customer = txn_type in ("SALE", "LOAN_OUT")
    if batch_id:
        bf = " AND batch_id=%s"
        params.append(batch_id)
    elif to_customer:
        bf = """ AND (batch_id IS NULL OR batch_id IN (SELECT id FROM fin_batches WHERE status='AVAILABLE'
                                                       AND (expiry_date IS NULL OR expiry_date >= %s)))"""
        params.append(txn_date)
    layers = q(conn, f"""SELECT id, batch_id, qty_remaining, unit_cost FROM fin_cost_layers
                         WHERE legal_entity_id=%s AND sku=%s {bf} AND qty_remaining > 0
                         ORDER BY layer_date, id FOR UPDATE""", params)
    available = sum((Decimal(str(l["qty_remaining"])) for l in layers), Decimal("0"))
    if available < qn:
        where = f" in batch {_batch_no(conn, batch_id)}" if batch_id else (" that can be sold (recalled, quarantined and expired lots excluded)"
                                                                             if to_customer else "")
        raise FinError("INSUFFICIENT_STOCK", f"Only {available:g} of {sku} on hand{where}; {qn:g} requested",
                       {"sku": sku, "available": str(available), "requested": str(qn), "batch_id": batch_id})
    need, cost, used = qn, Decimal("0"), []
    for l in layers:
        if need <= 0:
            break
        take = min(need, Decimal(str(l["qty_remaining"])))
        uc = Decimal(str(l["unit_cost"]))
        used.append((l["id"], take, uc))
        cost += take * uc
        need -= take
    total = money(cost)
    unit = (cost / qn) if qn else Decimal("0")
    t = q1(conn, """
        INSERT INTO fin_inventory_transactions (legal_entity_id, txn_date, sku, batch_id, txn_type, quantity, unit_cost,
            total_cost, source_type, source_id, reference, reason, customer_id, supplier_id, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
    """, (ctx.entity_id, txn_date, sku, batch_id, txn_type, -qn, unit, -total, source_type, str(source_id),
          reference, reason, customer_id, supplier_id, ctx.actor_id))
    with conn.cursor() as cur:
        for layer_id, take, uc in used:
            cur.execute("UPDATE fin_cost_layers SET qty_remaining = qty_remaining - %s WHERE id=%s", (take, layer_id))
            cur.execute("INSERT INTO fin_layer_consumptions (layer_id, inventory_txn_id, quantity, unit_cost) VALUES (%s,%s,%s,%s)",
                        (layer_id, t["id"], take, uc))
    if mirror:
        _mirror_ops(conn, ctx, sku, -qn, txn_type, reference or str(source_id), source_type)
    t["cost"] = total
    return t


def restore(conn, ctx, *, original_txn_id: str, quantity: Any, txn_type: str, txn_date: dt.date,
            batch_id: Optional[str] = None, source_type: str, source_id: Any, reference: Optional[str] = None,
            reason: Optional[str] = None, customer_id: Any = None) -> Dict[str, Any]:
    """Bring stock back at the cost it left with (returns, loan returns)."""
    orig = q1(conn, "SELECT * FROM fin_inventory_transactions WHERE id=%s AND legal_entity_id=%s",
              (original_txn_id, ctx.entity_id))
    if not orig:
        raise not_found("Original stock movement", original_txn_id)
    unit = abs(Decimal(str(orig["total_cost"]))) / abs(Decimal(str(orig["quantity"])))
    return receive(conn, ctx, sku=orig["sku"], quantity=quantity, unit_cost=unit, txn_type=txn_type,
                   txn_date=txn_date, batch_id=batch_id or (str(orig["batch_id"]) if orig["batch_id"] else None),
                   source_type=source_type, source_id=source_id, reference=reference, reason=reason,
                   customer_id=customer_id)


def _batch_no(conn, batch_id: Optional[str]) -> str:
    if not batch_id:
        return ""
    b = q1(conn, "SELECT batch_number FROM fin_batches WHERE id=%s", (batch_id,))
    return b["batch_number"] if b else str(batch_id)


def link_journal(conn, txn_ids: List[str], journal_id: str) -> None:
    if txn_ids:
        ex(conn, "UPDATE fin_inventory_transactions SET journal_id=%s WHERE id = ANY(%s::uuid[]) AND journal_id IS NULL",
           (journal_id, txn_ids))


# ---------------------------------------------------------------------------
# Stock adjustments (damage, expiry, shortage, excess, count corrections)
# ---------------------------------------------------------------------------

def create_adjustment(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.adjustment.create")
    lines = data.get("lines") or []
    if not lines:
        raise invalid("An adjustment needs at least one line")
    reason = str(data.get("reason_code") or "").upper()
    if reason not in ("DAMAGE", "EXPIRY", "SHORTAGE", "EXCESS", "COUNT_CORRECTION", "DATA_CORRECTION", "OTHER"):
        raise invalid("Choose a reason: damage, expiry, shortage, excess, count correction, data correction or other")
    number = next_number(conn, ctx.entity_id, "INVENTORY")
    adj = q1(conn, """INSERT INTO fin_stock_adjustments (legal_entity_id, adjustment_number, adjustment_date,
                      reason_code, notes, created_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
             (ctx.entity_id, number, data["adjustment_date"], reason, data.get("notes"), ctx.actor_id))
    for i, l in enumerate(lines, start=1):
        sku = str(l["sku"]).strip()
        rules.product(conn, ctx.entity_id, sku)
        qn = qty(l["quantity"])
        if qn == 0:
            raise invalid(f"Line {i}: quantity cannot be zero")
        if reason in ("DAMAGE", "EXPIRY", "SHORTAGE") and qn > 0:
            raise invalid(f"Line {i}: {reason.lower()} reduces stock - enter a negative quantity")
        batch_id = l.get("batch_id") or ensure_batch(conn, ctx.entity_id, sku, l.get("batch_number"))
        ex(conn, """INSERT INTO fin_stock_adjustment_lines (adjustment_id, line_no, sku, batch_id, quantity, unit_cost, reason)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
           (adj["id"], i, sku, batch_id, qn, l.get("unit_cost"), l.get("reason")))
    audit.record(conn, ctx, "STOCK_ADJUSTMENT_CREATED", "stock_adjustment", adj["id"], ref=number,
                 after={"reason": reason, "lines": len(lines)})
    return get_adjustment(conn, ctx.entity_id, adj["id"])


def get_adjustment(conn, entity_id: str, adj_id: str) -> Dict[str, Any]:
    a = q1(conn, "SELECT * FROM fin_stock_adjustments WHERE id=%s AND legal_entity_id=%s", (adj_id, entity_id))
    if not a:
        raise not_found("Stock adjustment", adj_id)
    a["lines"] = q(conn, """SELECT l.*, b.batch_number, p.name AS product_name FROM fin_stock_adjustment_lines l
                            LEFT JOIN fin_batches b ON b.id=l.batch_id
                            LEFT JOIN fin_products p ON p.legal_entity_id=%s AND p.sku=l.sku
                            WHERE l.adjustment_id=%s ORDER BY l.line_no""", (entity_id, adj_id))
    return a


def post_adjustment(conn, ctx, adj_id: str, *, approved_by_count: bool = False) -> Dict[str, Any]:
    ctx.require("inventory.adjustment.approve")
    a = q1(conn, "SELECT * FROM fin_stock_adjustments WHERE id=%s AND legal_entity_id=%s FOR UPDATE",
           (adj_id, ctx.entity_id))
    if not a:
        raise not_found("Stock adjustment", adj_id)
    if a["status"] == "POSTED":
        return get_adjustment(conn, ctx.entity_id, adj_id)
    if a["status"] != "DRAFT":
        raise FinError("INVALID_STATE_TRANSITION", f"A {a['status'].lower()} adjustment cannot be posted")
    if a["created_by"] == ctx.actor_id and not approved_by_count and not _self_ok(conn, ctx):
        raise FinError("PERMISSION_DENIED", "Another person must approve a stock adjustment you raised")
    adj_acct = rules.account(conn, ctx.entity_id, "INVENTORY_ADJUSTMENT")
    txn_type = {"DAMAGE": "DAMAGE", "EXPIRY": "EXPIRY", "COUNT_CORRECTION": "STOCK_COUNT"}.get(a["reason_code"], "ADJUSTMENT")
    jl, txns, total = [], [], ZERO
    for l in q(conn, "SELECT * FROM fin_stock_adjustment_lines WHERE adjustment_id=%s ORDER BY line_no", (adj_id,)):
        acc = rules.product_accounts(conn, ctx.entity_id, l["sku"])
        qn = Decimal(str(l["quantity"]))
        if qn < 0:
            t = issue(conn, ctx, sku=l["sku"], quantity=-qn, txn_type=txn_type, txn_date=a["adjustment_date"],
                      batch_id=str(l["batch_id"]) if l["batch_id"] else None, source_type="STOCK_ADJUSTMENT",
                      source_id=adj_id, reference=a["adjustment_number"], reason=l["reason"] or a["reason_code"])
            value = -t["cost"]
        else:
            uc = Decimal(str(l["unit_cost"])) if l["unit_cost"] is not None else last_unit_cost(conn, ctx.entity_id, l["sku"])
            t = receive(conn, ctx, sku=l["sku"], quantity=qn, unit_cost=uc, txn_type=txn_type,
                        txn_date=a["adjustment_date"], batch_id=str(l["batch_id"]) if l["batch_id"] else None,
                        source_type="STOCK_ADJUSTMENT", source_id=adj_id, reference=a["adjustment_number"],
                        reason=l["reason"] or a["reason_code"])
            value = money(t["total_cost"])
        txns.append(str(t["id"]))
        ex(conn, "UPDATE fin_stock_adjustment_lines SET value=%s, unit_cost=%s, inventory_txn_id=%s WHERE id=%s",
           (value, t["unit_cost"], t["id"], l["id"]))
        total += value
        if value < 0:
            jl += [{"account_id": adj_acct["id"], "debit": -value, "product_sku": l["sku"],
                    "description": f"{a['reason_code'].title()} {l['sku']}"},
                   {"account_id": acc["inventory_account_id"], "credit": -value, "product_sku": l["sku"]}]
        elif value > 0:
            jl += [{"account_id": acc["inventory_account_id"], "debit": value, "product_sku": l["sku"]},
                   {"account_id": adj_acct["id"], "credit": value, "product_sku": l["sku"],
                    "description": f"{a['reason_code'].title()} {l['sku']}"}]
    journal = None
    if jl:
        journal = posting.post_system(conn, ctx, event_type="INVENTORY_ADJUSTED", journal_date=a["adjustment_date"],
                                      lines=jl, description=f"Stock adjustment {a['adjustment_number']} ({a['reason_code'].lower()})",
                                      source_type="STOCK_ADJUSTMENT", source_id=adj_id, source_ref=a["adjustment_number"])
        link_journal(conn, txns, journal["id"])
    ex(conn, """UPDATE fin_stock_adjustments SET status='POSTED', total_value=%s, journal_id=%s, posted_by=%s,
                posted_at=now() WHERE id=%s""", (total, journal["id"] if journal else None, ctx.actor_id, adj_id))
    audit.record(conn, ctx, "STOCK_ADJUSTMENT_POSTED", "stock_adjustment", adj_id, ref=a["adjustment_number"],
                 metadata={"value": str(total)})
    return get_adjustment(conn, ctx.entity_id, adj_id)


def _self_ok(conn, ctx) -> bool:
    s = q1(conn, "SELECT allow_self_approval FROM fin_settings WHERE legal_entity_id=%s", (ctx.entity_id,))
    return bool(s and s["allow_self_approval"])


# ---------------------------------------------------------------------------
# Stock counts -> count-correction adjustment
# ---------------------------------------------------------------------------

def create_count(conn, ctx, count_date: dt.date, skus: Optional[List[str]] = None, notes: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("inventory.count.create")
    number = next_number(conn, ctx.entity_id, "STOCK_COUNT")
    c = q1(conn, """INSERT INTO fin_stock_counts (legal_entity_id, count_number, count_date, notes, created_by)
                    VALUES (%s,%s,%s,%s,%s) RETURNING *""", (ctx.entity_id, number, count_date, notes, ctx.actor_id))
    params: List[Any] = [ctx.entity_id]
    sf = ""
    if skus:
        sf = " AND sku = ANY(%s)"
        params.append(skus)
    for r in q(conn, f"""SELECT sku, batch_id, SUM(qty_remaining) q FROM fin_cost_layers
                         WHERE legal_entity_id=%s {sf} GROUP BY sku, batch_id HAVING SUM(qty_remaining) <> 0""", params):
        ex(conn, "INSERT INTO fin_stock_count_lines (count_id, sku, batch_id, system_qty) VALUES (%s,%s,%s,%s)",
           (c["id"], r["sku"], r["batch_id"], r["q"]))
    audit.record(conn, ctx, "STOCK_COUNT_CREATED", "stock_count", c["id"], ref=number)
    return get_count(conn, ctx.entity_id, c["id"])


def count_overview(conn, entity_id: str) -> Dict[str, Any]:
    """What a stock count covers, before any count exists: the book quantity and value of every
    item and batch, its expiry and status, when the item was last counted, and the lots the books
    show as short (sold below zero in Sage - a count is how they are corrected)."""
    rows = q(conn, """
        SELECT l.sku, p.name AS product_name, l.batch_id, b.batch_number, b.pack_batch_number, b.expiry_date,
               COALESCE(b.status, 'AVAILABLE') AS batch_status,
               SUM(l.qty_remaining) AS book_qty, SUM(l.qty_remaining * l.unit_cost) AS book_value,
               lc.last_counted
        FROM fin_cost_layers l
        LEFT JOIN fin_batches b ON b.id = l.batch_id
        LEFT JOIN fin_products p ON p.legal_entity_id = l.legal_entity_id AND p.sku = l.sku
        LEFT JOIN LATERAL (SELECT MAX(c.count_date) AS last_counted FROM fin_stock_count_lines cl
                           JOIN fin_stock_counts c ON c.id = cl.count_id AND c.status = 'POSTED'
                           WHERE cl.sku = l.sku) lc ON TRUE
        WHERE l.legal_entity_id = %s
        GROUP BY l.sku, p.name, l.batch_id, b.batch_number, b.pack_batch_number, b.expiry_date, b.status, lc.last_counted
        HAVING SUM(l.qty_remaining) <> 0
        ORDER BY l.sku, b.expiry_date NULLS LAST""", (entity_id,))
    short = q(conn, """SELECT id::text AS id, title, amount, quantity, detail->>'sku' AS sku
                       FROM fin_data_exceptions WHERE legal_entity_id=%s AND kind='STOCK_SHORT_LOT' AND status='OPEN'
                       ORDER BY amount DESC NULLS LAST""", (entity_id,))
    today = dt.date.today()
    for r in rows:
        r["expired"] = bool(r["expiry_date"] and r["expiry_date"] < today)
    return {"lines": rows, "short_lots": short,
            "summary": {"items": len({r["sku"] for r in rows}), "lines": len(rows),
                        "book_value": sum((Decimal(str(r["book_value"] or 0)) for r in rows), Decimal("0")),
                        "expired_lines": sum(1 for r in rows if r["expired"]),
                        "blocked_lines": sum(1 for r in rows if r["batch_status"] != "AVAILABLE"),
                        "never_counted": len({r["sku"] for r in rows if not r["last_counted"]}),
                        "short_lots": len(short)}}


def get_count(conn, entity_id: str, count_id: str) -> Dict[str, Any]:
    c = q1(conn, "SELECT * FROM fin_stock_counts WHERE id=%s AND legal_entity_id=%s", (count_id, entity_id))
    if not c:
        raise not_found("Stock count", count_id)
    c["lines"] = q(conn, """SELECT l.*, b.batch_number, p.name AS product_name,
                                   (l.counted_qty - l.system_qty) AS variance
                            FROM fin_stock_count_lines l LEFT JOIN fin_batches b ON b.id=l.batch_id
                            LEFT JOIN fin_products p ON p.legal_entity_id=%s AND p.sku=l.sku
                            WHERE l.count_id=%s ORDER BY l.sku, b.batch_number""", (entity_id, count_id))
    return c


def record_count(conn, ctx, count_id: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    ctx.require("inventory.count.create")
    c = get_count(conn, ctx.entity_id, count_id)
    if c["status"] != "DRAFT":
        raise FinError("INVALID_STATE_TRANSITION", "This count is already posted")
    for l in lines:
        ex(conn, "UPDATE fin_stock_count_lines SET counted_qty=%s, reason=%s WHERE id=%s AND count_id=%s",
           (qty(l["counted_qty"]) if l.get("counted_qty") not in (None, "") else None, l.get("reason"), l["id"], count_id))
    return get_count(conn, ctx.entity_id, count_id)


def post_count(conn, ctx, count_id: str) -> Dict[str, Any]:
    ctx.require("inventory.adjustment.approve")
    c = get_count(conn, ctx.entity_id, count_id)
    if c["status"] != "DRAFT":
        raise FinError("INVALID_STATE_TRANSITION", "This count is already posted")
    # The count sheet is the document being approved: whoever raised it cannot post it.
    if c["created_by"] == ctx.actor_id and not _self_ok(conn, ctx):
        raise FinError("PERMISSION_DENIED", "Another person must approve a stock count you raised")
    uncounted = [l for l in c["lines"] if l["counted_qty"] is None]
    if uncounted:
        raise invalid(f"{len(uncounted)} line(s) have no counted quantity yet")
    diffs = [l for l in c["lines"] if Decimal(str(l["counted_qty"])) != Decimal(str(l["system_qty"]))]
    adj = None
    if diffs:
        adj = create_adjustment(conn, ctx, {
            "adjustment_date": c["count_date"], "reason_code": "COUNT_CORRECTION",
            "notes": f"From stock count {c['count_number']}",
            "lines": [{"sku": l["sku"], "batch_id": str(l["batch_id"]) if l["batch_id"] else None,
                       "quantity": Decimal(str(l["counted_qty"])) - Decimal(str(l["system_qty"])),
                       "reason": l["reason"] or "Count variance"} for l in diffs]})
        adj = post_adjustment(conn, ctx, adj["id"], approved_by_count=True)
    ex(conn, "UPDATE fin_stock_counts SET status='POSTED', adjustment_id=%s, posted_by=%s, posted_at=now() WHERE id=%s",
       (adj["id"] if adj else None, ctx.actor_id, count_id))
    audit.record(conn, ctx, "STOCK_COUNT_POSTED", "stock_count", count_id, ref=c["count_number"],
                 metadata={"variances": len(diffs)})
    return get_count(conn, ctx.entity_id, count_id)


# ---------------------------------------------------------------------------
# Stock loans (meeting 2): out on loan is NOT a sale; returns may come back
# in a different batch, which then joins that batch's stock.
# ---------------------------------------------------------------------------

def create_loan(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.loan.create")
    sku = str(data["sku"]).strip()
    qn = qty(data["quantity"])
    customer_id = int(data["customer_id"])
    if not q1(conn, "SELECT 1 FROM customers WHERE id=%s", (customer_id,)):
        raise not_found("Customer", customer_id)
    batch_id = data.get("batch_id") or ensure_batch(conn, ctx.entity_id, sku, data.get("batch_number"))
    number = next_number(conn, ctx.entity_id, "STOCK_LOAN")
    t = issue(conn, ctx, sku=sku, quantity=qn, txn_type="LOAN_OUT", txn_date=data["loan_date"], batch_id=batch_id,
              source_type="STOCK_LOAN", source_id=number, reference=number, customer_id=customer_id,
              reason=data.get("notes"))
    acc = rules.product_accounts(conn, ctx.entity_id, sku)
    loan_acct = rules.account(conn, ctx.entity_id, "STOCK_ON_LOAN")
    unit = t["cost"] / qn
    loan = q1(conn, """INSERT INTO fin_stock_loans (legal_entity_id, loan_number, customer_id, sku, batch_id, quantity,
                       unit_cost, loan_date, expected_return_date, notes, out_txn_id, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
               (ctx.entity_id, number, customer_id, sku, batch_id, qn, unit, data["loan_date"],
                data.get("expected_return_date"), data.get("notes"), t["id"], ctx.actor_id))
    if t["cost"] > 0:
        j = posting.post_system(conn, ctx, event_type="STOCK_LOANED", journal_date=data["loan_date"], lines=[
            {"account_id": loan_acct["id"], "debit": t["cost"], "customer_id": customer_id, "product_sku": sku,
             "description": f"{sku} x{qn:g} on loan"},
            {"account_id": acc["inventory_account_id"], "credit": t["cost"], "product_sku": sku}],
            description=f"Stock loan {number}", source_type="STOCK_LOAN", source_id=loan["id"], source_ref=number)
        link_journal(conn, [str(t["id"])], j["id"])
    audit.record(conn, ctx, "STOCK_LOAN_CREATED", "stock_loan", loan["id"], ref=number,
                 after={"sku": sku, "quantity": qn, "customer_id": customer_id})
    return get_loan(conn, ctx.entity_id, loan["id"])


def get_loan(conn, entity_id: str, loan_id: str) -> Dict[str, Any]:
    l = q1(conn, """SELECT l.*, c.name AS customer_name, b.batch_number, p.name AS product_name,
                           (l.quantity - l.quantity_returned) AS outstanding
                    FROM fin_stock_loans l LEFT JOIN customers c ON c.id=l.customer_id
                    LEFT JOIN fin_batches b ON b.id=l.batch_id
                    LEFT JOIN fin_products p ON p.legal_entity_id=l.legal_entity_id AND p.sku=l.sku
                    WHERE (l.id::text=%s OR l.loan_number=%s) AND l.legal_entity_id=%s""", (loan_id, loan_id, entity_id))
    if not l:
        raise not_found("Stock loan", loan_id)
    l["returns"] = q(conn, """SELECT r.*, b.batch_number FROM fin_stock_loan_returns r
                              LEFT JOIN fin_batches b ON b.id=r.batch_id WHERE r.loan_id=%s ORDER BY r.return_date""",
                     (l["id"],))
    return l


def return_loan(conn, ctx, loan_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.loan.create")
    loan = q1(conn, "SELECT * FROM fin_stock_loans WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (loan_id, ctx.entity_id))
    if not loan:
        raise not_found("Stock loan", loan_id)
    if loan["status"] not in ("OPEN", "PARTIALLY_RETURNED"):
        raise FinError("INVALID_STATE_TRANSITION", f"Loan {loan['loan_number']} is {loan['status'].lower()}")
    qn = qty(data["quantity"])
    outstanding = Decimal(str(loan["quantity"])) - Decimal(str(loan["quantity_returned"]))
    if qn <= 0 or qn > outstanding:
        raise invalid(f"Return quantity must be between 1 and the {outstanding:g} still out")
    # The returned units may be a different batch (meeting 2: "it will join batch M").
    batch_id = data.get("batch_id") or ensure_batch(conn, ctx.entity_id, loan["sku"], data.get("batch_number"),
                                                    expiry_date=data.get("expiry_date"))
    batch_id = batch_id or (str(loan["batch_id"]) if loan["batch_id"] else None)
    unit = Decimal(str(loan["unit_cost"]))
    t = receive(conn, ctx, sku=loan["sku"], quantity=qn, unit_cost=unit, txn_type="LOAN_RETURN",
                txn_date=data["return_date"], batch_id=batch_id, source_type="STOCK_LOAN", source_id=loan["loan_number"],
                reference=loan["loan_number"], customer_id=loan["customer_id"], reason=data.get("notes"))
    value = money(t["total_cost"])
    if value > 0:
        acc = rules.product_accounts(conn, ctx.entity_id, loan["sku"])
        loan_acct = rules.account(conn, ctx.entity_id, "STOCK_ON_LOAN")
        j = posting.post_system(conn, ctx, event_type="STOCK_LOAN_RETURNED", journal_date=data["return_date"], lines=[
            {"account_id": acc["inventory_account_id"], "debit": value, "product_sku": loan["sku"]},
            {"account_id": loan_acct["id"], "credit": value, "customer_id": loan["customer_id"], "product_sku": loan["sku"],
             "description": f"Loan {loan['loan_number']} returned"}],
            description=f"Return on stock loan {loan['loan_number']}", source_type="STOCK_LOAN_RETURN",
            source_id=t["id"], source_ref=loan["loan_number"])
        link_journal(conn, [str(t["id"])], j["id"])
    ex(conn, """INSERT INTO fin_stock_loan_returns (loan_id, return_date, quantity, batch_id, txn_id, notes, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""", (loan_id, data["return_date"], qn, batch_id, t["id"], data.get("notes"), ctx.actor_id))
    returned = Decimal(str(loan["quantity_returned"])) + qn
    status = "RETURNED" if returned >= Decimal(str(loan["quantity"])) else "PARTIALLY_RETURNED"
    ex(conn, "UPDATE fin_stock_loans SET quantity_returned=%s, status=%s WHERE id=%s", (returned, status, loan_id))
    audit.record(conn, ctx, "STOCK_LOAN_RETURNED", "stock_loan", loan_id, ref=loan["loan_number"],
                 metadata={"quantity": str(qn), "batch": _batch_no(conn, batch_id)})
    return get_loan(conn, ctx.entity_id, loan_id)


def write_off_loan(conn, ctx, loan_id: str, reason: str, on: dt.date) -> Dict[str, Any]:
    ctx.require("inventory.adjustment.approve")
    loan = q1(conn, "SELECT * FROM fin_stock_loans WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (loan_id, ctx.entity_id))
    if not loan:
        raise not_found("Stock loan", loan_id)
    if loan["status"] not in ("OPEN", "PARTIALLY_RETURNED"):
        raise FinError("INVALID_STATE_TRANSITION", f"Loan {loan['loan_number']} is {loan['status'].lower()}")
    outstanding = Decimal(str(loan["quantity"])) - Decimal(str(loan["quantity_returned"]))
    value = money(outstanding * Decimal(str(loan["unit_cost"])))
    if value > 0:
        posting.post_system(conn, ctx, event_type="STOCK_LOAN_WRITTEN_OFF", journal_date=on, lines=[
            {"account_id": rules.account(conn, ctx.entity_id, "INVENTORY_ADJUSTMENT")["id"], "debit": value,
             "product_sku": loan["sku"], "description": f"Loan {loan['loan_number']} not returned"},
            {"account_id": rules.account(conn, ctx.entity_id, "STOCK_ON_LOAN")["id"], "credit": value,
             "customer_id": loan["customer_id"], "product_sku": loan["sku"]}],
            description=f"Write-off of stock loan {loan['loan_number']}: {reason}",
            source_type="STOCK_LOAN_WRITEOFF", source_id=loan_id, source_ref=loan["loan_number"])
    ex(conn, "UPDATE fin_stock_loans SET status='WRITTEN_OFF', notes=COALESCE(notes,'') || %s WHERE id=%s",
       (f"\nWritten off: {reason}", loan_id))
    audit.record(conn, ctx, "STOCK_LOAN_WRITTEN_OFF", "stock_loan", loan_id, ref=loan["loan_number"], reason=reason)
    return get_loan(conn, ctx.entity_id, loan_id)


# ---------------------------------------------------------------------------
# Batch traceability & recalls (meeting 2: "who bought this batch, how many")
# ---------------------------------------------------------------------------

def trace_batch(conn, entity_id: str, batch_id: str) -> Dict[str, Any]:
    b = q1(conn, """SELECT b.*, p.name AS product_name FROM fin_batches b
                    LEFT JOIN fin_products p ON p.legal_entity_id=b.legal_entity_id AND p.sku=b.sku
                    WHERE b.id=%s AND b.legal_entity_id=%s""", (batch_id, entity_id))
    if not b:
        raise not_found("Batch", batch_id)
    movements = q(conn, """SELECT t.*, c.name AS customer_name, s.name AS supplier_name
                           FROM fin_inventory_transactions t
                           LEFT JOIN customers c ON c.id=t.customer_id
                           LEFT JOIN suppliers s ON s.id=t.supplier_id
                           WHERE t.batch_id=%s ORDER BY t.txn_date, t.created_at""", (batch_id,))
    # Also catch sales that consumed this batch's layers without naming it.
    customers = q(conn, """
        SELECT t.customer_id, c.name AS customer_name, c.contact_details,
               SUM(CASE WHEN t.txn_type='SALE' THEN lc.quantity ELSE 0 END) AS quantity_sold,
               SUM(CASE WHEN t.txn_type='LOAN_OUT' THEN lc.quantity ELSE 0 END) AS quantity_on_loan,
               array_agg(DISTINCT t.reference) AS documents
        FROM fin_cost_layers l
        JOIN fin_layer_consumptions lc ON lc.layer_id = l.id
        JOIN fin_inventory_transactions t ON t.id = lc.inventory_txn_id
        LEFT JOIN customers c ON c.id = t.customer_id
        WHERE l.batch_id=%s AND t.customer_id IS NOT NULL AND t.txn_type IN ('SALE','LOAN_OUT')
        GROUP BY t.customer_id, c.name, c.contact_details ORDER BY quantity_sold DESC""", (batch_id,))
    bal = on_hand(conn, entity_id, b["sku"], batch_id)
    return {"batch": b, "on_hand": bal, "movements": movements, "customers": customers}


def open_recall(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.recall.create")
    batch = q1(conn, "SELECT * FROM fin_batches WHERE id=%s AND legal_entity_id=%s", (data["batch_id"], ctx.entity_id))
    if not batch:
        raise not_found("Batch", data["batch_id"])
    if not (data.get("reason") or "").strip():
        raise invalid("A recall needs a reason")
    number = next_number(conn, ctx.entity_id, "RECALL")
    r = q1(conn, """INSERT INTO fin_recalls (legal_entity_id, recall_number, sku, batch_id, reason, notes, opened_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
           (ctx.entity_id, number, batch["sku"], batch["id"], data["reason"], data.get("notes"), ctx.actor_id))
    for d in affected_documents(conn, ctx.entity_id, batch):
        _insert_recall_line(conn, ctx, r["id"], batch["sku"], d)
    # Stock still on hand is frozen: it cannot be sold while recalled.
    ex(conn, "UPDATE fin_batches SET status='RECALLED' WHERE id=%s", (batch["id"],))
    audit.record(conn, ctx, "RECALL_OPENED", "recall", r["id"], ref=number, reason=data["reason"],
                 metadata={"sku": batch["sku"], "batch": batch["batch_number"]})
    return get_recall(conn, ctx.entity_id, r["id"])


def affected_documents(conn, entity_id: str, batch: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every document that took the batch out to a customer, one row per invoice or loan, with the
    quantity of this batch on it and the price it was sold at:
      - ACE Books invoices, traced through the FIFO layers the sale consumed (so a sale that did not
        name the batch is still found), priced from the invoice line;
      - loans (stock out with the customer, not sold);
      - Sage invoices: in Sage each lot is its own item, so a sale of the item is a sale of the lot."""
    ace = q(conn, """
        SELECT 'ACE' AS source, i.id AS invoice_id, i.invoice_number, i.invoice_date, i.customer_id,
               SUM(lc.quantity) AS quantity, MAX(il.unit_price) AS unit_price
        FROM fin_cost_layers l
        JOIN fin_layer_consumptions lc ON lc.layer_id = l.id
        JOIN fin_inventory_transactions t ON t.id = lc.inventory_txn_id AND t.txn_type = 'SALE'
        JOIN fin_sales_invoice_lines il ON il.inventory_txn_id = t.id
        JOIN fin_sales_invoices i ON i.id = il.invoice_id AND i.status NOT IN ('VOID', 'DRAFT')
        WHERE l.batch_id = %s
        GROUP BY i.id, i.invoice_number, i.invoice_date, i.customer_id""", (batch["id"],))
    loans = q(conn, """
        SELECT 'LOAN' AS source, NULL::uuid AS invoice_id, t.reference AS invoice_number, MIN(t.txn_date) AS invoice_date,
               t.customer_id, SUM(lc.quantity) AS quantity, NULL::numeric AS unit_price
        FROM fin_cost_layers l
        JOIN fin_layer_consumptions lc ON lc.layer_id = l.id
        JOIN fin_inventory_transactions t ON t.id = lc.inventory_txn_id AND t.txn_type = 'LOAN_OUT'
        WHERE l.batch_id = %s AND t.customer_id IS NOT NULL
        GROUP BY t.reference, t.customer_id""", (batch["id"],))
    sage = q(conn, """
        SELECT 'SAGE' AS source, NULL::uuid AS invoice_id, invoice_number, MIN(invoice_date) AS invoice_date, customer_id,
               SUM(quantity) AS quantity, round(SUM(amount) / NULLIF(SUM(quantity), 0), 2) AS unit_price
        FROM fin_sage_sales_lines
        WHERE legal_entity_id = %s AND sku = %s AND customer_id IS NOT NULL AND quantity > 0
        GROUP BY invoice_number, customer_id""", (entity_id, batch["sku"]))
    seen = {d["invoice_number"] for d in ace}
    rows = ace + loans + [d for d in sage if d["invoice_number"] not in seen]
    return sorted(rows, key=lambda d: (d["invoice_date"] or dt.date.min), reverse=True)


def _insert_recall_line(conn, ctx, recall_id: str, sku: str, d: Dict[str, Any], by_hand: bool = False) -> None:
    ex(conn, """INSERT INTO fin_recall_items (recall_id, customer_id, invoice_id, invoice_number, invoice_date, quantity_sold,
                                              unit_price, source, added_by_hand, updated_by, sku)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
       (recall_id, d["customer_id"], d.get("invoice_id"), d["invoice_number"], d.get("invoice_date"), d["quantity"],
        d.get("unit_price"), d["source"], by_hand, ctx.actor_id, sku))


def add_recall_invoice(conn, ctx, recall_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Add an invoice the trace did not find (e.g. the batch was sold without being named and the
    customer says they have it). The invoice must carry the recalled item; its quantity and price
    of that item become the recall line."""
    ctx.require("inventory.recall.create")
    r = get_recall(conn, ctx.entity_id, recall_id)
    if r["status"] != "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", "This recall is closed")
    number = str(data.get("invoice_number") or "").strip()
    d = None
    if data.get("invoice_id") or (number and not data.get("sage")):
        d = q1(conn, """SELECT 'ACE' AS source, i.id AS invoice_id, i.invoice_number, i.invoice_date, i.customer_id,
                               SUM(l.quantity) AS quantity, MAX(l.unit_price) AS unit_price
                        FROM fin_sales_invoices i JOIN fin_sales_invoice_lines l ON l.invoice_id = i.id AND l.sku = %s
                        WHERE i.legal_entity_id = %s AND i.status NOT IN ('VOID', 'DRAFT')
                          AND (i.id::text = %s OR i.invoice_number = %s)
                        GROUP BY i.id, i.invoice_number, i.invoice_date, i.customer_id""",
               (r["sku"], ctx.entity_id, str(data.get("invoice_id") or ""), number))
    if not d and number:
        d = q1(conn, """SELECT 'SAGE' AS source, NULL::uuid AS invoice_id, invoice_number, MIN(invoice_date) AS invoice_date,
                               MAX(customer_id) AS customer_id, SUM(quantity) AS quantity,
                               round(SUM(amount) / NULLIF(SUM(quantity), 0), 2) AS unit_price
                        FROM fin_sage_sales_lines WHERE legal_entity_id = %s AND sku = %s AND invoice_number = %s
                        GROUP BY invoice_number""", (ctx.entity_id, r["sku"], number))
    if not d:
        raise invalid(f"Invoice {number or data.get('invoice_id')} has no {r.get('product_name') or r['sku']} on it")
    if any((i["invoice_id"] and d["invoice_id"] and str(i["invoice_id"]) == str(d["invoice_id"])) or i["invoice_number"] == d["invoice_number"]
           for i in r["items"]):
        raise invalid(f"Invoice {d['invoice_number']} is already on this recall")
    if data.get("quantity"):
        d["quantity"] = qty(data["quantity"])
    _insert_recall_line(conn, ctx, recall_id, r["sku"], d, by_hand=True)
    audit.record(conn, ctx, "RECALL_INVOICE_ADDED", "recall", recall_id, ref=r["recall_number"],
                 metadata={"invoice": d["invoice_number"], "source": d["source"], "quantity": str(d["quantity"])})
    return get_recall(conn, ctx.entity_id, recall_id)


def recall_supply(conn, entity_id: str, recall: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Where the recalled batch came from: the supplier bill(s) in ACE Books that received it, else
    the Sage purchase invoices of the item (each Sage lot is its own item)."""
    rows = q(conn, """SELECT 'ACE' AS source, b.id AS bill_id, b.bill_number, b.supplier_invoice_number, b.bill_date,
                             b.supplier_id, s.name AS supplier_name, SUM(l.quantity) AS quantity,
                             round(SUM(l.line_total) / NULLIF(SUM(l.quantity), 0), 2) AS unit_cost
                      FROM fin_supplier_bill_lines l JOIN fin_supplier_bills b ON b.id = l.bill_id AND b.status <> 'VOID'
                      LEFT JOIN suppliers s ON s.id = b.supplier_id
                      WHERE l.batch_id = %s
                      GROUP BY b.id, b.bill_number, b.supplier_invoice_number, b.bill_date, b.supplier_id, s.name""",
             (recall["batch_id"],))
    if rows:
        return rows
    return q(conn, """SELECT 'SAGE' AS source, NULL::uuid AS bill_id, bill_number, bill_number AS supplier_invoice_number,
                             MIN(bill_date) AS bill_date, supplier_id, MAX(supplier_name) AS supplier_name, SUM(quantity) AS quantity,
                             round(SUM(amount) / NULLIF(SUM(quantity), 0), 2) AS unit_cost
                      FROM fin_sage_purchase_lines WHERE legal_entity_id = %s AND sku = %s AND quantity > 0
                      GROUP BY bill_number, supplier_id ORDER BY MIN(bill_date) DESC""", (entity_id, recall["sku"]))


def return_recall_to_supplier(conn, ctx, recall_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Send recalled stock back to the supplier: a debit note against the bill the batch came in on
    reduces what we owe them, and the units leave the (frozen) batch at book cost."""
    from src.fin import purchases
    ctx.require("inventory.recall.create")
    r = get_recall(conn, ctx.entity_id, recall_id)
    quantity = qty(data.get("quantity") or 0)
    if quantity <= 0:
        raise invalid("How many units go back to the supplier?")
    src = None
    if data.get("bill_id"):
        src = next((x for x in r["supply"] if x["bill_id"] and str(x["bill_id"]) == str(data["bill_id"])), None)
    elif data.get("bill_number"):
        src = next((x for x in r["supply"] if x["bill_number"] == data["bill_number"]), None)
    elif len(r["supply"]) == 1:
        src = r["supply"][0]
    supplier_id = data.get("supplier_id") or (src or {}).get("supplier_id")
    if not supplier_id:
        raise invalid("Choose the supplier (no bill in ACE Books or Sage shows who supplied this batch)")
    unit_cost = money(data.get("unit_cost") or (src or {}).get("unit_cost") or 0)
    on = data.get("note_date") or dt.date.today()
    dn = purchases.create_debit_note(conn, ctx, {
        "supplier_id": supplier_id, "note_date": on,
        "bill_id": str(src["bill_id"]) if src and src.get("bill_id") else None,
        "sage_bill_number": src["bill_number"] if src and src["source"] == "SAGE" else None,
        "reason": f"Recall {r['recall_number']}: {r['reason']}",
        "lines": [{"line_type": "ITEM", "sku": r["sku"], "quantity": quantity, "batch_id": str(r["batch_id"]),
                   "line_total": money(quantity * unit_cost) if unit_cost > 0 else None,
                   "description": f"{r.get('product_name') or r['sku']} batch {r['batch_number']} (recalled) returned"}]})
    ex(conn, """INSERT INTO fin_recall_supplier_returns (recall_id, supplier_id, bill_id, sage_bill_number, debit_note_id, quantity,
                                                         unit_cost, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
       (recall_id, supplier_id, src["bill_id"] if src else None, src["bill_number"] if src and src["source"] == "SAGE" else None,
        dn["id"], quantity, unit_cost or None, ctx.actor_id))
    audit.record(conn, ctx, "RECALL_RETURNED_TO_SUPPLIER", "recall", recall_id, ref=r["recall_number"],
                 metadata={"debit_note": dn.get("debit_note_number"), "quantity": str(quantity)})
    return {**get_recall(conn, ctx.entity_id, recall_id), "debit_note": dn}


def recalls_for_invoice(conn, entity_id: str, invoice_id: Optional[str] = None,
                        invoice_number: Optional[str] = None) -> List[Dict[str, Any]]:
    """The recalls an invoice is part of (shown on the invoice, ACE Books or Sage)."""
    return q(conn, """SELECT r.id AS recall_id, r.recall_number, r.status, r.reason, r.sku, b.batch_number,
                             i.quantity_sold, i.quantity_returned, i.contact_status, i.credit_note_id, n.credit_note_number,
                             n.total AS credit_total, rc.id AS qc_case_id, rc.recall_id AS qc_recall
                      FROM fin_recall_items i JOIN fin_recalls r ON r.id = i.recall_id
                      JOIN fin_batches b ON b.id = r.batch_id
                      LEFT JOIN fin_credit_notes n ON n.id = i.credit_note_id
                      LEFT JOIN recall_cases rc ON rc.fin_recall_id = r.id
                      WHERE r.legal_entity_id = %s AND ((%s::text IS NOT NULL AND i.invoice_id::text = %s)
                                                        OR (%s::text IS NOT NULL AND i.invoice_number = %s))
                      ORDER BY r.opened_at DESC""",
             (entity_id, invoice_id, invoice_id, invoice_number, invoice_number))


def get_recall(conn, entity_id: str, recall_id: str) -> Dict[str, Any]:
    r = q1(conn, """SELECT r.*, b.batch_number, b.expiry_date, p.name AS product_name FROM fin_recalls r
                    JOIN fin_batches b ON b.id=r.batch_id
                    LEFT JOIN fin_products p ON p.legal_entity_id=r.legal_entity_id AND p.sku=r.sku
                    WHERE r.id=%s AND r.legal_entity_id=%s""", (recall_id, entity_id))
    if not r:
        raise not_found("Recall", recall_id)
    r["items"] = q(conn, """SELECT i.*, c.name AS customer_name, c.contact_details, n.credit_note_number, n.total AS credit_total
                            FROM fin_recall_items i LEFT JOIN customers c ON c.id=i.customer_id
                            LEFT JOIN fin_credit_notes n ON n.id=i.credit_note_id WHERE i.recall_id=%s
                            ORDER BY i.invoice_date DESC NULLS LAST, i.quantity_sold DESC""", (recall_id,))
    r["on_hand"] = on_hand(conn, entity_id, r["sku"], str(r["batch_id"]))
    r["supply"] = recall_supply(conn, entity_id, r)
    r["supplier_returns"] = q(conn, """SELECT x.*, s.name AS supplier_name, d.debit_note_number, d.total AS debit_total,
                                              b.bill_number
                                       FROM fin_recall_supplier_returns x LEFT JOIN suppliers s ON s.id = x.supplier_id
                                       LEFT JOIN fin_debit_notes d ON d.id = x.debit_note_id
                                       LEFT JOIN fin_supplier_bills b ON b.id = x.bill_id
                                       WHERE x.recall_id = %s ORDER BY x.created_at""", (recall_id,))
    case = q1(conn, "SELECT id::text AS id, recall_id, status, severity FROM recall_cases WHERE fin_recall_id=%s", (recall_id,))
    r["qc_case"] = case
    r["totals"] = {"invoices": len([i for i in r["items"] if i["source"] != "LOAN"]),
                   "units_out": sum((Decimal(str(i["quantity_sold"] or 0)) for i in r["items"]), Decimal("0")),
                   "units_returned": sum((Decimal(str(i["quantity_returned"] or 0)) for i in r["items"]), Decimal("0")),
                   "credited": sum((Decimal(str(i["credit_total"] or 0)) for i in r["items"]), Decimal("0")),
                   "to_supplier": sum((Decimal(str(x["quantity"] or 0)) for x in r["supplier_returns"]), Decimal("0"))}
    return r


def update_recall_item(conn, ctx, recall_id: str, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.recall.create")
    r = get_recall(conn, ctx.entity_id, recall_id)
    if r["status"] != "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", "This recall is closed")
    fields = {k: data[k] for k in ("contact_status", "quantity_returned", "notes") if k in data}
    if not fields:
        return r
    sets = ", ".join(f"{k}=%s" for k in fields)
    ex(conn, f"UPDATE fin_recall_items SET {sets}, updated_by=%s, updated_at=now() WHERE id=%s AND recall_id=%s",
       list(fields.values()) + [ctx.actor_id, item_id, recall_id])
    audit.record(conn, ctx, "RECALL_ITEM_UPDATED", "recall", recall_id, ref=r["recall_number"], after=fields)
    return get_recall(conn, ctx.entity_id, recall_id)


def record_recall_return(conn, ctx, recall_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """A customer brings recalled stock back: a credit note against the invoice they bought it
    on (ACE Books or Sage) reduces what they owe, and the stock comes back into the recalled
    batch (still frozen - it cannot be sold). The recall line records who returned what."""
    from src.fin import sales
    ctx.require("inventory.recall.create")
    r = get_recall(conn, ctx.entity_id, recall_id)
    if r["status"] != "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", "This recall is closed")
    customer_id = data.get("customer_id")
    item = None
    if data.get("item_id"):
        item = next((i for i in r["items"] if str(i["id"]) == str(data["item_id"])), None)
        if not item:
            raise not_found("Recall line", data["item_id"])
        customer_id = customer_id or item["customer_id"]
        # the line already names the invoice and the price it was sold at
        if not data.get("invoice_id") and not data.get("sage_invoice_number"):
            if item.get("invoice_id"):
                data = {**data, "invoice_id": str(item["invoice_id"])}
            elif item.get("source") == "SAGE" and item.get("invoice_number"):
                data = {**data, "sage_invoice_number": item["invoice_number"]}
        if not data.get("unit_price") and item.get("unit_price") and data.get("credit", True):
            data = {**data, "unit_price": item["unit_price"]}
    if not customer_id:
        raise invalid("Choose the customer returning the stock")
    quantity = qty(data.get("quantity") or 0)
    if quantity <= 0:
        raise invalid("How many units came back?")
    price = money(data.get("unit_price") or 0)
    on = data.get("note_date") or dt.date.today()
    cn = None
    if data.get("credit", True) and price > 0:
        cn = sales.create_credit_note(conn, ctx, {
            "customer_id": customer_id, "note_date": on, "invoice_id": data.get("invoice_id"),
            "sage_invoice_number": data.get("sage_invoice_number"), "return_to_stock": True, "recall_id": recall_id,
            "reason": f"Recall {r['recall_number']}: {r['reason']}",
            "lines": [{"line_type": "ITEM", "sku": r["sku"], "quantity": quantity, "unit_price": price,
                       "batch_id": str(r["batch_id"]), "unit_cost": data.get("unit_cost"),
                       "description": f"{r.get('product_name') or r['sku']} batch {r['batch_number']} (recalled)"}]})
    else:
        receive(conn, ctx, sku=r["sku"], quantity=quantity, unit_cost=data.get("unit_cost") or last_unit_cost(conn, ctx.entity_id, r["sku"]),
                txn_type="RETURN_IN", txn_date=on, batch_id=str(r["batch_id"]), source_type="RECALL", source_id=recall_id,
                reference=r["recall_number"], customer_id=customer_id, reason="Recalled stock returned (no credit)")
    if item:
        ex(conn, """UPDATE fin_recall_items SET quantity_returned = quantity_returned + %s, contact_status='RETURNED',
                    credit_note_id=COALESCE(%s, credit_note_id), updated_by=%s, updated_at=now() WHERE id=%s""",
           (quantity, cn["id"] if cn else None, ctx.actor_id, item["id"]))
    else:
        ex(conn, """INSERT INTO fin_recall_items (recall_id, customer_id, invoice_number, quantity_sold, quantity_returned,
                    contact_status, credit_note_id, updated_by, sku) VALUES (%s,%s,%s,%s,%s,'RETURNED',%s,%s,%s)""",
           (recall_id, customer_id, data.get("sage_invoice_number") or data.get("invoice_number"), quantity, quantity,
            cn["id"] if cn else None, ctx.actor_id, r["sku"]))
    audit.record(conn, ctx, "RECALL_RETURN_RECORDED", "recall", recall_id, ref=r["recall_number"],
                 metadata={"customer_id": customer_id, "quantity": str(quantity), "credit_note": cn["credit_note_number"] if cn else None})
    return {**get_recall(conn, ctx.entity_id, recall_id), "credit_note": cn}


def void_recall(conn, ctx, recall_id: str, reason: str) -> Dict[str, Any]:
    """A recall opened by mistake: the batch is released (sellable again) and the recall and its
    Quality Control case are marked void (kept for the audit trail). Not possible once a return has
    been posted - void those credit / debit notes first, so no figure is left without its reason."""
    ctx.require("inventory.recall.create")
    if not (reason or "").strip():
        raise invalid("Give the reason for voiding the recall")
    r = get_recall(conn, ctx.entity_id, recall_id)
    if r["status"] == "VOID":
        raise FinError("INVALID_STATE_TRANSITION", "This recall is already void")
    notes = [i["credit_note_number"] for i in r["items"] if i.get("credit_note_id")
             and q1(conn, "SELECT 1 FROM fin_credit_notes WHERE id=%s AND status <> 'VOID'", (i["credit_note_id"],))]
    notes += [x["debit_note_number"] for x in r["supplier_returns"] if x.get("debit_note_id")
              and q1(conn, "SELECT 1 FROM fin_debit_notes WHERE id=%s AND status <> 'VOID'", (x["debit_note_id"],))]
    if notes:
        raise FinError("INVALID_STATE_TRANSITION",
                       f"Returns were posted on this recall ({', '.join(n for n in notes if n)}). Void those notes first, then the recall.")
    ex(conn, """UPDATE fin_recalls SET status='VOID', void_reason=%s, voided_by=%s, voided_at=now() WHERE id=%s""",
       (reason.strip(), ctx.actor_id, recall_id))
    if not q1(conn, "SELECT 1 FROM fin_recalls WHERE batch_id=%s AND status='OPEN' AND id<>%s", (r["batch_id"], recall_id)):
        ex(conn, "UPDATE fin_batches SET status='AVAILABLE' WHERE id=%s AND status='RECALLED'", (r["batch_id"],))
    ex(conn, "UPDATE recall_cases SET status='voided', resolved_at=now(), updated_at=now() WHERE fin_recall_id=%s", (recall_id,))
    from src.services.quality_hub import notify_recall
    notify_recall(conn, f"Recall {r['recall_number']} voided", f"{r.get('product_name') or r['sku']} batch {r['batch_number']} "
                  f"is sellable again. Reason: {reason}", ctx.actor_id)
    audit.record(conn, ctx, "RECALL_VOIDED", "recall", recall_id, ref=r["recall_number"], reason=reason,
                 metadata={"batch": r["batch_number"], "batch_released": True})
    return get_recall(conn, ctx.entity_id, recall_id)


def close_recall(conn, ctx, recall_id: str, notes: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("inventory.recall.create")
    r = get_recall(conn, ctx.entity_id, recall_id)
    if r["status"] != "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", "This recall is already closed")
    ex(conn, "UPDATE fin_recalls SET status='CLOSED', closed_by=%s, closed_at=now(), notes=COALESCE(%s, notes) WHERE id=%s",
       (ctx.actor_id, notes, recall_id))
    audit.record(conn, ctx, "RECALL_CLOSED", "recall", recall_id, ref=r["recall_number"], reason=notes)
    return get_recall(conn, ctx.entity_id, recall_id)


def set_batch_status(conn, ctx, batch_id: str, status: str, reason: str) -> Dict[str, Any]:
    ctx.require("inventory.batch.edit")
    status = status.upper()
    if status not in ("AVAILABLE", "QUARANTINED", "RECALLED", "EXPIRED", "DAMAGED", "CLOSED"):
        raise invalid("Unknown batch status")
    b = q1(conn, "SELECT * FROM fin_batches WHERE id=%s AND legal_entity_id=%s", (batch_id, ctx.entity_id))
    if not b:
        raise not_found("Batch", batch_id)
    ex(conn, "UPDATE fin_batches SET status=%s WHERE id=%s", (status, batch_id))
    audit.record(conn, ctx, "BATCH_STATUS_CHANGED", "batch", batch_id, ref=f"{b['sku']} {b['batch_number']}",
                 before={"status": b["status"]}, after={"status": status}, reason=reason)
    return {**b, "status": status}


def update_batch(conn, ctx, batch_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.batch.edit")
    b = q1(conn, "SELECT * FROM fin_batches WHERE id=%s AND legal_entity_id=%s", (batch_id, ctx.entity_id))
    if not b:
        raise not_found("Batch", batch_id)
    fields: Dict[str, Any] = {}
    if data.get("batch_number") is not None:
        num = str(data["batch_number"]).strip()
        if not num:
            raise invalid("A batch needs a number")
        if num != b["batch_number"] and q1(conn, "SELECT 1 FROM fin_batches WHERE legal_entity_id=%s AND sku=%s AND batch_number=%s",
                                           (ctx.entity_id, b["sku"], num)):
            raise FinError("DUPLICATE_RESOURCE", f"{b['sku']} already has a batch {num}")
        fields["batch_number"] = num
    for k in ("manufacture_date", "expiry_date"):
        if k in data:
            fields[k] = data[k] or None
    if "pack_batch_number" in data:
        fields["pack_batch_number"] = (str(data["pack_batch_number"] or "").strip() or None)
    if "notes" in data:
        fields["notes"] = data["notes"]
    if not fields:
        return b
    ex(conn, f"UPDATE fin_batches SET {', '.join(f'{k}=%s' for k in fields)} WHERE id=%s", list(fields.values()) + [batch_id])
    audit.record(conn, ctx, "BATCH_UPDATED", "batch", batch_id, ref=f"{b['sku']} {b['batch_number']}",
                 before={k: b.get(k) for k in fields}, after=fields)
    return q1(conn, "SELECT * FROM fin_batches WHERE id=%s", (batch_id,))


def require_sellable(conn, entity_id: str, batch_id: Optional[str]) -> None:
    if not batch_id:
        return
    b = q1(conn, "SELECT batch_number, status, expiry_date FROM fin_batches WHERE id=%s AND legal_entity_id=%s", (batch_id, entity_id))
    if not b:
        raise FinError("INVALID_BATCH", "Batch not found")
    if b["status"] != "AVAILABLE":
        raise FinError("INVALID_BATCH", f"Batch {b['batch_number']} is {b['status'].lower()} and cannot be sold",
                       {"batch": b["batch_number"], "status": b["status"]})
    if b["expiry_date"] and b["expiry_date"] < dt.date.today():
        raise FinError("INVALID_BATCH", f"Batch {b['batch_number']} expired on {b['expiry_date']:%d %b %Y} and cannot be sold",
                       {"batch": b["batch_number"], "expiry_date": str(b["expiry_date"])})
