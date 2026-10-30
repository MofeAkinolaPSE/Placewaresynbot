"""Maintain - the records behind the books, as Sage's Maintain menu (Frontdesk design meeting, 26 Oct 2026).

Maintain Inventory Items: every item ID with its description, class, prices, GL accounts, costing, stock
(on hand, held for invoices awaiting QC / Finance, available), reorder level and quantity, preferred vendor,
UPC, part number, location, weight - and its batches (number on the pack, manufacture and expiry dates).

The client tells lots of one product apart by a letter on the item ID - CLEXANE 40mg(K) ... (Z), then
(Z)i, (Z)ii ... - because each new delivery can come at a new price. Here an item shows its whole family in
that order (price, stock, first received, expiry of each lot), and a new lot is created with the next code
already worked out.

Maintain Vendors: Vendor ID, name, contact, account number, addresses, telephones, e-mail, web site,
vendor type, terms, expense account, inactive.
"""
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from src.fin import audit
from src.fin.db import ZERO, ex, q, q1
from src.fin.errors import FinError, invalid, not_found

# "CLEXANE 40mg(Z)iv" -> ("CLEXANE 40mg", "Z", "iv")
_LOT = re.compile(r"^(?P<base>.*?)\s*\((?P<letter>[A-Za-z])\)\s*(?P<roman>[ivxlcIVXLC]*)\s*$")
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
PENDING_REQUEST = ("draft", "qc_pending", "qc_passed", "qc_failed", "finance_pending")


