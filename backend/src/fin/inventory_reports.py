"""Inventory engine for the stock reports the client ran in Sage (finance meeting 4, 19 Oct 2026).

One movement ledger per item across both systems, the same rule as the books: Sage is the record up
to and including the hand-over date (``fin_settings.history_until``, H) and ACE Books from the day
after. Sage's history comes from its own Item Costing export (``fin_sage_item_costing``: received,
adjusted, sold and remaining per item and date); ACE's from ``fin_inventory_transactions``.

Every movement carries the document behind it so a row opens it (the accountant's "who did we sell
these ten to?"): a Sage sale is matched to its Sage invoice line (same item, date and quantity, in
order), a Sage receipt to its purchase line, a Sage adjustment to its INAJ journal entry; an ACE
movement points at its own invoice, bill, credit note, adjustment or loan.

Reports built on it:
  * unit_activity  - Sage "Inventory Unit Activity": beginning qty, units sold, units purchased,
                     adjust qty and qty on hand per item for a period.
  * item_costing   - Sage "Item Costing": each item's movements in date order with qty received,
                     item cost, adjust qty, qty sold, remaining qty and value, and the customer /
                     supplier and document for each.
Item IDs carry the Sage lot (e.g. "CERVARIX 0.5ml(H)"), which is how the client reads a batch.
"""
import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from src.fin.books_ledger import history_until
from src.fin.db import ZERO, q

ONE_DAY = dt.timedelta(days=1)

RECEIVED_TYPES = ("PURCHASE", "RETURN_OUT")          # a return to the supplier is a negative receipt (as Sage)
SOLD_TYPES = ("SALE", "RETURN_IN")                    # a customer return is a negative sale (as Sage)
LOAN_TYPES = ("LOAN_OUT", "LOAN_RETURN")
TYPE_LABEL = {
    "PURCHASE": "Received", "RETURN_OUT": "Returned to supplier", "SALE": "Sold", "RETURN_IN": "Customer return",
    "LOAN_OUT": "Lent", "LOAN_RETURN": "Loan returned", "ADJUSTMENT": "Adjustment", "DAMAGE": "Damage",
    "EXPIRY": "Expiry write-off", "STOCK_COUNT": "Stock count", "RECALL": "Recall", "BATCH_REPLACEMENT": "Batch replacement",
    "TRANSFER_IN": "Transfer in", "TRANSFER_OUT": "Transfer out", "OPENING_BALANCE": "Opening balance",
}
SOURCE_DRILL = {
    "SALES_INVOICE": "invoice", "FRONTDESK": "invoice", "SALES_INVOICE_VOID": "invoice", "SALES_INVOICE_AMENDED": "invoice",
    "CREDIT_NOTE": "creditnote", "SUPPLIER_BILL": "bill", "DEBIT_NOTE": "debitnote", "STOCK_ADJUSTMENT": "adjustment",
    "STOCK_LOAN": "loan", "RECALL": "recall", "DATA_CORRECTION": "dataissue",
}


def _d(v: Any) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else ZERO


def _bounds(conn, e: str, date_from: dt.date, date_to: dt.date) -> Dict[str, Any]:
    """Which part of the period each system covers."""
    h = history_until(conn, e)
    return {
        "h": h,
        # Sage rows: date_from .. min(date_to, H); opening = Sage's remaining before min(date_from, H+1)
        "sage_to": min(date_to, h) if h else None,
        "sage_open_before": min(date_from, h + ONE_DAY) if h else None,
        # ACE rows: max(date_from, H+1) .. date_to; opening adds ACE movements after H and before date_from
        "ace_from": max(date_from, h + ONE_DAY) if h else date_from,
        "ace_after": h,
    }


