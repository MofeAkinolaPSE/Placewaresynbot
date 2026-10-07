"""Sage transaction history behind the cut-over balances (display + lineage only).

The cut-over loads Sage as balances. These loaders add the line detail behind
them so a user can see what was sold or bought, in what quantity, to or from
whom, and how each item moved:

    Sales Journal    -> invoice revenue lines + customer      (fin_sage_sales_lines)
    COGS Journal     -> quantity + cost for those lines
    Purchase Journal -> supplier bill lines                   (fin_sage_purchase_lines)
    Item Costing     -> every receipt / sale / adjustment per Sage item
                        (fin_sage_item_costing); also pins history lines to
                        the exact Sage item (lot) and quantity

Nothing here posts to the ledger. Loading a file replaces that kind's history
inside the file's date range, so a later July-to-date export never duplicates.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import execute_values

from src.fin import audit, inventory
from src.fin.db import ZERO, ex, money, q, q1, qty
from src.fin.errors import invalid

KINDS = ("SALES_JOURNAL", "COGS_JOURNAL", "PURCHASE_JOURNAL", "ITEM_COSTING")


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _dec(v: Any) -> Decimal:
    return ZERO if v in (None, "") else money(str(v).replace(",", ""))


def _d(v: Any) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = _s(v)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", _s(s)).lower()


def _rows(rows, header_index, col, must, cols):
    h, idx = header_index(rows, must)
    pos = {k: col(idx, *names) for k, names in cols.items()}
    out = []
    for r in rows[h + 1:]:
        get = lambda k: r[pos[k]] if pos.get(k) is not None and pos[k] < len(r) else None
        d = _d(get("date"))
        if not d:
            continue  # totals and blank separator rows
        out.append({"date": d.isoformat(), **{k: get(k) for k in pos if k != "date"}})
    return out


def _span(rows):
    ds = [r["date"] for r in rows if r.get("date")]
    return (min(ds), max(ds)) if ds else (None, None)


# ---------------------------------------------------------------------------
# Parsers (header helpers are passed in from migration.py)
# ---------------------------------------------------------------------------

def parse_sales_journal(rows, header_index, col):
    out = _rows(rows, header_index, col, ("account id", "invoice/cm", "debit"),
                {"date": ("date",), "account": ("account id",), "ref": ("invoice/cm #", "invoice/cm"),
                 "desc": ("line description",), "debit": ("debit amnt", "debit amount", "debit"),
                 "credit": ("credit amnt", "credit amount", "credit")})
    out = [{"date": r["date"], "account": _s(r["account"]), "ref": _s(r["ref"]), "desc": _s(r["desc"]),
            "debit": str(_dec(r["debit"])), "credit": str(_dec(r["credit"]))} for r in out]
    f, t = _span(out)
    return {"rows": out, "summary": {"lines": len(out), "invoices": len({r["ref"] for r in out}), "from": f, "to": t}, "issues": []}


def parse_cogs_journal(rows, header_index, col):
    out = _rows(rows, header_index, col, ("gl acct", "reference", "qty"),
                {"date": ("date",), "account": ("gl acct id", "gl acct"), "ref": ("reference",), "qty": ("qty",),
                 "desc": ("line description",), "debit": ("debit amount", "debit"), "credit": ("credit amount", "credit")})
    out = [{"date": r["date"], "account": _s(r["account"]), "ref": _s(r["ref"]), "desc": _s(r["desc"]),
            "qty": str(qty(r["qty"] or 0)), "debit": str(_dec(r["debit"])), "credit": str(_dec(r["credit"]))} for r in out]
    f, t = _span(out)
    return {"rows": out, "summary": {"lines": len(out), "from": f, "to": t}, "issues": []}


def parse_purchase_journal(rows, header_index, col):
    out = _rows(rows, header_index, col, ("account id", "invoice/cm", "debit"),
                {"date": ("date",), "account": ("account id",), "ref": ("invoice/cm #", "invoice/cm"),
                 "desc": ("line description",), "debit": ("debit amount", "debit"), "credit": ("credit amount", "credit")})
    out = [{"date": r["date"], "account": _s(r["account"]), "ref": _s(r["ref"]), "desc": _s(r["desc"]),
            "debit": str(_dec(r["debit"])), "credit": str(_dec(r["credit"]))} for r in out]
    f, t = _span(out)
    return {"rows": out, "summary": {"lines": len(out), "bills": len({r["ref"] for r in out}), "from": f, "to": t}, "issues": []}


def parse_item_costing(rows, header_index, col):
    h, idx = header_index(rows, ("item id", "qty received", "cost of sales"))
    c = {k: col(idx, *n) for k, n in {"sku": ("item id",), "desc": ("item description",), "date": ("date",),
                                      "qin": ("qty received",), "cin": ("actual cost",), "qadj": ("adjust qty",),
                                      "cadj": ("adjust ($)", "adjust"), "qsold": ("quantity sold",), "csold": ("cost of sales",),
                                      "qrem": ("remaining qty",), "crem": ("remain value",)}.items()}
    out = []
    for r in rows[h + 1:]:
        g = lambda k: r[c[k]] if c[k] is not None and c[k] < len(r) else None
        d = _d(g("date"))
        if not d or not _s(g("sku")):
            continue  # item header rows carry no date
        out.append({"sku": _s(g("sku")), "desc": _s(g("desc")), "date": d.isoformat(), "qin": str(qty(g("qin") or 0)),
                    "cin": str(_dec(g("cin"))), "qadj": str(qty(g("qadj") or 0)), "cadj": str(_dec(g("cadj"))),
                    "qsold": str(qty(g("qsold") or 0)), "csold": str(_dec(g("csold"))),
                    "qrem": str(qty(g("qrem") or 0)), "crem": str(_dec(g("crem")))})
    f, t = _span(out)
    return {"rows": out, "summary": {"movements": len(out), "items": len({r["sku"] for r in out}), "from": f, "to": t}, "issues": []}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _accounts(conn, entity_id):
    return {r["code"]: r for r in q(conn, "SELECT code, account_type, subtype FROM fin_accounts WHERE legal_entity_id=%s", (entity_id,))}


def _mapped_code(conn, entity_id, key):
    r = q1(conn, """SELECT a.code FROM fin_account_mappings m JOIN fin_accounts a ON a.id=m.account_id
                    WHERE m.legal_entity_id=%s AND m.mapping_key=%s""", (entity_id, key))
    if not r:
        raise invalid(f"Posting rule {key} is not mapped yet - load the chart of accounts first")
    return r["code"]


def _group(rows):
    g: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in rows:
        g.setdefault((r["ref"], r["date"]), []).append(r)
    return g


def load_sales_journal(conn, ctx, b):
    acc = _accounts(conn, ctx.entity_id)
    ar = _mapped_code(conn, ctx.entity_id, "AR_CONTROL")
    f, t = _span(b["rows"])
    ex(conn, "DELETE FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND invoice_date BETWEEN %s AND %s", (ctx.entity_id, f, t))
    customers: Dict[str, int] = {}
    for r in q(conn, "SELECT id, name, customer_code FROM customers"):
        for k in (r["name"], r["customer_code"]):
            if k:
                customers.setdefault(_norm(k), r["id"])
    groups = _group(b["rows"])
    buf = []
    for (ref, date), lines in groups.items():
        cust = next((l["desc"] for l in lines if l["account"] == ar), None)
        cid = customers.get(_norm(cust)) if cust else None
        no = 0
        for l in lines:
            a = acc.get(l["account"])
            if l["account"] == ar or not a or a["account_type"] != "REVENUE":
                continue  # AR, inventory and cost-of-sales sides are not invoice lines
            no += 1
            buf.append((ctx.entity_id, b["id"], ref, date, cid, cust, no, l["desc"], l["account"],
                        money(l["credit"]) - money(l["debit"])))
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO fin_sage_sales_lines (legal_entity_id, batch_id, invoice_number, invoice_date, customer_id,
                               customer_name, line_no, description, account_code, amount) VALUES %s""", buf, page_size=5000)
    return {"sales_lines": len(buf), "invoices": len(groups), "from": f, "to": t, **resolve(conn, ctx.entity_id)}