def _roman(s: str) -> int:
    s, total, prev = (s or "").lower(), 0, 0
    for ch in reversed(s):
        v = _ROMAN.get(ch, 0)
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _to_roman(n: int) -> str:
    out = ""
    for v, r in ((100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += r; n -= v
    return out


def lot_of(sku: str) -> Optional[Tuple[str, str, str]]:
    """(base, letter, roman) of a lot-coded item ID, or None."""
    m = _LOT.match(sku or "")
    return (m.group("base"), m.group("letter").upper(), m.group("roman").lower()) if m else None


def lot_key(sku: str) -> Tuple[int, int, str]:
    """Order of lots: no letter first, then A..Z, then Z i, Z ii, ... (later deliveries sort later)."""
    p = lot_of(sku)
    if not p:
        return (0, 0, sku)
    return (ord(p[1]) - 64, _roman(p[2]), sku)


def next_lot(skus: List[str], base_hint: str) -> str:
    """The item ID for the next delivery of a product, following the client's lettering."""
    lots = sorted((s for s in skus if lot_of(s)), key=lot_key)
    if not lots:
        return f"{base_hint}(A)"
    base, letter, roman = lot_of(lots[-1])
    sep = "" if lots[-1][len(base):].startswith("(") else " "
    if letter < "Z" and not roman:
        return f"{base}{sep}({chr(ord(letter) + 1)})"
    return f"{base}{sep}(Z){_to_roman(_roman(roman) + 1)}"


def held_by_requests(conn, skus: Optional[List[str]] = None) -> Dict[str, Decimal]:
    """Quantity of each item on Frontdesk invoices raised but not yet approved by Finance - held so the
    same stock is not promised twice (they post and take the stock when Finance approves)."""
    rows = q(conn, f"""SELECT it->>'sku' AS sku, SUM(COALESCE(NULLIF(it->>'quantity','')::numeric, 0)) AS qty
                       FROM frontdesk_invoices f, jsonb_array_elements(f.items) it
                       WHERE f.status = ANY(%s) AND it->>'sku' IS NOT NULL {"AND it->>'sku' = ANY(%s)" if skus else ""}
                       GROUP BY it->>'sku'""", [list(PENDING_REQUEST)] + ([skus] if skus else []))
    return {r["sku"]: Decimal(str(r["qty"] or 0)) for r in rows}


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------

ITEM_FIELDS = ("name", "sales_description", "legacy_class", "standard_price", "reorder_level", "reorder_qty", "uom",
               "upc", "part_number", "location", "weight", "price_levels", "preferred_supplier_id", "status", "product_type")


def list_items(conn, e: str, search: Optional[str] = None, include_inactive: bool = False, limit: int = 300) -> List[Dict[str, Any]]:
    s = f"%{search}%" if search else None
    rows = q(conn, """SELECT p.sku, p.name, p.legacy_class, p.status, p.standard_price, p.product_type,
                             COALESCE((SELECT SUM(qty_remaining) FROM fin_cost_layers l WHERE l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku),0) AS on_hand
                      FROM fin_products p WHERE p.legal_entity_id=%s AND (%s OR p.status='ACTIVE')
                        AND (%s::text IS NULL OR p.sku ILIKE %s OR p.name ILIKE %s)
                      ORDER BY lower(p.name), p.sku LIMIT %s""", (e, include_inactive, s, s, s, limit))
    rows.sort(key=lambda r: (r["name"].lower(), lot_key(r["sku"])))
    return rows


def get_item(conn, e: str, sku: str) -> Dict[str, Any]:
    p = q1(conn, """SELECT p.*, ra.code AS sales_gl, ia.code AS inventory_gl, ca.code AS cogs_gl,
                           ra.name AS sales_gl_name, ia.name AS inventory_gl_name, ca.name AS cogs_gl_name, s.name AS preferred_vendor,
                           s.external_vendor_id AS preferred_vendor_id
                    FROM fin_products p LEFT JOIN fin_accounts ra ON ra.id=p.revenue_account_id
                    LEFT JOIN fin_accounts ia ON ia.id=p.inventory_account_id LEFT JOIN fin_accounts ca ON ca.id=p.cogs_account_id
                    LEFT JOIN suppliers s ON s.id=p.preferred_supplier_id
                    WHERE p.legal_entity_id=%s AND p.sku=%s""", (e, sku))
    if not p:
        raise not_found("Item", sku)
    stock = q1(conn, """SELECT COALESCE(SUM(qty_remaining),0) AS on_hand, COALESCE(SUM(qty_remaining*unit_cost),0) AS value
                        FROM fin_cost_layers WHERE legal_entity_id=%s AND sku=%s""", (e, sku))
    last = q1(conn, """SELECT unit_cost, txn_date FROM fin_inventory_transactions WHERE legal_entity_id=%s AND sku=%s
                       AND txn_type IN ('PURCHASE','OPENING_BALANCE') AND quantity > 0 ORDER BY txn_date DESC, created_at DESC LIMIT 1""", (e, sku))
    if not last:
        last = q1(conn, """SELECT CASE WHEN qty_received > 0 THEN round(received_cost/qty_received, 2) END AS unit_cost, txn_date
                           FROM fin_sage_item_costing WHERE legal_entity_id=%s AND sku=%s AND qty_received > 0
                           ORDER BY txn_date DESC, id DESC LIMIT 1""", (e, sku))
    on_loan = q1(conn, """SELECT COALESCE(SUM(quantity - COALESCE(quantity_returned,0)),0) AS n
                          FROM fin_stock_loans WHERE legal_entity_id=%s AND sku=%s AND status NOT IN ('RETURNED','WRITTEN_OFF')""", (e, sku)) \
        if _has_table(conn, "fin_stock_loans") else {"n": 0}
    held = held_by_requests(conn, [sku]).get(sku, ZERO)
    on_hand = Decimal(str(stock["on_hand"]))
    batches = q(conn, """SELECT b.id::text AS id, b.batch_number, b.lot_code, b.pack_batch_number, b.manufacture_date, b.expiry_date,
                                b.status, s.name AS supplier, b.created_at::date AS created,
                                COALESCE((SELECT SUM(qty_remaining) FROM fin_cost_layers l WHERE l.batch_id=b.id),0) AS on_hand,
                                (SELECT round(SUM(qty_remaining*unit_cost)/NULLIF(SUM(qty_remaining),0),2) FROM fin_cost_layers l WHERE l.batch_id=b.id) AS unit_cost
                         FROM fin_batches b LEFT JOIN suppliers s ON s.id=b.supplier_id
                         WHERE b.legal_entity_id=%s AND b.sku=%s ORDER BY b.expiry_date NULLS LAST, b.created_at""", (e, sku))
    family = q(conn, """SELECT p.sku, p.standard_price, p.status,
                               COALESCE((SELECT SUM(qty_remaining) FROM fin_cost_layers l WHERE l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku),0) AS on_hand,
                               (SELECT MIN(expiry_date) FROM fin_batches b WHERE b.legal_entity_id=p.legal_entity_id AND b.sku=p.sku) AS expiry,
                               COALESCE((SELECT MIN(txn_date) FROM fin_sage_item_costing c WHERE c.legal_entity_id=p.legal_entity_id AND c.sku=p.sku AND qty_received > 0),
                                        (SELECT MIN(txn_date) FROM fin_inventory_transactions t WHERE t.legal_entity_id=p.legal_entity_id AND t.sku=p.sku AND t.quantity > 0)) AS first_received
                        FROM fin_products p WHERE p.legal_entity_id=%s AND p.name=%s""", (e, p["name"]))
    family.sort(key=lambda r: lot_key(r["sku"]))
    for k, f in enumerate(family, start=1):
        f["order"] = k
        f["current"] = f["sku"] == sku
    p.update({"on_hand": on_hand, "value": stock["value"], "held_for_invoices": held, "on_loan": on_loan["n"],
              "available": on_hand - held, "last_unit_cost": (last or {}).get("unit_cost"), "last_received": (last or {}).get("txn_date"),
              "cost_method": "FIFO", "batches": batches, "family": family,
              "next_lot": next_lot([f["sku"] for f in family], p["name"]), "lot": lot_of(sku)})
    return p


def _has_table(conn, name: str) -> bool:
    return bool(q1(conn, "SELECT to_regclass(%s) AS t", (name,))["t"])


def _account(conn, e: str, code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    a = q1(conn, "SELECT id FROM fin_accounts WHERE legal_entity_id=%s AND code=%s", (e, str(code).strip()))
    if not a:
        raise invalid(f"Account {code} is not in the chart of accounts")
    return str(a["id"])


def _item_values(conn, e: str, data: Dict[str, Any]) -> Dict[str, Any]:
    v: Dict[str, Any] = {}
    for k in ITEM_FIELDS:
        if k in data:
            x = data[k]
            if isinstance(x, str):
                x = x.strip() or None
            v[k] = x
    if "status" in v and v["status"] not in ("ACTIVE", "INACTIVE"):
        raise invalid("Status is ACTIVE or INACTIVE")
    for k in ("standard_price", "reorder_level", "reorder_qty", "weight"):
        if v.get(k) is not None and Decimal(str(v[k])) < 0:
            raise invalid(f"{k.replace('_', ' ')} cannot be negative")
    for code_key, col in (("sales_gl", "revenue_account_id"), ("inventory_gl", "inventory_account_id"), ("cogs_gl", "cogs_account_id")):
        if code_key in data:
            v[col] = _account(conn, e, data[code_key])
    if "price_levels" in v:
        from psycopg2.extras import Json
        v["price_levels"] = Json(v["price_levels"] or {})
    if v.get("name") is not None and not v["name"]:
        raise invalid("An item needs a description")
    return v


def update_item(conn, ctx, sku: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("inventory.product.create")
    before = q1(conn, "SELECT * FROM fin_products WHERE legal_entity_id=%s AND sku=%s FOR UPDATE", (ctx.entity_id, sku))
    if not before:
        raise not_found("Item", sku)
    v = _item_values(conn, ctx.entity_id, data)
    if v:
        ex(conn, f"UPDATE fin_products SET {', '.join(f'{k}=%s' for k in v)}, updated_at=now() WHERE id=%s",
           list(v.values()) + [before["id"]])
        audit.record(conn, ctx, "ITEM_MAINTAINED", "product", str(before["id"]), ref=sku,
                     before={k: before.get(k) for k in v if k != "price_levels"}, after={k: data.get(k) for k in data})
    return get_item(conn, ctx.entity_id, sku)


def create_item(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    """A new item, or the next lot of an existing one (`copy_from`: its description, class, prices and
    GL accounts are carried over; the item ID defaults to the next lot code)."""
    ctx.require("inventory.product.create")
    src = None
    if data.get("copy_from"):
        src = q1(conn, "SELECT * FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, data["copy_from"]))
        if not src:
            raise not_found("Item", data["copy_from"])
    sku = str(data.get("sku") or "").strip()
    if not sku and src:
        fam = [r["sku"] for r in q(conn, "SELECT sku FROM fin_products WHERE legal_entity_id=%s AND name=%s", (ctx.entity_id, src["name"]))]
        sku = next_lot(fam, src["name"])
    if not sku:
        raise invalid("Give the item ID")
    if len(sku) > 40:
        raise invalid("The item ID is too long (40 characters at most)")
    if q1(conn, "SELECT 1 FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku)):
        raise FinError("DUPLICATE_RESOURCE", f"Item {sku} already exists")
    base = {k: src.get(k) for k in ("name", "sales_description", "legacy_class", "standard_price", "reorder_level", "reorder_qty",
                                    "uom", "product_type", "revenue_account_id", "inventory_account_id", "cogs_account_id",
                                    "preferred_supplier_id", "location")} if src else {}
    v = {**base, **_item_values(conn, ctx.entity_id, data)}
    if not v.get("name"):
        raise invalid("An item needs a description")
    if not src:
        # a new product: the default stock accounts until finance chooses its own
        from src.fin import rules
        for key, col in (("SALES_DEFAULT", "revenue_account_id"), ("INVENTORY_DEFAULT", "inventory_account_id"), ("COGS_DEFAULT", "cogs_account_id")):
            if not v.get(col):
                a = rules.optional(conn, ctx.entity_id, key)
                if a:
                    v[col] = str(a["id"])
    v.setdefault("product_type", "INVENTORY")
    v.setdefault("uom", "Each")
    cols = ["legal_entity_id", "sku"] + list(v)
    p = q1(conn, f"INSERT INTO fin_products ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
           [ctx.entity_id, sku] + list(v.values()))
    audit.record(conn, ctx, "ITEM_CREATED", "product", str(p["id"]), ref=sku, metadata={"copied_from": data.get("copy_from")})
    return get_item(conn, ctx.entity_id, sku)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

VENDOR_FIELDS = ("external_vendor_id", "name", "contact_name", "account_number", "address", "phone", "telephone_2", "fax",
                 "contact_email", "website", "category", "payment_terms", "tax_id", "bank_details", "expense_account_code", "status")


def list_vendors(conn, search: Optional[str] = None, include_inactive: bool = False) -> List[Dict[str, Any]]:
    s = f"%{search}%" if search else None
    return q(conn, """SELECT id::text AS id, external_vendor_id AS vendor_id, name, contact_name, phone, contact_email, category,
                             payment_terms, COALESCE(status,'active') AS status
                      FROM suppliers WHERE (%s OR COALESCE(status,'active') <> 'inactive')
                        AND (%s::text IS NULL OR name ILIKE %s OR external_vendor_id ILIKE %s)
                      ORDER BY lower(name)""", (include_inactive, s, s, s))


def get_vendor(conn, vendor_id: str) -> Dict[str, Any]:
    v = q1(conn, "SELECT *, id::text AS id, external_vendor_id AS vendor_id FROM suppliers WHERE id::text=%s", (vendor_id,))
    if not v:
        raise not_found("Vendor", vendor_id)
    return v


def _vendor_values(data: Dict[str, Any]) -> Dict[str, Any]:
    v = {}
    for k in VENDOR_FIELDS:
        key = "external_vendor_id" if k == "external_vendor_id" and "vendor_id" in data else k
        src_key = "vendor_id" if k == "external_vendor_id" and "vendor_id" in data else k
        if src_key in data:
            x = data[src_key]
            v[key] = (x.strip() or None) if isinstance(x, str) else x
    if "external_vendor_id" in v and v["external_vendor_id"] and (len(v["external_vendor_id"]) > 20 or any(c in v["external_vendor_id"] for c in "*?+")):
        raise invalid("A Vendor ID has up to 20 characters and cannot contain * ? or +")
    if "status" in v and v["status"] not in (None, "active", "inactive"):
        raise invalid("Status is active or inactive")
    return v


def save_vendor(conn, ctx, vendor_id: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("payables.vendor.edit")
    v = _vendor_values(data)
    if vendor_id is None:
        if not v.get("name"):
            raise invalid("A vendor needs a name")
        if not v.get("external_vendor_id"):
            v["external_vendor_id"] = re.sub(r"[*?+]", "", v["name"])[:20].strip()
    vid = v.get("external_vendor_id")
    if vid and q1(conn, "SELECT 1 FROM suppliers WHERE external_vendor_id=%s AND id::text <> %s", (vid, vendor_id or "")):
        raise FinError("DUPLICATE_RESOURCE", f"Vendor ID {vid} is already used")
    if vendor_id is None:
        cols = list(v)
        row = q1(conn, f"INSERT INTO suppliers ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id::text AS id",
                 list(v.values()))
        audit.record(conn, ctx, "VENDOR_CREATED", "supplier", row["id"], ref=vid)
        return get_vendor(conn, row["id"])
    before = get_vendor(conn, vendor_id)
    if v:
        ex(conn, f"UPDATE suppliers SET {', '.join(f'{k}=%s' for k in v)}, updated_at=now() WHERE id::text=%s", list(v.values()) + [vendor_id])
        audit.record(conn, ctx, "VENDOR_MAINTAINED", "supplier", vendor_id, ref=before.get("external_vendor_id"),
                     before={k: before.get(k) for k in v}, after=v)
    return get_vendor(conn, vendor_id)