def _item_filter(search: Optional[str], sku: Optional[str], sku_from: Optional[str], sku_to: Optional[str],
                 alias: str = "x") -> Tuple[str, List[Any]]:
    w, p = [], []
    if sku:
        w.append(f"{alias}.sku = %s"); p.append(sku)
    if search:
        w.append(f"({alias}.sku ILIKE %s OR {alias}.name ILIKE %s)"); p += [f"%{search}%", f"%{search}%"]
    if sku_from:
        w.append(f"lower({alias}.sku) >= lower(%s)"); p.append(sku_from)
    if sku_to:
        w.append(f"lower({alias}.sku) <= lower(%s)"); p.append(sku_to)
    return (" AND " + " AND ".join(w)) if w else "", p


def _lot_code(v: Optional[str]) -> Optional[tuple]:
    """A short lot code typed in the range ("A", "g", "Z ii", "(H)") -> its order key; None for a full item ID."""
    import re
    m = re.match(r"^\(?\s*([A-Za-z])\s*\)?\s*([ivxlcIVXLC]*)\s*$", (v or "").strip())
    if not m:
        return None
    from src.fin.maintain import _roman
    return (ord(m.group(1).upper()) - 64, _roman(m.group(2)))


def _items(conn, e: str, search=None, sku=None, sku_from=None, sku_to=None) -> List[Dict[str, Any]]:
    """Every item ID known to either system (ACE products and Sage's item costing), A-Z. The range may be
    full item IDs, or - with a product name - lot codes: "CERVARIX", A to G."""
    lo, hi = _lot_code(sku_from), _lot_code(sku_to)
    if lo or hi:
        rows = _items(conn, e, search, sku, None if lo else sku_from, None if hi else sku_to)
        from src.fin.maintain import lot_key
        out = []
        for r in rows:
            k = lot_key(r["sku"])
            if k[0] == 0:
                continue
            if (lo and (k[0], k[1]) < lo) or (hi and (k[0], k[1]) > hi):
                continue
            out.append(r)
        return out
    f, p = _item_filter(search, sku, sku_from, sku_to)
    return q(conn, f"""
        SELECT x.sku, MAX(x.name) AS name, BOOL_OR(x.ace) AS in_ace FROM (
            SELECT sku, name, TRUE AS ace FROM fin_products WHERE legal_entity_id=%s AND product_type='INVENTORY'
            UNION ALL
            SELECT sku, MAX(description), FALSE FROM fin_sage_item_costing WHERE legal_entity_id=%s GROUP BY sku
        ) x WHERE TRUE {f}
        GROUP BY x.sku ORDER BY lower(x.sku)""", [e, e] + p)


def _openings(conn, e: str, b: Dict[str, Any], skus: List[str]) -> Dict[str, Dict[str, Decimal]]:
    """Quantity and value on hand at the start of the period, per item."""
    out: Dict[str, Dict[str, Decimal]] = {s: {"qty": ZERO, "value": ZERO} for s in skus}
    if not skus:
        return out
    if b["h"]:
        for r in q(conn, """SELECT DISTINCT ON (sku) sku, remaining_qty, remaining_value FROM fin_sage_item_costing
                            WHERE legal_entity_id=%s AND sku = ANY(%s) AND txn_date < %s
                            ORDER BY sku, txn_date DESC, id DESC""", (e, skus, b["sage_open_before"])):
            out[r["sku"]] = {"qty": _d(r["remaining_qty"]), "value": _d(r["remaining_value"])}
    after = b["ace_after"]
    rows = q(conn, f"""SELECT sku, SUM(quantity) AS qty, SUM(total_cost) AS value FROM fin_inventory_transactions
                       WHERE legal_entity_id=%s AND sku = ANY(%s) AND txn_date < %s {"AND txn_date > %s" if after else ""}
                       GROUP BY sku""", [e, skus, b["ace_from"]] + ([after] if after else []))
    for r in rows:
        o = out.setdefault(r["sku"], {"qty": ZERO, "value": ZERO})
        o["qty"] += _d(r["qty"]); o["value"] += _d(r["value"])
    return out


# ---------------------------------------------------------------------------
# Inventory Unit Activity
# ---------------------------------------------------------------------------