def load_cogs_journal(conn, ctx, b):
    acc = _accounts(conn, ctx.entity_id)
    f, t = _span(b["rows"])
    if not q1(conn, "SELECT 1 FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND invoice_date BETWEEN %s AND %s LIMIT 1",
              (ctx.entity_id, f, t)):
        raise invalid("Load the Sales Journal for the same period first; the COGS Journal adds quantity and cost to its lines")
    agg: Dict[Tuple[str, str], List[Decimal]] = {}
    for r in b["rows"]:
        a = acc.get(r["account"])
        if not a or a["subtype"] != "COST_OF_SALES":
            continue
        sign = 1 if money(r["debit"]) > 0 else -1
        v = agg.setdefault((r["ref"], _norm(r["desc"])), [Decimal("0"), ZERO])
        v[0] += sign * qty(r["qty"])
        v[1] += money(r["debit"]) - money(r["credit"])
    ex(conn, "CREATE TEMP TABLE IF NOT EXISTS _sage_cogs (ref text, descr text, q numeric, c numeric)")
    ex(conn, "TRUNCATE _sage_cogs")
    with conn.cursor() as cur:
        execute_values(cur, "INSERT INTO _sage_cogs VALUES %s", [(k[0], k[1], v[0], v[1]) for k, v in agg.items()], page_size=5000)
    # One quantity/cost figure per (invoice, item): it goes on the first line of that item.
    ex(conn, """UPDATE fin_sage_sales_lines s SET quantity=m.q, cost=m.c
                FROM (SELECT DISTINCT ON (l.invoice_number, lower(regexp_replace(trim(l.description), '\\s+', ' ', 'g'))) l.id, g.q, g.c
                      FROM fin_sage_sales_lines l
                      JOIN _sage_cogs g ON g.ref=l.invoice_number AND g.descr=lower(regexp_replace(trim(l.description), '\\s+', ' ', 'g'))
                      WHERE l.legal_entity_id=%s AND l.invoice_date BETWEEN %s AND %s
                      ORDER BY l.invoice_number, lower(regexp_replace(trim(l.description), '\\s+', ' ', 'g')), l.line_no) m
                WHERE s.id=m.id""", (ctx.entity_id, f, t))
    ex(conn, "DROP TABLE IF EXISTS _sage_cogs")
    n = q1(conn, """SELECT COUNT(*) n FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND quantity IS NOT NULL
                    AND invoice_date BETWEEN %s AND %s""", (ctx.entity_id, f, t))["n"]
    return {"cost_lines": len(agg), "sales_lines_with_quantity": n, **resolve(conn, ctx.entity_id)}


