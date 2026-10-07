"""Stock orders, reorder planning, supplier purchases and the supplier directory,
all read from ACE Books.

What the old screens showed and why it was wrong
  * "Purchase orders" were Sage's Vendor Transaction History (every supplier
    invoice since 2018) imported into sage_purchase_orders_snapshot. There were
    never 1,180 orders and the 72 "open" ones were simply invoices from the last
    180 days. The client does not raise purchase orders in Sage.
  * The reorder queue was filled by the automation from the Sage stock view
    (qty < 10 on every catalogue item, qty 20 each), so it listed 753 dead items.

What this module does instead
  * reorder_plan(): per item, stock on hand (ACE Books FIFO), demand from dated
    sales (Sage history to the cut-over + ACE Books invoices after), the last
    supplier and cost paid, stock already on order, and a suggested quantity.
  * Stock orders are replenishment_requests: requested -> approved -> ordered ->
    received. An ordered item is received when its supplier bill is posted in
    ACE Books (which is what adds the stock, with cost and batch); sync_received()
    links the two, so nothing is keyed twice.
  * purchases(): every supplier invoice - ACE Books bills plus the Sage purchase
    journal history (a Sage invoice still open at the cut-over is its ACE Books
    opening bill, so it appears once).
  * supplier_directory(): balances from ACE Books payables and buying history.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.fin.db import ex, q, q1, tx

# Planning policy. Lead time is not recorded anywhere (no PO dates exist), so it
# is a stated assumption, shown on screen next to the plan.
POLICY = {"demand_days": 180, "lead_days": 30, "safety_days": 14, "cover_days": 60}
OPEN_ORDER_STATES = ("recommended", "approved", "ordered")
_BILL_LIVE = "b.status NOT IN ('VOID','DRAFT')"


def _f(v: Any) -> float:
    return float(v or 0)


# ---------------------------------------------------------------------------
# Purchase lines (ACE Books bills + Sage purchase journal), one definition
# ---------------------------------------------------------------------------

_PURCHASE_LINES = f"""
    SELECT l.sku, b.supplier_id, s.name AS supplier_name, b.bill_date, l.quantity, l.line_total AS amount,
           b.bill_number AS doc_number, 'ACE' AS src
    FROM fin_supplier_bill_lines l JOIN fin_supplier_bills b ON b.id=l.bill_id LEFT JOIN suppliers s ON s.id=b.supplier_id
    WHERE {_BILL_LIVE} AND NOT b.is_opening
    UNION ALL
    SELECT p.sku, p.supplier_id, COALESCE(s.name, p.supplier_name), p.bill_date, p.quantity, p.amount, p.bill_number, 'Sage'
    FROM fin_sage_purchase_lines p LEFT JOIN suppliers s ON s.id=p.supplier_id