def unit_activity(conn, e: str, date_from: dt.date, date_to: dt.date, *, search: Optional[str] = None,
                  sku: Optional[str] = None, sku_from: Optional[str] = None, sku_to: Optional[str] = None,
                  include_inactive: bool = False) -> Dict[str, Any]:
    b = _bounds(conn, e, date_from, date_to)
    items = _items(conn, e, search, sku, sku_from, sku_to)
    skus = [i["sku"] for i in items]
    opening = _openings(conn, e, b, skus)
    acc: Dict[str, Dict[str, Decimal]] = {s: {k: ZERO for k in ("sold", "purchased", "adjusted", "loans", "cost_of_sales", "purchase_cost")}
                                          for s in skus}
    if skus and b["h"] and b["sage_to"] and date_from <= b["sage_to"]:
        for r in q(conn, """SELECT sku, SUM(qty_sold) AS sold, SUM(qty_received) AS purchased, SUM(qty_adjusted) AS adjusted,
                                   SUM(cost_of_sales) AS cos, SUM(received_cost) AS pc
                            FROM fin_sage_item_costing WHERE legal_entity_id=%s AND sku = ANY(%s) AND txn_date BETWEEN %s AND %s
                            GROUP BY sku""", (e, skus, date_from, b["sage_to"])):
            a = acc[r["sku"]]
            a["sold"] += _d(r["sold"]); a["purchased"] += _d(r["purchased"]); a["adjusted"] += _d(r["adjusted"])
            a["cost_of_sales"] += _d(r["cos"]); a["purchase_cost"] += _d(r["pc"])
    if skus and b["ace_from"] <= date_to:
        for r in q(conn, """SELECT sku, txn_type, SUM(quantity) AS qty, SUM(total_cost) AS cost FROM fin_inventory_transactions
                            WHERE legal_entity_id=%s AND sku = ANY(%s) AND txn_date BETWEEN %s AND %s GROUP BY sku, txn_type""",
                       (e, skus, b["ace_from"], date_to)):
            a = acc[r["sku"]]
            qn, cost = _d(r["qty"]), _d(r["cost"])
            if r["txn_type"] in SOLD_TYPES:
                a["sold"] -= qn; a["cost_of_sales"] -= cost
            elif r["txn_type"] in RECEIVED_TYPES:
                a["purchased"] += qn; a["purchase_cost"] += cost
            elif r["txn_type"] in LOAN_TYPES:
                a["loans"] += qn
            else:
                a["adjusted"] += qn
    rows = []
    for i in items:
        s = i["sku"]; a = acc[s]; o = opening[s]
        on_hand = o["qty"] + a["purchased"] - a["sold"] + a["adjusted"] + a["loans"]
        r = {"sku": s, "name": i["name"], "beg_qty": o["qty"], "sold": a["sold"], "purchased": a["purchased"],
             "adjusted": a["adjusted"], "loans": a["loans"], "on_hand": on_hand, "cost_of_sales": a["cost_of_sales"],
             "purchase_cost": a["purchase_cost"]}
        if include_inactive or any(r[k] != 0 for k in ("beg_qty", "sold", "purchased", "adjusted", "loans", "on_hand")):
            rows.append(r)
    tot = {k: sum((r[k] for r in rows), ZERO) for k in ("beg_qty", "sold", "purchased", "adjusted", "loans", "on_hand",
                                                         "cost_of_sales", "purchase_cost")}
    return {"date_from": date_from, "date_to": date_to, "history_until": b["h"], "rows": rows, "totals": tot,
            "items_considered": len(items)}


# ---------------------------------------------------------------------------
# Item Costing
# ---------------------------------------------------------------------------