def load_purchase_journal(conn, ctx, b):
    ap = _mapped_code(conn, ctx.entity_id, "AP_CONTROL")
    f, t = _span(b["rows"])
    ex(conn, "DELETE FROM fin_sage_purchase_lines WHERE legal_entity_id=%s AND bill_date BETWEEN %s AND %s", (ctx.entity_id, f, t))
    suppliers: Dict[str, str] = {}
    for r in q(conn, "SELECT id, name, external_vendor_id FROM suppliers"):
        for k in (r["name"], r["external_vendor_id"]):
            if k:
                suppliers.setdefault(_norm(k), str(r["id"]))
    groups = _group(b["rows"])
    buf = []
    for (ref, date), lines in groups.items():
        vendor = next((l["desc"] for l in lines if l["account"] == ap), None)
        sid = suppliers.get(_norm(vendor)) if vendor else None
        no = 0
        for l in lines:
            if l["account"] == ap:
                continue
            no += 1
            buf.append((ctx.entity_id, b["id"], ref, date, sid, vendor, no, l["desc"], l["account"],
                        money(l["debit"]) - money(l["credit"])))
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO fin_sage_purchase_lines (legal_entity_id, batch_id, bill_number, bill_date, supplier_id,
                               supplier_name, line_no, description, account_code, amount) VALUES %s""", buf, page_size=5000)
    return {"purchase_lines": len(buf), "bills": len(groups), "from": f, "to": t, **resolve(conn, ctx.entity_id)}


def load_item_costing(conn, ctx, b):
    rows = b["rows"]
    f, t = _span(rows)
    skus = sorted({r["sku"] for r in rows})
    ex(conn, "DELETE FROM fin_sage_item_costing WHERE legal_entity_id=%s AND sku = ANY(%s) AND txn_date BETWEEN %s AND %s",
       (ctx.entity_id, skus, f, t))
    nz = lambda v: v if v else None
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO fin_sage_item_costing (legal_entity_id, batch_id, sku, description, txn_date, qty_received,
                               received_cost, qty_adjusted, adjusted_cost, qty_sold, cost_of_sales, remaining_qty, remaining_value) VALUES %s""",
                       [(ctx.entity_id, b["id"], r["sku"], r["desc"], r["date"], nz(qty(r["qin"])), nz(money(r["cin"])),
                         nz(qty(r["qadj"])), nz(money(r["cadj"])), nz(qty(r["qsold"])), nz(money(r["csold"])),
                         qty(r["qrem"]), money(r["crem"])) for r in rows], page_size=5000)
    return {"movements": len(rows), "items": len(skus), "from": f, "to": t, **resolve(conn, ctx.entity_id)}