"""


def _sales_as_of(conn) -> dt.date:
    r = q1(conn, "SELECT MAX(invoice_date) AS d FROM v_sales_lines")
    return r["d"] or dt.date.today()


# ---------------------------------------------------------------------------
# Reorder plan (per product: every Sage lot code of a product is one product)
# ---------------------------------------------------------------------------

# In Sage each lot was a separate item code - MENACTRA (A) ... MENACTRA (R) - so a
# lot running out is not the product running out. The plan works on the product
# (the item name without its trailing "(lot)"), summing stock, demand and open
# orders across its lot codes.
FAMILY_SQL = r"""regexp_replace(COALESCE({name}, {sku}), '\s*\([^)]*\)\s*$', '')"""
_ITEMS = f"""
    SELECT i.sku, {FAMILY_SQL.format(name="fp.name", sku="i.sku")} AS family, fp.sku IS NOT NULL AS in_books,
           GREATEST(i.current_stock, 0) AS on_hand, i.cost_price, i.expiry_date, i.batch_number
    FROM v_inventory i LEFT JOIN fin_products fp ON fp.sku=i.sku"""


def reorder_plan() -> Dict[str, Any]:
    p = POLICY
    with tx() as conn:
        as_of = _sales_as_of(conn)
        rows = q(conn, f"""
            WITH items AS ({_ITEMS}),
            stock AS (
                SELECT family, SUM(on_hand) AS on_hand, SUM(on_hand * cost_price) AS value,
                       COUNT(*) AS codes, COUNT(*) FILTER (WHERE on_hand > 0) AS lots_in_stock,
                       json_agg(json_build_object('sku', sku, 'qty', on_hand, 'expiry', expiry_date, 'batch', batch_number,
                                                  'value', on_hand * cost_price) ORDER BY expiry_date NULLS LAST, sku)
                           FILTER (WHERE on_hand > 0) AS lots,
                       bool_or(in_books AND sku = family) AS base_in_books
                FROM items GROUP BY family),
            demand AS (
                SELECT it.family, SUM(s.quantity) AS sold, COUNT(DISTINCT s.invoice_number) AS orders,
                       COUNT(DISTINCT s.customer_pk) AS customers, MAX(s.invoice_date) AS last_sold
                FROM v_sales_lines s JOIN items it ON it.sku=s.sku
                WHERE s.quantity > 0 AND s.invoice_date > %(as_of)s::date - %(days)s AND s.invoice_date <= %(as_of)s
                GROUP BY it.family),
            purch AS (
                SELECT DISTINCT ON (it.family) it.family, x.sku AS last_sku, x.supplier_id, x.supplier_name, x.bill_date AS last_purchase,
                       x.amount / NULLIF(x.quantity, 0) AS last_cost, x.quantity AS last_qty
                FROM ({_PURCHASE_LINES}) x JOIN items it ON it.sku=x.sku
                WHERE x.quantity > 0 ORDER BY it.family, x.bill_date DESC),
            orders AS (
                SELECT it.family, SUM(r.requested_qty) FILTER (WHERE r.status IN ('approved','ordered')) AS on_order,
                       (array_agg(r.id::text ORDER BY r.created_at DESC))[1] AS order_id,
                       (array_agg(r.status ORDER BY r.created_at DESC))[1] AS order_status
                FROM replenishment_requests r JOIN items it ON it.sku=r.sku
                WHERE r.status IN ('recommended','approved','ordered') GROUP BY it.family)
            SELECT st.*, d.sold, d.orders, d.customers, d.last_sold,
                   pu.last_sku, pu.supplier_id, pu.supplier_name, pu.last_purchase, pu.last_cost, pu.last_qty,
                   o.on_order, o.order_id, o.order_status
            FROM stock st LEFT JOIN demand d USING (family) LEFT JOIN purch pu USING (family) LEFT JOIN orders o USING (family)
            WHERE COALESCE(d.sold, 0) > 0 OR st.on_hand > 0 OR o.order_id IS NOT NULL""",
                 {"as_of": as_of, "days": p["demand_days"]})

    items: List[Dict[str, Any]] = []
    for r in rows:
        on_hand = _f(r["on_hand"])
        on_order = _f(r["on_order"])
        daily = _f(r["sold"]) / p["demand_days"]
        value = _f(r["value"])
        unit_cost = _f(r["last_cost"]) or (value / on_hand if on_hand else 0.0)
        avail = on_hand + on_order
        rop = daily * (p["lead_days"] + p["safety_days"])
        if daily <= 0:
            status = "no_recent_sales"
        elif on_hand <= 0 and on_order <= 0:
            status = "out_of_stock"
        elif avail <= rop:
            status = "reorder_now"
        elif avail <= rop + daily * 30:
            status = "reorder_soon"
        else:
            status = "healthy"
        suggested = 0
        if status in ("out_of_stock", "reorder_now", "reorder_soon"):
            suggested = max(0, math.ceil(daily * (p["lead_days"] + p["cover_days"]) - avail))
        cover = round(on_hand / daily, 1) if daily > 0 else None

        # Expiry, lot by lot in FIFO order: units that will not sell before their lot expires.
        lots = r["lots"] or []
        sold_through, risk_units, risk_value = 0.0, 0.0, 0.0
        for lot in lots:
            qty, exp = _f(lot["qty"]), lot["expiry"]
            if exp:
                days_left = (dt.date.fromisoformat(str(exp)[:10]) - as_of).days
                can_sell = max(0.0, daily * days_left - sold_through) if daily > 0 else 0.0
                unsold = max(0.0, qty - can_sell) if days_left <= 365 else 0.0
                if unsold > 0:
                    risk_units += unsold
                    risk_value += _f(lot["value"]) * unsold / qty
            sold_through += qty
        first = lots[0] if lots else {}
        # Order against the product itself when ACE Books has it, else the lot code last bought.
        order_sku = r["family"] if r["base_in_books"] else (r["last_sku"] or first.get("sku") or r["family"])
        items.append({
            "sku": order_sku, "family": r["family"], "name": r["family"], "status": status,
            "codes": r["codes"], "lots_in_stock": r["lots_in_stock"], "lots": lots,
            "on_hand": on_hand, "on_order": on_order, "stock_value": round(value, 2),
            "monthly_demand": round(daily * 30, 1), "sold": _f(r["sold"]), "orders": r["orders"] or 0,
            "customers": r["customers"] or 0, "last_sold": r["last_sold"],
            "days_cover": cover, "reorder_point": math.ceil(rop), "suggested_qty": suggested,
            "est_cost": round(suggested * unit_cost, 2), "unit_cost": round(unit_cost, 2) if unit_cost else None,
            "supplier_id": str(r["supplier_id"]) if r["supplier_id"] else None, "supplier_name": r["supplier_name"],
            "last_purchase": r["last_purchase"], "last_qty": _f(r["last_qty"]) or None, "last_sku": r["last_sku"],
            "next_expiry": first.get("expiry"), "next_batch": first.get("batch"), "next_sku": first.get("sku"),
            "expiry_risk": risk_units > 0, "expiry_risk_units": round(risk_units), "expiry_risk_value": round(risk_value, 2),
            "order_id": r["order_id"], "order_status": r["order_status"],
        })
    rank = {"out_of_stock": 0, "reorder_now": 1, "reorder_soon": 2, "healthy": 3, "no_recent_sales": 4}
    items.sort(key=lambda i: (rank[i["status"]], -(i["monthly_demand"] or 0)))
    counts: Dict[str, int] = defaultdict(int)
    for i in items:
        counts[i["status"]] += 1
    to_order = [i for i in items if i["status"] in ("out_of_stock", "reorder_now") and not i["order_id"]]
    return {
        "as_of": as_of, "policy": p, "items": items, "counts": dict(counts),
        "to_order_count": len(to_order), "to_order_value": round(sum(i["est_cost"] for i in to_order), 2),
        "expiry_risk_count": sum(1 for i in items if i["expiry_risk"]),
        "expiry_risk_value": round(sum(i["expiry_risk_value"] for i in items), 2),
    }


# ---------------------------------------------------------------------------
# Stock orders (replenishment_requests)
# ---------------------------------------------------------------------------

def sync_received(conn) -> int:
    """Close ordered items whose supplier bill has been posted in ACE Books."""
    return ex(conn, f"""
        UPDATE replenishment_requests r
           SET status='received', bill_id=m.bill_id, received_qty=m.quantity, received_at=now(), updated_at=now(),
               notes=COALESCE(r.notes || '; ', '') || 'Received on supplier bill ' || m.bill_number
          FROM (SELECT DISTINCT ON (r2.id) r2.id, b.id AS bill_id, b.bill_number, l.quantity
                  FROM replenishment_requests r2
                  LEFT JOIN fin_products fr ON fr.sku=r2.sku
                  JOIN fin_supplier_bill_lines l ON l.quantity > 0
                  LEFT JOIN fin_products fl ON fl.sku=l.sku
                  JOIN fin_supplier_bills b ON b.id=l.bill_id
                 WHERE r2.status='ordered' AND {_BILL_LIVE} AND NOT b.is_opening
                   AND b.bill_date >= COALESCE(r2.ordered_at, r2.created_at)::date - 7
                   AND (r2.supplier_id IS NULL OR b.supplier_id=r2.supplier_id)
                   AND {FAMILY_SQL.format(name="fl.name", sku="l.sku")} = {FAMILY_SQL.format(name="fr.name", sku="r2.sku")}
                   AND NOT EXISTS (SELECT 1 FROM replenishment_requests r3 WHERE r3.bill_id=b.id AND r3.sku=r2.sku)
                 ORDER BY r2.id, b.bill_date) m
         WHERE r.id=m.id""")


def list_orders(status: Optional[str] = None, limit: int = 300) -> List[Dict[str, Any]]:
    from src.services.people import names_for
    with tx() as conn:
        sync_received(conn)
        rows = q(conn, """SELECT r.id::text AS id, r.sku, COALESCE(fp.name, r.sku) AS name, r.requested_qty, r.status, r.created_by,
                                 r.approved_by, r.po_id AS po_reference, r.notes, r.created_at, r.updated_at, r.approved_at, r.ordered_at,
                                 r.expected_date, r.received_at, r.received_qty, r.unit_cost, r.requested_qty * r.unit_cost AS est_value,
                                 r.supplier_id::text AS supplier_id, s.name AS supplier_name, r.bill_id::text AS bill_id, b.bill_number
                          FROM replenishment_requests r
                          LEFT JOIN fin_products fp ON fp.sku=r.sku
                          LEFT JOIN suppliers s ON s.id=r.supplier_id
                          LEFT JOIN fin_supplier_bills b ON b.id=r.bill_id
                          WHERE (%s::text IS NULL AND r.status <> 'cancelled' OR r.status=%s)
                          ORDER BY CASE r.status WHEN 'recommended' THEN 0 WHEN 'approved' THEN 1 WHEN 'ordered' THEN 2 ELSE 3 END,
                                   r.updated_at DESC
                          LIMIT %s""", (status, status, limit))
    names = names_for([r["created_by"] for r in rows] + [r["approved_by"] for r in rows])
    today = dt.date.today()
    for r in rows:
        r["created_by_name"] = names.get(str(r["created_by"])) if r["created_by"] else None
        r["approved_by_name"] = names.get(str(r["approved_by"])) if r["approved_by"] else None
        r["overdue"] = bool(r["status"] == "ordered" and r["expected_date"] and r["expected_date"] < today)
    return rows


def raise_order(sku: str, qty: float, actor: Optional[str], supplier_id: Optional[str] = None,
                unit_cost: Optional[float] = None, notes: Optional[str] = None) -> Dict[str, Any]:
    if qty <= 0:
        raise ValueError("Quantity must be more than zero")
    with tx() as conn:
        if not q1(conn, "SELECT 1 FROM fin_products WHERE sku=%s", (sku,)):
            raise ValueError(f"{sku} is not an item in ACE Books")
        dup = q1(conn, f"""SELECT r.id::text AS id, r.status FROM replenishment_requests r LEFT JOIN fin_products fr ON fr.sku=r.sku
                            WHERE r.status IN ('recommended','approved','ordered')
                              AND {FAMILY_SQL.format(name="fr.name", sku="r.sku")} =
                                  (SELECT {FAMILY_SQL.format(name="fp.name", sku="fp.sku")} FROM fin_products fp WHERE fp.sku=%s LIMIT 1)
                            LIMIT 1""", (sku,))
        if dup:
            raise ValueError(f"{sku} already has an open stock order ({dup['status']})")
        return q1(conn, """INSERT INTO replenishment_requests (sku, requested_qty, status, created_by, supplier_id, unit_cost, notes)
                           VALUES (%s, %s, 'recommended', %s, %s::uuid, %s, %s) RETURNING id::text AS id, sku, requested_qty, status""",
                  (sku, qty, actor, supplier_id or None, unit_cost, notes))


def update_order(order_id: str, action: str, actor: Optional[str], **f: Any) -> Dict[str, Any]:
    """approve | order | cancel. Receiving happens through the supplier bill."""
    with tx() as conn:
        r = q1(conn, "SELECT id, status, sku FROM replenishment_requests WHERE id=%s::uuid FOR UPDATE", (order_id,))
        if not r:
            raise LookupError("Stock order not found")
        st = r["status"]
        if action == "approve":
            if st != "recommended":
                raise ValueError(f"Only a requested order can be approved (this one is {st})")
            ex(conn, """UPDATE replenishment_requests SET status='approved', approved_by=%s, approved_at=now(), updated_at=now(),
                               requested_qty=COALESCE(%s, requested_qty) WHERE id=%s::uuid""", (actor, f.get("qty"), order_id))
        elif action == "order":
            if st not in ("recommended", "approved"):
                raise ValueError(f"This order is already {st}")
            if not f.get("supplier_id"):
                raise ValueError("Choose the supplier the order was placed with")
            ex(conn, """UPDATE replenishment_requests SET status='ordered', ordered_at=now(), updated_at=now(),
                               approved_by=COALESCE(approved_by, %s), approved_at=COALESCE(approved_at, now()),
                               supplier_id=%s::uuid, po_id=%s, expected_date=%s, unit_cost=COALESCE(%s, unit_cost),
                               requested_qty=COALESCE(%s, requested_qty) WHERE id=%s::uuid""",
               (actor, f.get("supplier_id"), f.get("po_reference"), f.get("expected_date"), f.get("unit_cost"), f.get("qty"), order_id))
        elif action == "cancel":
            if st in ("received", "cancelled"):
                raise ValueError(f"This order is already {st}")
            ex(conn, """UPDATE replenishment_requests SET status='cancelled', updated_at=now(),
                               notes=COALESCE(notes || '; ', '') || %s WHERE id=%s::uuid""",
               (f"Cancelled{': ' + f['reason'] if f.get('reason') else ''}", order_id))
        else:
            raise ValueError(f"Unknown action {action}")
    return {"ok": True, "id": order_id, "action": action}


# ---------------------------------------------------------------------------
# Payables (ACE Books) and the summary strip
# ---------------------------------------------------------------------------

def _payables() -> Dict[str, Dict[str, float]]:
    from src.fin.readmodel import ap_rows
    today = dt.date.today()
    out: Dict[str, Dict[str, float]] = defaultdict(lambda: {"balance": 0.0, "overdue": 0.0})
    for r in ap_rows():
        o = out[r["supplier_id"]]
        o["balance"] += r["balance"]
        # netted with unapplied payments / debit notes (as receivables are), never above what is owed
        if r["due_date"] and r["due_date"] < today:
            o["overdue"] += r["balance"]
    for o in out.values():
        o["overdue"] = max(0.0, min(o["overdue"], o["balance"]))
    return out


def summary() -> Dict[str, Any]:
    plan = reorder_plan()
    orders = list_orders(limit=1000)
    ap = _payables()
    with tx() as conn:
        pu = q1(conn, f"""WITH x AS ({_PURCHASE_LINES}) SELECT MAX(bill_date) AS as_of,
                              SUM(amount) FILTER (WHERE bill_date > (SELECT MAX(bill_date) FROM x) - 365) AS last12
                          FROM x""")
    by = defaultdict(list)
    for o in orders:
        by[o["status"]].append(o)
    return {
        "as_of": plan["as_of"], "policy": plan["policy"],
        "reorder_now": plan["counts"].get("reorder_now", 0), "out_of_stock": plan["counts"].get("out_of_stock", 0),
        "reorder_soon": plan["counts"].get("reorder_soon", 0), "to_order_count": plan["to_order_count"],
        "to_order_value": plan["to_order_value"], "expiry_risk_count": plan["expiry_risk_count"],
        "expiry_risk_value": plan["expiry_risk_value"],
        "requested": len(by["recommended"]), "approved": len(by["approved"]), "ordered": len(by["ordered"]),
        "ordered_value": round(sum(_f(o["est_value"]) for o in by["ordered"]), 2),
        "overdue_orders": sum(1 for o in by["ordered"] if o["overdue"]),
        "received_30d": sum(1 for o in by["received"] if o["received_at"] and
                            o["received_at"].date() >= dt.date.today() - dt.timedelta(days=30)),
        # what we owe (suppliers in credit are shown separately, not netted into it)
        "open_payables": round(sum(max(v["balance"], 0.0) for v in ap.values()), 2),
        "supplier_credits": round(-sum(min(v["balance"], 0.0) for v in ap.values()), 2),
        "overdue_payables": round(sum(v["overdue"] for v in ap.values()), 2),
        "purchases_12m": _f(pu["last12"]), "purchases_as_of": pu["as_of"],
    }


# ---------------------------------------------------------------------------
# Supplier invoices (purchases)
# ---------------------------------------------------------------------------

def purchases(search: str = "", supplier_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    params = {"s": f"%{search}%", "sup": supplier_id, "limit": limit, "offset": offset}
    with tx() as conn:
        base = f"""
            SELECT 'ACE Books' AS source, b.id::text AS doc_id, b.bill_number AS number, b.supplier_invoice_number AS supplier_ref,
                   b.bill_date, b.due_date, b.supplier_id::text AS supplier_id, s.name AS supplier_name, b.total AS amount,
                   b.total - b.amount_settled AS balance, b.status, b.is_opening,
                   CASE WHEN b.is_opening THEN (SELECT COUNT(*) FROM fin_sage_purchase_lines p WHERE p.bill_number=b.supplier_invoice_number
                                                   AND p.supplier_id IS NOT DISTINCT FROM b.supplier_id)
                        ELSE (SELECT COUNT(*) FROM fin_supplier_bill_lines l WHERE l.bill_id=b.id) END AS lines,
                   CASE WHEN b.is_opening THEN (SELECT SUM(quantity) FROM fin_sage_purchase_lines p WHERE p.bill_number=b.supplier_invoice_number
                                                   AND p.supplier_id IS NOT DISTINCT FROM b.supplier_id)
                        ELSE (SELECT SUM(quantity) FROM fin_supplier_bill_lines l WHERE l.bill_id=b.id AND l.sku IS NOT NULL) END AS qty
            FROM fin_supplier_bills b LEFT JOIN suppliers s ON s.id=b.supplier_id WHERE {_BILL_LIVE}
            UNION ALL
            SELECT 'Sage', NULL, p.bill_number, p.bill_number, MIN(p.bill_date), NULL, p.supplier_id::text,
                   COALESCE(s.name, MAX(p.supplier_name)), SUM(p.amount), 0, 'SETTLED', false, COUNT(*), SUM(p.quantity)
            FROM fin_sage_purchase_lines p LEFT JOIN suppliers s ON s.id=p.supplier_id
            WHERE NOT EXISTS (SELECT 1 FROM fin_supplier_bills b WHERE b.is_opening AND b.supplier_invoice_number=p.bill_number
                                AND b.supplier_id IS NOT DISTINCT FROM p.supplier_id)
            GROUP BY p.bill_number, p.supplier_id, s.name"""
        where = """WHERE (number ILIKE %(s)s OR supplier_ref ILIKE %(s)s OR supplier_name ILIKE %(s)s)
                     AND (%(sup)s::text IS NULL OR supplier_id=%(sup)s)"""
        total = q1(conn, f"SELECT COUNT(*) AS n, SUM(amount) AS amount FROM ({base}) x {where}", params)
        rows = q(conn, f"SELECT * FROM ({base}) x {where} ORDER BY bill_date DESC, number LIMIT %(limit)s OFFSET %(offset)s", params)
    return {"rows": rows, "total": total["n"], "amount": total["amount"]}


# ---------------------------------------------------------------------------
# Supplier directory
# ---------------------------------------------------------------------------

def supplier_directory() -> Dict[str, Any]:
    ap = _payables()
    with tx() as conn:
        rows = q(conn, f"""
            WITH lines AS ({_PURCHASE_LINES}),
            docs AS (SELECT supplier_id, doc_number, MIN(bill_date) AS d, SUM(amount) AS amt FROM lines
                     WHERE supplier_id IS NOT NULL GROUP BY supplier_id, doc_number),
            asof AS (SELECT MAX(d) AS d FROM docs),
            agg AS (SELECT supplier_id, COUNT(*) AS invoices, SUM(amt) AS lifetime,
                           SUM(amt) FILTER (WHERE docs.d > asof.d - 365) AS last12, MAX(docs.d) AS last_purchase, MIN(docs.d) AS first_purchase
                    FROM docs, asof GROUP BY supplier_id),
            gaps AS (SELECT supplier_id, AVG(gap) AS avg_gap FROM (
                        SELECT supplier_id, d - LAG(d) OVER (PARTITION BY supplier_id ORDER BY d) AS gap
                        FROM (SELECT DISTINCT supplier_id, d FROM docs) z) y WHERE gap IS NOT NULL GROUP BY supplier_id),
            items AS (SELECT supplier_id, COUNT(DISTINCT sku) AS items FROM lines WHERE sku IS NOT NULL GROUP BY supplier_id),
            pc AS (SELECT supplier_id, sku,
                          AVG(amount / quantity) FILTER (WHERE bill_date > asof.d - 182) AS recent,
                          AVG(amount / quantity) FILTER (WHERE bill_date <= asof.d - 182 AND bill_date > asof.d - 547) AS prior,
                          SUM(amount) FILTER (WHERE bill_date > asof.d - 182) AS w
                   FROM lines, asof WHERE sku IS NOT NULL AND quantity > 0 AND supplier_id IS NOT NULL GROUP BY supplier_id, sku),
            price AS (SELECT supplier_id, SUM((recent / prior - 1) * w) / NULLIF(SUM(w), 0) * 100 AS price_change_pct
                      FROM pc WHERE recent IS NOT NULL AND prior > 0 GROUP BY supplier_id)
            SELECT s.id::text AS id, s.name, s.external_vendor_id AS code, s.contact_name, s.phone, s.contact_email, s.address,
                   s.payment_terms, COALESCE(s.status, 'active') AS status, s.tax_id,
                   COALESCE(agg.invoices, 0) AS invoices, COALESCE(agg.lifetime, 0) AS lifetime, COALESCE(agg.last12, 0) AS last12,
                   agg.last_purchase, agg.first_purchase, round(gaps.avg_gap::numeric, 1) AS avg_gap_days,
                   COALESCE(items.items, 0) AS items, round(price.price_change_pct::numeric, 1) AS price_change_pct,
                   (SELECT d FROM asof) AS as_of
            FROM suppliers s LEFT JOIN agg ON agg.supplier_id=s.id LEFT JOIN gaps ON gaps.supplier_id=s.id
            LEFT JOIN items ON items.supplier_id=s.id LEFT JOIN price ON price.supplier_id=s.id
            ORDER BY COALESCE(agg.last12, 0) DESC, COALESCE(agg.lifetime, 0) DESC, s.name""")
    as_of = rows[0]["as_of"] if rows else None
    for r in rows:
        a = ap.get(r["id"], {"balance": 0.0, "overdue": 0.0})
        r["balance"] = round(a["balance"], 2)
        r["overdue"] = round(a["overdue"], 2)
        r.pop("as_of", None)
        r["active"] = bool(r["last_purchase"] and as_of and (as_of - r["last_purchase"]).days <= 365)
    return {
        "as_of": as_of, "suppliers": rows,
        "totals": {
            "suppliers": len(rows), "active": sum(1 for r in rows if r["active"]),
            "balance": round(sum(max(r["balance"], 0.0) for r in rows), 2), "overdue": round(sum(r["overdue"] for r in rows), 2),
            "credits": round(-sum(min(r["balance"], 0.0) for r in rows), 2),
            "last12": round(sum(_f(r["last12"]) for r in rows), 2),
            "with_balance": sum(1 for r in rows if r["balance"] > 0),
        },
    }