def _sage_rows(conn, e: str, skus: List[str], date_from: dt.date, date_to: dt.date) -> List[Dict[str, Any]]:
    """Sage's item costing lines with the document behind each (matched on item, date and quantity, in order)."""
    rows = q(conn, """
        WITH ic AS (
            SELECT id, sku, description, txn_date, qty_received, received_cost, qty_adjusted, adjusted_cost, qty_sold,
                   cost_of_sales, remaining_qty, remaining_value,
                   row_number() OVER (PARTITION BY sku, txn_date, qty_sold ORDER BY id) AS rn_s,
                   row_number() OVER (PARTITION BY sku, txn_date, qty_received ORDER BY id) AS rn_r
            FROM fin_sage_item_costing WHERE legal_entity_id=%(e)s AND sku = ANY(%(skus)s) AND txn_date BETWEEN %(f)s AND %(t)s),
        sl AS (
            SELECT sku, invoice_date, quantity, invoice_number, customer_id, customer_name, amount,
                   row_number() OVER (PARTITION BY sku, invoice_date, quantity ORDER BY invoice_number, line_no, id) AS rn
            FROM fin_sage_sales_lines WHERE legal_entity_id=%(e)s AND sku = ANY(%(skus)s) AND invoice_date BETWEEN %(f)s AND %(t)s),
        pl AS (
            SELECT sku, bill_date, quantity, bill_number, supplier_id, supplier_name, amount,
                   row_number() OVER (PARTITION BY sku, bill_date, quantity ORDER BY bill_number, line_no, id) AS rn
            FROM fin_sage_purchase_lines WHERE legal_entity_id=%(e)s AND sku = ANY(%(skus)s) AND bill_date BETWEEN %(f)s AND %(t)s)
        SELECT ic.*, sl.invoice_number, sl.customer_id, sl.customer_name, sl.amount AS sale_amount,
               pl.bill_number, pl.supplier_id::text AS supplier_id, pl.supplier_name,
               CASE WHEN ic.qty_adjusted IS NOT NULL THEN
                 (SELECT g.reference FROM fin_sage_gl_lines g WHERE g.legal_entity_id=%(e)s AND g.jrnl='INAJ' AND g.txn_date=ic.txn_date
                    AND lower(trim(g.description))=lower(trim(ic.description)) ORDER BY g.seq LIMIT 1) END AS adj_ref
        FROM ic
        LEFT JOIN sl ON ic.qty_sold IS NOT NULL AND sl.sku=ic.sku AND sl.invoice_date=ic.txn_date AND sl.quantity=ic.qty_sold AND sl.rn=ic.rn_s
        LEFT JOIN pl ON ic.qty_received IS NOT NULL AND pl.sku=ic.sku AND pl.bill_date=ic.txn_date AND pl.quantity=ic.qty_received AND pl.rn=ic.rn_r
        ORDER BY ic.sku, ic.txn_date, ic.id""", {"e": e, "skus": skus, "f": date_from, "t": date_to})
    # A sale Sage costed differently from its invoice line (e.g. the item twice on one invoice): offer that
    # day's invoices for the item instead of nothing.
    # Matched on the item ID, or - for Sage lines saved without one - on the item's description.
    loose = {(r["sku"], r["txn_date"]): (r["description"] or "").strip().lower()
             for r in rows if r["qty_sold"] is not None and not r["invoice_number"]}
    cands: Dict[Tuple[str, dt.date], List[Dict[str, Any]]] = {}
    if loose:
        found = q(conn, """SELECT sku, lower(trim(description)) AS d, invoice_date, invoice_number, customer_id, customer_name,
                                  SUM(quantity) AS quantity
                           FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND invoice_date = ANY(%s)
                             AND (sku = ANY(%s) OR (sku IS NULL AND lower(trim(description)) = ANY(%s)))
                           GROUP BY sku, lower(trim(description)), invoice_date, invoice_number, customer_id, customer_name
                           ORDER BY invoice_number""",
                  (e, list({k[1] for k in loose}), list({k[0] for k in loose}), [v for v in set(loose.values()) if v]))
        for (sk, day), desc in loose.items():
            cands[(sk, day)] = [c for c in found if c["invoice_date"] == day and (c["sku"] == sk or (c["sku"] is None and desc and c["d"] == desc))]
    out = []
    for r in rows:
        if r["qty_received"] is not None:
            kind = "Received"
            doc = {"type": "sagebill", "id": f"{r['bill_number']}|{r['supplier_id'] or ''}", "label": r["bill_number"]} if r["bill_number"] else None
            party = r["supplier_name"]
        elif r["qty_adjusted"] is not None:
            kind = "Adjustment"
            doc = {"type": "sagetxn", "id": f"{r['txn_date']}|INAJ|{r['adj_ref'] or ''}", "label": r["adj_ref"] or "INAJ"}
            party = None
        else:
            kind = "Customer return" if _d(r["qty_sold"]) < 0 else "Sold"
            doc = {"type": "sageinvoice", "id": r["invoice_number"], "label": r["invoice_number"]} if r["invoice_number"] else None
            party = r["customer_name"]
        qr = _d(r["qty_received"])
        out.append({
            "key": f"s{r['id']}", "source": "SAGE", "sku": r["sku"], "date": r["txn_date"], "kind": kind,
            "qty_received": r["qty_received"], "item_cost": (_d(r["received_cost"]) / qr).quantize(Decimal("0.01")) if qr else None,
            "received_value": r["received_cost"], "qty_adjusted": r["qty_adjusted"], "adjusted_value": r["adjusted_cost"],
            "qty_sold": r["qty_sold"], "cost_of_sales": r["cost_of_sales"], "remaining_qty": r["remaining_qty"],
            "remaining_value": r["remaining_value"], "party": party,
            "customer_id": r["customer_id"] if kind != "Received" else None,
            "supplier_id": r["supplier_id"] if kind == "Received" else None,
            "doc": doc, "batch": None, "possible": [
                {"type": "sageinvoice", "id": c["invoice_number"], "label": c["invoice_number"], "party": c["customer_name"],
                 "quantity": c["quantity"]} for c in cands.get((r["sku"], r["txn_date"]), [])] if not doc and kind != "Received" and kind != "Adjustment" else [],
        })
    return out