PARSERS = {"SALES_JOURNAL": parse_sales_journal, "COGS_JOURNAL": parse_cogs_journal,
           "PURCHASE_JOURNAL": parse_purchase_journal, "ITEM_COSTING": parse_item_costing}
LOADERS = {"SALES_JOURNAL": load_sales_journal, "COGS_JOURNAL": load_cogs_journal,
           "PURCHASE_JOURNAL": load_purchase_journal, "ITEM_COSTING": load_item_costing}


# ---------------------------------------------------------------------------
# Resolution: customers, suppliers and the exact Sage item (lot)
# ---------------------------------------------------------------------------

def resolve(conn, entity_id: str) -> Dict[str, Any]:
    """Pin history lines to customers, suppliers and the exact Sage item.

    Sage journals name the product (MENACTRA) but stock each lot as its own item
    (MENACTRA (P), MENACTRA (R)). The Item Costing report records the item, date,
    quantity and cost of every sale and receipt, so a line whose name, date,
    quantity and cost agree with one costing entry gets that item. A name used by
    a single item needs no costing match. Safe to run repeatedly."""
    # Customers of opening invoices are known exactly: OB invoice source_id = batch:customer:sage invoice no.
    ex(conn, """UPDATE fin_sage_sales_lines s SET customer_id = i.customer_id
                FROM fin_sales_invoices i
                WHERE s.legal_entity_id=%s AND s.customer_id IS NULL AND i.legal_entity_id=s.legal_entity_id AND i.is_opening
                  AND split_part(i.source_id, ':', 3) = s.invoice_number""", (entity_id,))
    for table in ("fin_sage_sales_lines", "fin_sage_purchase_lines"):
        ex(conn, f"""WITH u AS (SELECT lower(trim(name)) n, MIN(sku) sku FROM fin_products WHERE legal_entity_id=%s
                                GROUP BY 1 HAVING COUNT(*)=1)
                     UPDATE {table} s SET sku=u.sku FROM u
                     WHERE s.legal_entity_id=%s AND s.sku IS NULL AND lower(trim(s.description))=u.n""", (entity_id, entity_id))
    ex(conn, """UPDATE fin_sage_sales_lines s SET sku = m.sku FROM (
                  SELECT DISTINCT ON (l.id) l.id, c.sku
                  FROM fin_sage_sales_lines l
                  JOIN fin_products p ON p.legal_entity_id=l.legal_entity_id AND lower(trim(p.name))=lower(trim(l.description))
                  JOIN fin_sage_item_costing c ON c.legal_entity_id=l.legal_entity_id AND c.sku=p.sku AND c.txn_date=l.invoice_date
                       AND c.qty_sold = l.quantity AND abs(COALESCE(c.cost_of_sales,0) - COALESCE(l.cost,0)) < 1
                  WHERE l.legal_entity_id=%s AND l.sku IS NULL AND l.quantity IS NOT NULL
                  ORDER BY l.id, c.id) m
                WHERE s.id=m.id""", (entity_id,))
    ex(conn, """UPDATE fin_sage_purchase_lines s SET sku = m.sku, quantity = m.q FROM (
                  SELECT DISTINCT ON (l.id) l.id, c.sku, c.qty_received q
                  FROM fin_sage_purchase_lines l
                  JOIN fin_sage_item_costing c ON c.legal_entity_id=l.legal_entity_id AND c.txn_date=l.bill_date
                       AND c.qty_received IS NOT NULL AND abs(COALESCE(c.received_cost,0) - l.amount) < 1
                  LEFT JOIN fin_products p ON p.legal_entity_id=l.legal_entity_id AND p.sku=c.sku
                  WHERE l.legal_entity_id=%s AND l.quantity IS NULL
                    AND (l.sku = c.sku OR (l.sku IS NULL AND lower(trim(COALESCE(p.name, c.description)))=lower(trim(l.description))))
                  ORDER BY l.id, c.id) m
                WHERE s.id=m.id""", (entity_id,))
    st = q1(conn, """SELECT (SELECT COUNT(*) FROM fin_sage_sales_lines WHERE legal_entity_id=%s) sales,
                            (SELECT COUNT(*) FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND sku IS NOT NULL) sales_with_item,
                            (SELECT COUNT(*) FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND customer_id IS NOT NULL) sales_with_customer,
                            (SELECT COUNT(*) FROM fin_sage_purchase_lines WHERE legal_entity_id=%s) purchases,
                            (SELECT COUNT(*) FROM fin_sage_purchase_lines WHERE legal_entity_id=%s AND sku IS NOT NULL) purchases_with_item""",
             (entity_id,) * 5)
    return {"history": dict(st)}


# ---------------------------------------------------------------------------
# Opening stock lots
# ---------------------------------------------------------------------------

_LOT = re.compile(r"\(([^()]*)\)?\s*([ivx]*)\s*$", re.I)


def lot_label(sku: str) -> str:
    """Placeware's Sage lot letter: 'ROTARIX(L)' -> 'L', 'CLEXANE 40mg(Z)iii' -> 'Z iii'."""
    m = _LOT.search(sku or "")
    if not m or not (m.group(1) or "").strip():
        return "SAGE"
    return " ".join(x for x in ((m.group(1) or "").strip(), (m.group(2) or "").strip()) if x)[:30]


def assign_opening_batches(conn, ctx) -> Dict[str, Any]:
    """Give migrated opening stock its Sage lot and expiry (from the Sage item snapshot)."""
    ctx.require("migration.load")
    done = 0
    for t in q(conn, """SELECT t.id, t.sku, l.id AS layer_id FROM fin_inventory_transactions t
                        JOIN fin_cost_layers l ON l.inventory_txn_id=t.id
                        WHERE t.legal_entity_id=%s AND t.txn_type='OPENING_BALANCE' AND t.batch_id IS NULL""", (ctx.entity_id,)):
        snap = q1(conn, """SELECT expiry_date, NULLIF(batch_number,'') AS batch_number FROM sage_items_snapshot WHERE item_id=%s
                           ORDER BY imported_at DESC LIMIT 1""", (t["sku"],))
        number = (snap or {}).get("batch_number") or lot_label(t["sku"])
        bid = inventory.ensure_batch(conn, ctx.entity_id, t["sku"], number, expiry_date=(snap or {}).get("expiry_date"))
        ex(conn, "UPDATE fin_inventory_transactions SET batch_id=%s WHERE id=%s", (bid, t["id"]))
        ex(conn, "UPDATE fin_cost_layers SET batch_id=%s WHERE id=%s", (bid, t["layer_id"]))
        done += 1
    if done:
        audit.record(conn, ctx, "OPENING_BATCHES_ASSIGNED", "inventory", ctx.entity_id, metadata={"movements": done})
    return {"opening_movements_batched": done}