def _ace_rows(conn, e: str, skus: List[str], date_from: dt.date, date_to: dt.date) -> List[Dict[str, Any]]:
    rows = q(conn, """SELECT t.id, t.sku, t.txn_date, t.txn_type, t.quantity, t.unit_cost, t.total_cost, t.reference,
                             t.source_type, t.source_id, t.customer_id, t.supplier_id::text AS supplier_id,
                             b.id::text AS batch_id, b.batch_number, b.pack_batch_number, c.name AS customer_name, s.name AS supplier_name
                      FROM fin_inventory_transactions t LEFT JOIN fin_batches b ON b.id=t.batch_id
                      LEFT JOIN customers c ON c.id=t.customer_id LEFT JOIN suppliers s ON s.id=t.supplier_id
                      WHERE t.legal_entity_id=%s AND t.sku = ANY(%s) AND t.txn_date BETWEEN %s AND %s
                      ORDER BY t.sku, t.txn_date, t.created_at""", (e, skus, date_from, date_to))
    out = []
    for r in rows:
        qn, cost, tt = _d(r["quantity"]), _d(r["total_cost"]), r["txn_type"]
        dtype = SOURCE_DRILL.get(r["source_type"] or "")
        doc = {"type": dtype, "id": str(r["source_id"]), "label": r["reference"] or TYPE_LABEL.get(tt, tt)} if dtype and r["source_id"] else None
        out.append({
            "key": f"a{r['id']}", "source": "ACE", "sku": r["sku"], "date": r["txn_date"], "kind": TYPE_LABEL.get(tt, tt.title()),
            "qty_received": qn if tt in RECEIVED_TYPES else None, "item_cost": r["unit_cost"] if tt in RECEIVED_TYPES else None,
            "received_value": cost if tt in RECEIVED_TYPES else None,
            "qty_adjusted": qn if tt not in RECEIVED_TYPES + SOLD_TYPES else None,
            "adjusted_value": cost if tt not in RECEIVED_TYPES + SOLD_TYPES else None,
            "qty_sold": -qn if tt in SOLD_TYPES else None, "cost_of_sales": -cost if tt in SOLD_TYPES else None,
            "_dq": qn, "_dv": cost, "party": r["customer_name"] or r["supplier_name"],
            "customer_id": r["customer_id"], "supplier_id": r["supplier_id"], "doc": doc,
            "batch": {"id": r["batch_id"], "label": r["pack_batch_number"] or r["batch_number"]} if r["batch_id"] else None,
            "possible": [],
        })
    return out