# ---------------------------------------------------------------------------
# Reads used by the lineage sheets
# ---------------------------------------------------------------------------

def invoice_lines(conn, entity_id: str, sage_invoice_no: str, customer_id: Optional[int]) -> List[Dict[str, Any]]:
    return q(conn, """SELECT line_no, invoice_date, description, sku, account_code, quantity, amount, cost
                      FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND invoice_number=%s
                        AND (%s::bigint IS NULL OR customer_id IS NULL OR customer_id=%s)
                      ORDER BY invoice_date, line_no""", (entity_id, sage_invoice_no, customer_id, customer_id))


def bill_lines(conn, entity_id: str, supplier_invoice_no: str, supplier_id: Optional[str]) -> List[Dict[str, Any]]:
    return q(conn, """SELECT line_no, bill_date, description, sku, account_code, quantity, amount
                      FROM fin_sage_purchase_lines WHERE legal_entity_id=%s AND bill_number=%s
                        AND (%s::uuid IS NULL OR supplier_id IS NULL OR supplier_id=%s::uuid)
                      ORDER BY bill_date, line_no""", (entity_id, supplier_invoice_no, supplier_id, supplier_id))


def _opening_invoice_join():
    return """LEFT JOIN fin_sales_invoices oi ON oi.legal_entity_id=s.legal_entity_id AND oi.is_opening
                   AND split_part(oi.source_id, ':', 3)=s.invoice_number AND oi.customer_id=s.customer_id"""


def product_history(conn, entity_id: str, sku: str, limit: int = 300) -> Dict[str, Any]:
    sales = q(conn, f"""SELECT s.invoice_number, s.invoice_date, s.customer_id, COALESCE(c.name, s.customer_name) AS customer_name,
                               s.quantity, s.amount, s.cost, oi.id AS opening_invoice_id
                        FROM fin_sage_sales_lines s LEFT JOIN customers c ON c.id=s.customer_id {_opening_invoice_join()}
                        WHERE s.legal_entity_id=%s AND s.sku=%s ORDER BY s.invoice_date DESC LIMIT %s""", (entity_id, sku, limit))
    buyers = q(conn, """SELECT s.customer_id, COALESCE(c.name, MAX(s.customer_name)) AS customer_name, SUM(s.quantity) AS quantity,
                               SUM(s.amount) AS amount, COUNT(DISTINCT s.invoice_number) AS invoices, MAX(s.invoice_date) AS last_date
                        FROM fin_sage_sales_lines s LEFT JOIN customers c ON c.id=s.customer_id
                        WHERE s.legal_entity_id=%s AND s.sku=%s GROUP BY s.customer_id, c.name ORDER BY quantity DESC NULLS LAST LIMIT 100""",
                   (entity_id, sku))
    costing = q(conn, """SELECT txn_date, qty_received, received_cost, qty_adjusted, adjusted_cost, qty_sold, cost_of_sales,
                                remaining_qty, remaining_value
                         FROM fin_sage_item_costing WHERE legal_entity_id=%s AND sku=%s ORDER BY txn_date DESC, id DESC LIMIT %s""",
                      (entity_id, sku, limit))
    purchases = q(conn, """SELECT p.bill_number, p.bill_date, p.supplier_id, COALESCE(s.name, p.supplier_name) AS supplier_name, p.quantity, p.amount,
                                  b.id AS opening_bill_id
                           FROM fin_sage_purchase_lines p LEFT JOIN suppliers s ON s.id=p.supplier_id
                           LEFT JOIN fin_supplier_bills b ON b.legal_entity_id=p.legal_entity_id AND b.is_opening
                                AND b.supplier_invoice_number=p.bill_number AND b.supplier_id=p.supplier_id
                           WHERE p.legal_entity_id=%s AND p.sku=%s ORDER BY p.bill_date DESC LIMIT 100""", (entity_id, sku))
    return {"sales": sales, "buyers": buyers, "costing": costing, "purchases": purchases}


def customer_history(conn, entity_id: str, customer_id: int) -> Dict[str, Any]:
    products = q(conn, """SELECT s.sku, COALESCE(p.name, MAX(s.description)) AS name, SUM(s.quantity) AS quantity, SUM(s.amount) AS amount,
                                 MAX(s.invoice_date) AS last_date
                          FROM fin_sage_sales_lines s LEFT JOIN fin_products p ON p.legal_entity_id=s.legal_entity_id AND p.sku=s.sku
                          WHERE s.legal_entity_id=%s AND s.customer_id=%s
                          GROUP BY s.sku, p.name ORDER BY amount DESC LIMIT 100""", (entity_id, customer_id))
    invoices = q(conn, f"""SELECT s.invoice_number, MIN(s.invoice_date) AS invoice_date, SUM(s.amount) AS amount, COUNT(*) AS lines,
                                  MIN(oi.id::text) AS opening_invoice_id
                           FROM fin_sage_sales_lines s {_opening_invoice_join()}
                           WHERE s.legal_entity_id=%s AND s.customer_id=%s
                           GROUP BY s.invoice_number ORDER BY MIN(s.invoice_date) DESC LIMIT 100""", (entity_id, customer_id))
    return {"products": products, "invoices": invoices}


def bill_detail(conn, entity_id: str, number: str, supplier_id: Optional[str]) -> Dict[str, Any]:
    """A supplier invoice from the Sage purchase journal that is not an open bill in ACE Books."""
    lines = q(conn, """SELECT p.*, COALESCE(s.name, p.supplier_name) AS supplier FROM fin_sage_purchase_lines p
                       LEFT JOIN suppliers s ON s.id=p.supplier_id
                       WHERE p.legal_entity_id=%s AND p.bill_number=%s AND (%s::uuid IS NULL OR p.supplier_id=%s::uuid)
                       ORDER BY p.bill_date, p.line_no""", (entity_id, number, supplier_id, supplier_id))
    return {"bill_number": number, "lines": lines,
            "bill_date": lines[0]["bill_date"] if lines else None,
            "supplier_id": lines[0]["supplier_id"] if lines else None,
            "supplier_name": lines[0]["supplier"] if lines else None,
            "total": sum((money(l["amount"]) for l in lines), ZERO)}


def supplier_bills(conn, entity_id: str, supplier_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Sage purchase-journal invoices for a supplier, excluding those that are ACE Books opening bills."""
    return q(conn, """SELECT p.bill_number, MIN(p.bill_date) AS bill_date, SUM(p.amount) AS amount, COUNT(*) AS lines, SUM(p.quantity) AS quantity
                      FROM fin_sage_purchase_lines p
                      WHERE p.legal_entity_id=%s AND p.supplier_id=%s::uuid
                        AND NOT EXISTS (SELECT 1 FROM fin_supplier_bills b WHERE b.legal_entity_id=p.legal_entity_id AND b.is_opening
                                          AND b.supplier_invoice_number=p.bill_number AND b.supplier_id=p.supplier_id)
                      GROUP BY p.bill_number ORDER BY MIN(p.bill_date) DESC LIMIT %s""", (entity_id, supplier_id, limit))


def invoice_detail(conn, entity_id: str, sage_invoice_no: str) -> Dict[str, Any]:
    """A Sage invoice from history that is not an open item in ACE Books."""
    lines = q(conn, """SELECT s.*, COALESCE(c.name, s.customer_name) AS customer FROM fin_sage_sales_lines s
                       LEFT JOIN customers c ON c.id=s.customer_id
                       WHERE s.legal_entity_id=%s AND s.invoice_number=%s ORDER BY s.invoice_date, s.line_no""", (entity_id, sage_invoice_no))
    return {"invoice_number": sage_invoice_no, "lines": lines,
            "invoice_date": lines[0]["invoice_date"] if lines else None,
            "customer_id": lines[0]["customer_id"] if lines else None,
            "customer_name": lines[0]["customer"] if lines else None,
            "total": sum((money(l["amount"]) for l in lines), ZERO),
            "cost": sum((money(l["cost"]) for l in lines if l["cost"] is not None), ZERO)}