def item_costing(conn, e: str, date_from: dt.date, date_to: dt.date, *, search: Optional[str] = None,
                 sku: Optional[str] = None, sku_from: Optional[str] = None, sku_to: Optional[str] = None,
                 offset: int = 0, limit: int = 25) -> Dict[str, Any]:
    """Items (paged, A-Z, only those with stock or movements in the period) with their movements."""
    b = _bounds(conn, e, date_from, date_to)
    items = _items(conn, e, search, sku, sku_from, sku_to)
    skus = [i["sku"] for i in items]
    opening = _openings(conn, e, b, skus)
    # which items move in the period (cheap counts first, so paging is over items that have something to show)
    moving = set()
    if skus and b["h"] and b["sage_to"] and date_from <= b["sage_to"]:
        moving |= {r["sku"] for r in q(conn, """SELECT DISTINCT sku FROM fin_sage_item_costing WHERE legal_entity_id=%s
                                                AND sku = ANY(%s) AND txn_date BETWEEN %s AND %s""", (e, skus, date_from, b["sage_to"]))}
    if skus and b["ace_from"] <= date_to:
        moving |= {r["sku"] for r in q(conn, """SELECT DISTINCT sku FROM fin_inventory_transactions WHERE legal_entity_id=%s
                                                AND sku = ANY(%s) AND txn_date BETWEEN %s AND %s""", (e, skus, b["ace_from"], date_to))}
    shown = [i for i in items if i["sku"] in moving or opening[i["sku"]]["qty"] != 0]
    page = shown[offset:offset + limit]
    psk = [i["sku"] for i in page]
    sage = _sage_rows(conn, e, psk, date_from, b["sage_to"]) if psk and b["h"] and b["sage_to"] and date_from <= b["sage_to"] else []
    ace = _ace_rows(conn, e, psk, b["ace_from"], date_to) if psk and b["ace_from"] <= date_to else []
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in sage + ace:
        by.setdefault(r["sku"], []).append(r)
    out = []
    for i in page:
        s = i["sku"]; o = opening[s]
        qty, val = o["qty"], o["value"]
        moves = sorted(by.get(s, []), key=lambda r: (r["date"], 0 if r["source"] == "SAGE" else 1))
        t = {"received": ZERO, "adjusted": ZERO, "sold": ZERO, "cost_of_sales": ZERO}
        for r in moves:
            if r["source"] == "SAGE":
                qty, val = _d(r["remaining_qty"]), _d(r["remaining_value"])
            else:
                qty += r.pop("_dq"); val += r.pop("_dv")
                r["remaining_qty"], r["remaining_value"] = qty, val
            t["received"] += _d(r["qty_received"]); t["adjusted"] += _d(r["qty_adjusted"])
            t["sold"] += _d(r["qty_sold"]); t["cost_of_sales"] += _d(r["cost_of_sales"])
        out.append({"sku": s, "name": i["name"], "opening_qty": o["qty"], "opening_value": o["value"], "rows": moves,
                    "closing_qty": qty, "closing_value": val, "totals": t})
    return {"date_from": date_from, "date_to": date_to, "history_until": b["h"], "items": out,
            "items_total": len(shown), "offset": offset, "limit": limit}
