"""Inventory & Quality, connected: QC, Compliance/QMS, ACE Books stock and the calendar.

One record per fact, and every module acts on it through here:

  Recall      recall_cases (the QMS case: reason, scope, authority, documents)
              + fin_recalls (ACE Books: batch frozen so it cannot be sold, every
              customer who bought it traced, returns tracked). Opened together,
              closed together. QC, Compliance and the calendar all call
              initiate_recall(); nothing opens one without the other.
  Batch       nafdac_batch_registry (QC release decision) linked to fin_batches.
  release     Pending = QUARANTINED in ACE Books (cannot be sold); released =
              AVAILABLE; rejected = stays QUARANTINED and a deviation is raised.
  Deviation   deviation_reports with a target close date and CAPA due dates. A
              maintenance or audit deviation can reschedule the linked job.
  Audit       audit_schedule with a real date; completing a recurring audit
              schedules the next one.
  Maintenance maintenance_schedule (next date per equipment job).
  Expiry      read from ACE Books lots (FIFO layers by batch), grouped by product.

The calendar (calendar_feed) is a view over these tables plus stock orders and
manual events - moving an item on the calendar moves the record itself
(reschedule), and creating from the calendar creates the record.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.fin.db import ex, q, q1, tx
from src.services.stock_orders import FAMILY_SQL

OPEN_RECALL = ("initiated", "in_progress")
OPEN_DEVIATION = ("open", "under_investigation", "escalated")
FREQ_MONTHS = {"monthly": 1, "quarterly": 3, "biannual": 6, "annual": 12}


class QualityError(ValueError):
    """A request that cannot be carried out as asked (mapped to 409/400 by the router)."""


def _today() -> dt.date:
    return dt.date.today()


def _d(v: Any) -> Optional[dt.date]:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def _f(v: Any) -> float:
    return float(v or 0)


def _ctx(conn, user: Dict[str, Any]):
    """ACE Books context for the signed-in user (their own ACE Books permissions apply)."""
    from src.fin.context import FinContext, permissions_for, resolve_entity
    roles = [str(r).lower() for r in (user.get("roles") or [])]
    actor = str(user.get("sub") or "unknown")
    return FinContext(actor, str(user.get("name") or user.get("email") or actor), roles,
                      resolve_entity(conn, None), permissions_for(roles), uuid.uuid4().hex[:16])


def _next_id(conn, prefix: str, table: str, col: str) -> str:
    year = _today().year
    r = q1(conn, f"SELECT MAX(split_part({col}, '-', 3)::int) AS n FROM {table} WHERE {col} LIKE %s", (f"{prefix}-{year}-%",))
    return f"{prefix}-{year}-{(r['n'] or 0) + 1:03d}"


def _add_months(d: dt.date, months: int) -> dt.date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(d.day, last))


def _audit_log(conn, user: Dict[str, Any], action: str, subject_type: str, subject_id: str, details: Dict[str, Any]) -> None:
    ex(conn, """INSERT INTO placeware_audit_logs (event_type, event_class, action, outcome, actor_id, subject_type, subject_id, details)
                VALUES (%s, 'quality', %s, 'success', %s, %s, %s, %s::jsonb)""",
       (f"quality_{action}", action, str(user.get("sub") or "system"), subject_type, str(subject_id), json.dumps(details, default=str)))


# ---------------------------------------------------------------------------
# Expiry, per product (ACE Books lots)
# ---------------------------------------------------------------------------

def _bucket(days: Optional[int]) -> str:
    if days is None:
        return "no_expiry"
    if days < 0:
        return "expired"
    if days <= 30:
        return "critical"
    if days <= 90:
        return "soon"
    if days <= 180:
        return "watch"
    return "ok"


_BUCKET_RANK = {"expired": 0, "critical": 1, "soon": 2, "watch": 3, "ok": 4, "no_expiry": 5}


def lots_in_stock(conn) -> List[Dict[str, Any]]:
    return q(conn, f"""
        WITH lots AS (SELECT sku, batch_id, SUM(qty_remaining) AS qty, SUM(qty_remaining * unit_cost) AS value
                      FROM fin_cost_layers GROUP BY sku, batch_id HAVING SUM(qty_remaining) > 0)
        SELECT l.sku, l.batch_id::text AS batch_id, l.qty, l.value, b.batch_number, b.expiry_date, b.status AS batch_status,
               {FAMILY_SQL.format(name="fp.name", sku="l.sku")} AS family
        FROM lots l LEFT JOIN fin_batches b ON b.id=l.batch_id LEFT JOIN fin_products fp ON fp.sku=l.sku""")


def expiry_by_product(window_days: int = 180) -> Dict[str, Any]:
    today = _today()
    with tx() as conn:
        lots = lots_in_stock(conn)
        recalled = {r["batch_id"]: r for r in q(conn, """SELECT batch_id::text AS batch_id, recall_number, id::text AS fin_recall_id
                                                          FROM fin_recalls WHERE status='OPEN'""")}
    # units that will not sell before their lot expires, at the current rate of sale (reorder plan)
    try:
        from src.services.stock_orders import reorder_plan
        risk = {i["family"]: i for i in reorder_plan()["items"]}
    except Exception:
        risk = {}
    products: Dict[str, Dict[str, Any]] = {}
    for l in lots:
        days = (l["expiry_date"] - today).days if l["expiry_date"] else None
        b = _bucket(days)
        p = products.setdefault(l["family"], {"product": l["family"], "lots": [], "units": 0.0, "value": 0.0,
                                               "expiring_units": 0.0, "expiring_value": 0.0})
        p["lots"].append({"sku": l["sku"], "batch_id": l["batch_id"], "batch_number": l["batch_number"], "expiry_date": l["expiry_date"],
                          "days_left": days, "bucket": b, "qty": _f(l["qty"]), "value": round(_f(l["value"]), 2),
                          "batch_status": l["batch_status"], "recall": recalled.get(l["batch_id"])})
        p["units"] += _f(l["qty"])
        p["value"] += _f(l["value"])
        if days is not None and days <= window_days:
            p["expiring_units"] += _f(l["qty"])
            p["expiring_value"] += _f(l["value"])
    out = []
    for fam, p in products.items():
        p["lots"].sort(key=lambda x: (x["expiry_date"] or dt.date.max, x["sku"]))
        worst = min(p["lots"], key=lambda x: _BUCKET_RANK[x["bucket"]])
        p["bucket"] = worst["bucket"]
        p["next_expiry"] = worst["expiry_date"]
        p["days_left"] = worst["days_left"]
        r = risk.get(fam) or {}
        p["monthly_demand"] = r.get("monthly_demand")
        p["unsellable_units"] = r.get("expiry_risk_units") or 0
        p["unsellable_value"] = r.get("expiry_risk_value") or 0
        p["value"] = round(p["value"], 2)
        p["expiring_value"] = round(p["expiring_value"], 2)
        if p["expiring_units"] > 0:
            out.append(p)
    out.sort(key=lambda p: (_BUCKET_RANK[p["bucket"]], p["days_left"] if p["days_left"] is not None else 99999))
    summary: Dict[str, Dict[str, float]] = {}
    for p in out:
        s = summary.setdefault(p["bucket"], {"products": 0, "units": 0.0, "value": 0.0})
        s["products"] += 1
        s["units"] += sum(l["qty"] for l in p["lots"] if l["bucket"] == p["bucket"])
        s["value"] += sum(l["value"] for l in p["lots"] if l["bucket"] == p["bucket"])
    return {"window_days": window_days, "products": out, "summary": summary,
            "unsellable_value": round(sum(_f(p["unsellable_value"]) for p in out), 2)}


def quarantine_lot(user: Dict[str, Any], batch_id: str, reason: str) -> Dict[str, Any]:
    from src.fin import inventory
    with tx() as conn:
        return inventory.set_batch_status(conn, _ctx(conn, user), batch_id, "QUARANTINED", reason or "Quarantined by QC")


def release_lot(user: Dict[str, Any], batch_id: str, reason: str) -> Dict[str, Any]:
    from src.fin import inventory
    with tx() as conn:
        b = q1(conn, "SELECT status FROM fin_batches WHERE id=%s", (batch_id,))
        if b and b["status"] == "RECALLED":
            raise QualityError("This batch is under an open recall; close the recall to release it")
        return inventory.set_batch_status(conn, _ctx(conn, user), batch_id, "AVAILABLE", reason or "Released by QC")


def write_off_lot(user: Dict[str, Any], batch_id: str, reason: str = "EXPIRY", notes: Optional[str] = None) -> Dict[str, Any]:
    """Draft an ACE Books adjustment removing everything left in the lot. A second person approves it."""
    from src.fin import inventory
    with tx() as conn:
        lot = q1(conn, """SELECT l.sku, SUM(l.qty_remaining) AS qty, b.batch_number FROM fin_cost_layers l
                          JOIN fin_batches b ON b.id=l.batch_id WHERE l.batch_id=%s GROUP BY l.sku, b.batch_number""", (batch_id,))
        if not lot or _f(lot["qty"]) <= 0:
            raise QualityError("Nothing left in this lot to write off")
        ctx = _ctx(conn, user)
        return inventory.create_adjustment(conn, ctx, {
            "adjustment_date": _today(), "reason_code": reason,
            "notes": notes or f"Write-off of lot {lot['batch_number']} from Quality Control",
            "lines": [{"sku": lot["sku"], "batch_id": batch_id, "quantity": -_f(lot["qty"])}]})


# ---------------------------------------------------------------------------
# Recalls: the QMS case and the ACE Books recall, always together
# ---------------------------------------------------------------------------

def _resolve_batch(conn, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if data.get("batch_id"):
        return q1(conn, "SELECT b.*, b.id::text AS bid FROM fin_batches b WHERE b.id=%s", (data["batch_id"],))
    bn = (data.get("batch_number") or "").strip()
    if not bn:
        return None
    if data.get("sku"):
        return q1(conn, "SELECT b.*, b.id::text AS bid FROM fin_batches b WHERE b.sku=%s AND b.batch_number=%s", (data["sku"], bn))
    if data.get("product_name"):
        return q1(conn, f"""SELECT b.*, b.id::text AS bid FROM fin_batches b LEFT JOIN fin_products fp ON fp.sku=b.sku
                            WHERE b.batch_number=%s AND lower({FAMILY_SQL.format(name="fp.name", sku="b.sku")}) = lower(%s)
                            LIMIT 1""", (bn, data["product_name"].strip()))
    return None


def initiate_recall(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Open a recall. When the batch is in ACE Books (it always is for stock we hold or sold since
    go-live) the ACE Books recall is opened in the same transaction: the batch is frozen and every
    customer who bought it is listed for contact."""
    from src.fin import inventory
    if len((data.get("recall_reason") or data.get("reason") or "").strip()) < 5:
        raise QualityError("Give the reason for the recall")
    reason = (data.get("recall_reason") or data.get("reason")).strip()
    with tx() as conn:
        b = _resolve_batch(conn, data)
        if not b and not data.get("allow_unlinked"):
            raise QualityError("Choose the batch from ACE Books stock so it can be frozen and its buyers traced")
        fin = None
        product = data.get("product_name")
        if b:
            open_one = q1(conn, "SELECT recall_number FROM fin_recalls WHERE batch_id=%s AND status='OPEN'", (b["bid"],))
            if open_one:
                raise QualityError(f"Batch {b['batch_number']} already has an open recall ({open_one['recall_number']})")
            fin = inventory.open_recall(conn, _ctx(conn, user), {"batch_id": b["bid"], "reason": reason, "notes": data.get("notes")})
            fam = q1(conn, f"SELECT {FAMILY_SQL.format(name='fp.name', sku='fp.sku')} AS f FROM fin_products fp WHERE fp.sku=%s LIMIT 1",
                     (b["sku"],))
            product = (fam or {}).get("f") or b["sku"]
        dist = [{"customer_id": i["customer_id"], "name": i.get("customer_name"), "qty": _f(i["quantity_sold"]),
                 "invoices": i.get("invoice_number")} for i in (fin or {}).get("items", [])]
        rid = _next_id(conn, "RECALL", "recall_cases", "recall_id")
        row = q1(conn, """INSERT INTO recall_cases (recall_id, batch_number, product_name, sku, recall_reason, initiation_date, scope, status,
                                                    regulatory_authority, distribution_data, created_by, severity, nafdac_notified,
                                                    fin_recall_id, expected_return_date)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,'initiated',%s,%s::jsonb,%s,%s,%s,%s,%s) RETURNING id::text AS id, recall_id""",
                  (rid, b["batch_number"] if b else data.get("batch_number"), product, b["sku"] if b else data.get("sku"), reason, _today(),
                   data.get("scope") or "voluntary", data.get("regulatory_authority") or "NAFDAC", json.dumps(dist, default=str),
                   str(user.get("sub") or ""), data.get("severity") or "major", bool(data.get("nafdac_notified")),
                   (fin or {}).get("id"), _d(data.get("expected_return_date")) or _today() + dt.timedelta(days=14)))
        _audit_log(conn, user, "recall_initiated", "recall_case", row["id"],
                   {"recall_id": rid, "fin_recall": (fin or {}).get("recall_number"), "batch": row and (b or {}).get("batch_number")})
        # A customer bringing the batch back (e.g. "we wanted three, they brought five"): record the
        # return against their invoice now - credit note, customer's balance, stock - in the same step.
        if fin and data.get("customer_id") and data.get("return_quantity"):
            item = next((i for i in fin.get("items", []) if str(i["customer_id"]) == str(data["customer_id"])), None)
            inventory.record_recall_return(conn, _ctx(conn, user), fin["id"], {
                "item_id": item["id"] if item else None, "customer_id": data["customer_id"],
                "invoice_id": data.get("invoice_id"), "sage_invoice_number": data.get("sage_invoice_number"),
                "quantity": data["return_quantity"], "unit_price": data.get("unit_price"), "unit_cost": data.get("unit_cost"),
                "credit": data.get("credit", True)})
    return get_recall(row["id"])


def record_return(user: Dict[str, Any], recall_case_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """A customer returns recalled stock: credit note on their invoice + stock back (frozen)."""
    from src.fin import inventory
    with tx() as conn:
        r = q1(conn, "SELECT fin_recall_id::text AS f, status FROM recall_cases WHERE id=%s", (recall_case_id,))
        if not r or not r["f"]:
            raise QualityError("This recall is not linked to an ACE Books batch")
        inventory.record_recall_return(conn, _ctx(conn, user), r["f"], data)
        if r["status"] == "initiated":
            ex(conn, "UPDATE recall_cases SET status='in_progress', updated_at=now() WHERE id=%s", (recall_case_id,))
        _audit_log(conn, user, "recall_return", "recall_case", recall_case_id, {k: str(v) for k, v in data.items()})
    return get_recall(recall_case_id)


def customer_invoices_for_batch(customer_id: int, batch_id: Optional[str] = None, sku: Optional[str] = None) -> List[Dict[str, Any]]:
    """The customer's invoices that carried this product (ACE Books and Sage), for linking a return."""
    from src.fin import sales
    from src.fin.context import resolve_entity
    with tx() as conn:
        if batch_id and not sku:
            b = q1(conn, "SELECT sku FROM fin_batches WHERE id=%s", (batch_id,))
            sku = b["sku"] if b else None
        return sales.returnable_invoices(conn, resolve_entity(conn, None), int(customer_id), sku=sku)


def list_recalls(status: Optional[str] = None) -> List[Dict[str, Any]]:
    from src.services.people import names_for
    with tx() as conn:
        rows = q(conn, """SELECT r.id::text AS id, r.recall_id, r.batch_number, r.product_name, r.sku, r.recall_reason, r.initiation_date,
                                 r.scope, r.severity, r.status, r.regulatory_authority, r.nafdac_notified, r.expected_return_date,
                                 r.resolved_at, r.created_by, CASE WHEN jsonb_typeof(r.distribution_data)='array' THEN jsonb_array_length(r.distribution_data) ELSE 0 END AS customers_listed,
                                 r.fin_recall_id::text AS fin_recall_id, f.recall_number AS fin_recall_number, f.status AS fin_status,
                                 f.batch_id::text AS batch_id,
                                 (SELECT COUNT(*) FROM fin_recall_items i WHERE i.recall_id=f.id) AS customers,
                                 (SELECT COUNT(*) FROM fin_recall_items i WHERE i.recall_id=f.id AND i.contact_status <> 'PENDING') AS contacted,
                                 (SELECT COALESCE(SUM(quantity_sold),0) FROM fin_recall_items i WHERE i.recall_id=f.id) AS units_out,
                                 (SELECT COALESCE(SUM(quantity_returned),0) FROM fin_recall_items i WHERE i.recall_id=f.id) AS units_returned,
                                 (SELECT COALESCE(SUM(qty_remaining),0) FROM fin_cost_layers l WHERE l.batch_id=f.batch_id) AS units_frozen
                          FROM recall_cases r LEFT JOIN fin_recalls f ON f.id=r.fin_recall_id
                          WHERE (%s::text IS NULL OR r.status=%s)
                          ORDER BY (r.status IN ('initiated','in_progress')) DESC, r.initiation_date DESC""", (status, status))
    names = names_for([r["created_by"] for r in rows])
    today = _today()
    for r in rows:
        r["created_by_name"] = names.get(str(r["created_by"])) if r["created_by"] else None
        r["overdue"] = bool(r["status"] in OPEN_RECALL and r["expected_return_date"] and r["expected_return_date"] < today)
    return rows


def get_recall(recall_case_id: str) -> Dict[str, Any]:
    from src.fin import inventory
    rows = [r for r in list_recalls() if r["id"] == recall_case_id]
    if not rows:
        raise LookupError("Recall not found")
    r = rows[0]
    if r["fin_recall_id"]:
        with tx() as conn:
            from src.fin.context import resolve_entity
            r["books"] = inventory.get_recall(conn, resolve_entity(conn, None), r["fin_recall_id"])
    return r


def update_recall(user: Dict[str, Any], recall_case_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Status / expected return date. Completing or closing the case closes the ACE Books recall;
    the batch stays RECALLED (write off or return the stock, or release it, as a separate decision)."""
    from src.fin import inventory
    with tx() as conn:
        r = q1(conn, "SELECT id, status, fin_recall_id::text AS fin_recall_id FROM recall_cases WHERE id=%s FOR UPDATE", (recall_case_id,))
        if not r:
            raise LookupError("Recall not found")
        if r["status"] == "closed":
            raise QualityError("This recall is already closed")
        st = data.get("status")
        if st and st not in ("initiated", "in_progress", "completed", "closed"):
            raise QualityError("Unknown recall status")
        sets, params = ["updated_at=now()"], []
        if st:
            sets.append("status=%s"); params.append(st)
            if st in ("completed", "closed"):
                sets.append("resolved_at=now()")
        if data.get("expected_return_date"):
            sets.append("expected_return_date=%s"); params.append(_d(data["expected_return_date"]))
        ex(conn, f"UPDATE recall_cases SET {', '.join(sets)} WHERE id=%s", params + [recall_case_id])
        if st in ("completed", "closed") and r["fin_recall_id"]:
            f = q1(conn, "SELECT status FROM fin_recalls WHERE id=%s", (r["fin_recall_id"],))
            if f and f["status"] == "OPEN":
                inventory.close_recall(conn, _ctx(conn, user), r["fin_recall_id"], data.get("notes") or f"Recall case {st}")
        _audit_log(conn, user, "recall_updated", "recall_case", recall_case_id, {k: v for k, v in data.items() if v is not None})
    return get_recall(recall_case_id)


# ---------------------------------------------------------------------------
# Batch release (QC) bound to ACE Books batches
# ---------------------------------------------------------------------------

def sync_batches(conn) -> None:
    """Link registered batches to the ACE Books batch once it exists (the supplier bill created it),
    and hold pending ones in quarantine so they cannot be sold before QC releases them."""
    pending = q(conn, """SELECT r.id::text AS id, b.id::text AS bid, b.status FROM nafdac_batch_registry r
                         JOIN fin_batches b ON b.sku=r.sku AND b.batch_number=r.batch_number
                         WHERE r.fin_batch_id IS NULL AND r.sku IS NOT NULL""")
    for p in pending:
        ex(conn, "UPDATE nafdac_batch_registry SET fin_batch_id=%s, updated_at=now() WHERE id=%s", (p["bid"], p["id"]))
    ex(conn, """UPDATE fin_batches b SET status='QUARANTINED'
                FROM nafdac_batch_registry r
                WHERE r.fin_batch_id=b.id AND r.status IN ('pending','rejected','suspended') AND b.status='AVAILABLE'""")


def list_batches() -> Dict[str, Any]:
    from src.services.people import names_for
    today = _today()
    with tx() as conn:
        sync_batches(conn)
        rows = q(conn, """SELECT r.id::text AS id, r.batch_number, r.product_name, r.sku, r.status, r.supplier, r.nafdac_reg_number,
                                 r.certificate_ref, r.valid_from, r.valid_to, r.expected_arrival_date, r.quantity, r.expiry_date,
                                 r.stock_order_id::text AS stock_order_id, r.registered_by, r.approved_by, r.approved_at, r.rejection_reason,
                                 r.notes, r.created_at, r.fin_batch_id::text AS fin_batch_id, b.status AS batch_status,
                                 (SELECT COALESCE(SUM(qty_remaining),0) FROM fin_cost_layers l WHERE l.batch_id=b.id) AS on_hand
                          FROM nafdac_batch_registry r LEFT JOIN fin_batches b ON b.id=r.fin_batch_id
                          ORDER BY (r.status='pending') DESC, COALESCE(r.expected_arrival_date, r.created_at::date) DESC""")
        cut = q1(conn, "SELECT cutover_date FROM fin_settings LIMIT 1")
        unreleased = q(conn, f"""SELECT b.id::text AS batch_id, b.sku, b.batch_number, b.expiry_date, b.status, b.created_at,
                                        {FAMILY_SQL.format(name="fp.name", sku="b.sku")} AS product,
                                        (SELECT COALESCE(SUM(qty_remaining),0) FROM fin_cost_layers l WHERE l.batch_id=b.id) AS on_hand
                                 FROM fin_batches b LEFT JOIN fin_products fp ON fp.sku=b.sku
                                 WHERE b.created_at::date >= %s
                                   AND NOT EXISTS (SELECT 1 FROM nafdac_batch_registry r WHERE r.fin_batch_id=b.id)
                                   -- stock brought over from Sage at go-live was already released
                                   AND NOT EXISTS (SELECT 1 FROM fin_inventory_transactions t WHERE t.batch_id=b.id AND t.txn_type='OPENING_BALANCE')
                                 ORDER BY b.created_at DESC""", ((cut or {}).get("cutover_date") or today,))
    names = names_for([r["registered_by"] for r in rows] + [r["approved_by"] for r in rows])
    for r in rows:
        r["registered_by_name"] = names.get(str(r["registered_by"])) if r["registered_by"] else None
        r["approved_by_name"] = names.get(str(r["approved_by"])) if r["approved_by"] else None
        r["stage"] = ("rejected" if r["status"] in ("rejected", "suspended") else "released" if r["status"] == "approved"
                      else "awaiting_release" if r["fin_batch_id"] else "expected")
        r["late"] = bool(r["stage"] == "expected" and r["expected_arrival_date"] and r["expected_arrival_date"] < today)
    return {"batches": rows, "received_unreleased": unreleased}


def register_batch(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    sku = (data.get("sku") or "").strip()
    bn = (data.get("batch_number") or "").strip()
    if not sku or not bn:
        raise QualityError("Choose the product and give the batch number")
    with tx() as conn:
        fp = q1(conn, f"SELECT {FAMILY_SQL.format(name='name', sku='sku')} AS family FROM fin_products WHERE sku=%s", (sku,))
        if not fp:
            raise QualityError(f"{sku} is not a product in ACE Books")
        if q1(conn, "SELECT 1 FROM nafdac_batch_registry WHERE sku=%s AND batch_number=%s", (sku, bn)):
            raise QualityError(f"Batch {bn} of {sku} is already registered")
        row = q1(conn, """INSERT INTO nafdac_batch_registry (batch_number, product_name, sku, nafdac_reg_number, supplier, status, dispatch_blocked,
                                                             valid_from, valid_to, certificate_ref, registered_by, notes, expected_arrival_date,
                                                             quantity, expiry_date, stock_order_id)
                          VALUES (%s,%s,%s,%s,%s,'pending',TRUE,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id::text AS id""",
                  (bn, fp["family"], sku, data.get("nafdac_reg_number"), data.get("supplier"), _d(data.get("valid_from")),
                   _d(data.get("valid_to")), data.get("certificate_ref"), str(user.get("sub") or "unknown"), data.get("notes"),
                   _d(data.get("expected_arrival_date")), data.get("quantity"), _d(data.get("expiry_date")), data.get("stock_order_id") or None))
        sync_batches(conn)
        _audit_log(conn, user, "batch_registered", "nafdac_batch", row["id"], {"sku": sku, "batch": bn})
    if data.get("release_now"):
        return release_batch(user, row["id"], data)
    return {"id": row["id"], "status": "pending"}


def release_batch(user: Dict[str, Any], registry_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from src.fin import inventory
    data = data or {}
    with tx() as conn:
        sync_batches(conn)
        r = q1(conn, "SELECT *, fin_batch_id::text AS bid FROM nafdac_batch_registry WHERE id=%s FOR UPDATE", (registry_id,))
        if not r:
            raise LookupError("Batch not found")
        if r["status"] == "approved":
            raise QualityError("This batch is already released")
        ex(conn, """UPDATE nafdac_batch_registry SET status='approved', dispatch_blocked=FALSE, approved_by=%s, approved_at=now(), updated_at=now(),
                           valid_from=COALESCE(%s, valid_from), valid_to=COALESCE(%s, valid_to), certificate_ref=COALESCE(%s, certificate_ref),
                           nafdac_reg_number=COALESCE(%s, nafdac_reg_number), notes=COALESCE(%s, notes) WHERE id=%s""",
           (str(user.get("sub") or ""), _d(data.get("valid_from")), _d(data.get("valid_to")), data.get("certificate_ref"),
            data.get("nafdac_reg_number"), data.get("notes"), registry_id))
        if r["bid"]:
            b = q1(conn, "SELECT status FROM fin_batches WHERE id=%s", (r["bid"],))
            if b and b["status"] == "QUARANTINED":
                inventory.set_batch_status(conn, _ctx(conn, user), r["bid"], "AVAILABLE", "Released by QC")
        _audit_log(conn, user, "batch_released", "nafdac_batch", registry_id, {"batch": r["batch_number"], "sku": r["sku"]})
    return {"id": registry_id, "status": "approved", "in_books": bool(r["bid"])}


def reject_batch(user: Dict[str, Any], registry_id: str, reason: str, notes: Optional[str] = None) -> Dict[str, Any]:
    """Reject: the batch stays quarantined in ACE Books and a deviation is raised automatically."""
    from src.fin import inventory
    if len((reason or "").strip()) < 5:
        raise QualityError("Give the reason for rejecting the batch")
    with tx() as conn:
        sync_batches(conn)
        r = q1(conn, "SELECT *, fin_batch_id::text AS bid FROM nafdac_batch_registry WHERE id=%s FOR UPDATE", (registry_id,))
        if not r:
            raise LookupError("Batch not found")
        if r["status"] == "rejected":
            raise QualityError("This batch is already rejected")
        ex(conn, """UPDATE nafdac_batch_registry SET status='rejected', dispatch_blocked=TRUE, rejection_reason=%s,
                           notes=COALESCE(%s, notes), updated_at=now() WHERE id=%s""", (reason, notes, registry_id))
        if r["bid"]:
            b = q1(conn, "SELECT status FROM fin_batches WHERE id=%s", (r["bid"],))
            if b and b["status"] == "AVAILABLE":
                inventory.set_batch_status(conn, _ctx(conn, user), r["bid"], "QUARANTINED", f"Rejected by QC: {reason}")
        dev = _insert_deviation(conn, user, {
            "classification": "major", "trigger_type": "nafdac_violation", "trigger_ref": registry_id,
            "observation": f"Batch {r['batch_number']} of {r['product_name']} rejected at QC release: {reason}",
            "responsible_department": "Quality Assurance", "target_close_date": _today() + dt.timedelta(days=14)})
        _audit_log(conn, user, "batch_rejected", "nafdac_batch", registry_id, {"reason": reason, "deviation": dev["deviation_id"]})
    return {"id": registry_id, "status": "rejected", "deviation_id": dev["deviation_id"]}


# ---------------------------------------------------------------------------
# Deviations & CAPA
# ---------------------------------------------------------------------------

VALID_TRIGGERS = {"temperature_breach", "audit_failure", "inspection_failed", "missed_maintenance", "missed_activity",
                  "nafdac_violation", "manual"}


def _insert_deviation(conn, user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("classification", "minor") not in ("minor", "major", "critical"):
        raise QualityError("Classification must be minor, major or critical")
    if data.get("trigger_type") not in VALID_TRIGGERS:
        raise QualityError("Unknown deviation trigger")
    if len((data.get("observation") or "").strip()) < 10:
        raise QualityError("Describe what happened (at least 10 characters)")
    did = _next_id(conn, "DEV", "deviation_reports", "deviation_id")
    return q1(conn, """INSERT INTO deviation_reports (deviation_id, classification, trigger_type, trigger_ref, observation, impact_assessment,
                                                      recommendations, responsible_department, responsible_person, status, capa_actions,
                                                      target_close_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s::jsonb,%s) RETURNING id::text AS id, deviation_id""",
              (did, data.get("classification", "minor"), data["trigger_type"], data.get("trigger_ref"), data["observation"].strip(),
               data.get("impact_assessment"), data.get("recommendations"), data.get("responsible_department") or "Quality Assurance",
               data.get("responsible_person"), json.dumps(data.get("capa_actions") or [], default=str),
               _d(data.get("target_close_date")) or _today() + dt.timedelta(days=30)))


def raise_deviation(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Raise a deviation. When it concerns a maintenance job or an audit, the new date given
    (reschedule_date) moves that job, so the calendar shows the corrected schedule."""
    with tx() as conn:
        dev = _insert_deviation(conn, user, data)
        moved = None
        new_date = _d(data.get("reschedule_date"))
        ref = data.get("trigger_ref")
        if new_date and ref and data.get("trigger_type") == "missed_maintenance":
            if ex(conn, "UPDATE maintenance_schedule SET next_maintenance_date=%s, status='scheduled', updated_at=now() WHERE id::text=%s",
                  (new_date, ref)):
                moved = {"kind": "maintenance", "id": ref, "date": new_date}
        elif new_date and ref and data.get("trigger_type") == "audit_failure":
            a = q1(conn, "SELECT audit_type, department, risk_level, assigned_to FROM audit_schedule WHERE id::text=%s", (ref,))
            if a:
                nid = _insert_audit(conn, {**a, "scheduled_date": new_date, "frequency": "ad_hoc",
                                           "notes": f"Follow-up audit for {dev['deviation_id']}"})
                moved = {"kind": "audit", "id": nid, "date": new_date}
        _audit_log(conn, user, "deviation_raised", "deviation_report", dev["id"], {"deviation_id": dev["deviation_id"], "moved": moved})
    return {**dev, "rescheduled": moved}


def update_deviation(user: Dict[str, Any], dev_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    with tx() as conn:
        d = q1(conn, "SELECT status FROM deviation_reports WHERE id=%s FOR UPDATE", (dev_id,))
        if not d:
            raise LookupError("Deviation not found")
        if d["status"] == "closed":
            raise QualityError("This deviation is closed")
        fields = {k: data[k] for k in ("status", "impact_assessment", "recommendations", "responsible_person", "target_close_date",
                                       "classification") if data.get(k) is not None}
        if "status" in fields and fields["status"] not in ("open", "under_investigation", "escalated", "closed"):
            raise QualityError("Unknown deviation status")
        sets = [f"{k}=%s" for k in fields]
        params: List[Any] = [(_d(v) if k == "target_close_date" else v) for k, v in fields.items()]
        if data.get("capa_actions") is not None:
            sets.append("capa_actions=%s::jsonb"); params.append(json.dumps(data["capa_actions"], default=str))
        if fields.get("status") == "closed":
            sets.append("closed_at=now()")
        if not sets:
            return {"id": dev_id}
        ex(conn, f"UPDATE deviation_reports SET {', '.join(sets)}, updated_at=now() WHERE id=%s", params + [dev_id])
        _audit_log(conn, user, "deviation_updated", "deviation_report", dev_id, {"fields": list(fields) + (["capa_actions"] if data.get("capa_actions") is not None else [])})
    return {"id": dev_id, "updated": True}


def list_deviations(status: Optional[str] = None) -> List[Dict[str, Any]]:
    today = _today()
    with tx() as conn:
        rows = q(conn, """SELECT id::text AS id, deviation_id, classification, trigger_type, trigger_ref, observation, impact_assessment,
                                 recommendations, responsible_department, responsible_person, status, capa_actions, target_close_date,
                                 investigation_start_date, closed_at, created_at, updated_at
                          FROM deviation_reports WHERE (%s::text IS NULL OR status=%s)
                          ORDER BY (status <> 'closed') DESC, created_at DESC""", (status, status))
    for r in rows:
        acts = r["capa_actions"] if isinstance(r["capa_actions"], list) else []
        r["capa_actions"] = acts
        r["capa_total"] = len(acts)
        r["capa_done"] = sum(1 for a in acts if str(a.get("status", "")).lower() in ("done", "completed", "closed"))
        r["capa_overdue"] = sum(1 for a in acts if str(a.get("status", "")).lower() not in ("done", "completed", "closed")
                                and _d(a.get("due_date")) and _d(a.get("due_date")) < today)
        r["overdue"] = bool(r["status"] in OPEN_DEVIATION and r["target_close_date"] and r["target_close_date"] < today)
    return rows


# ---------------------------------------------------------------------------
# Audits & maintenance scheduling
# ---------------------------------------------------------------------------

def _insert_audit(conn, data: Dict[str, Any]) -> str:
    d = _d(data.get("scheduled_date"))
    if not d:
        raise QualityError("Choose the audit date")
    if not (data.get("audit_type") or "").strip() or not (data.get("department") or "").strip():
        raise QualityError("Give the audit type and department")
    r = q1(conn, """INSERT INTO audit_schedule (audit_type, risk_level, frequency, department, month_due, year, assigned_to, status, notes, scheduled_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,%s) RETURNING id::text AS id""",
           (data["audit_type"].strip(), data.get("risk_level") or "medium", data.get("frequency") or "ad_hoc", data["department"].strip(),
            d.month, d.year, data.get("assigned_to"), data.get("notes"), d))
    return r["id"]


def schedule_audit(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    with tx() as conn:
        aid = _insert_audit(conn, data)
        _audit_log(conn, user, "audit_scheduled", "audit", aid, {"type": data.get("audit_type"), "date": data.get("scheduled_date")})
    return {"id": aid}


def schedule_next_audit(audit_id: str) -> Optional[str]:
    """After a recurring audit is completed, put the next one on the calendar."""
    with tx() as conn:
        a = q1(conn, "SELECT * FROM audit_schedule WHERE id::text=%s", (audit_id,))
        months = FREQ_MONTHS.get((a or {}).get("frequency") or "")
        if not a or not months:
            return None
        base = a["scheduled_date"] or dt.date(a["year"], a["month_due"] or 1, 1)
        nxt = _add_months(base, months)
        if q1(conn, "SELECT 1 FROM audit_schedule WHERE audit_type=%s AND department=%s AND scheduled_date=%s",
              (a["audit_type"], a["department"], nxt)):
            return None
        return _insert_audit(conn, {**a, "scheduled_date": nxt, "notes": None})


def schedule_maintenance(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    d = _d(data.get("next_maintenance_date"))
    if not data.get("equipment_id") or not d:
        raise QualityError("Choose the equipment and the date")
    mt = data.get("maintenance_type") or "preventive"
    if mt not in ("preventive", "calibration", "repair", "inspection"):
        raise QualityError("Unknown maintenance type")
    with tx() as conn:
        if not q1(conn, "SELECT 1 FROM equipment_registry WHERE id::text=%s", (data["equipment_id"],)):
            raise QualityError("Equipment not found")
        r = q1(conn, """INSERT INTO maintenance_schedule (equipment_id, maintenance_type, interval_days, next_maintenance_date, status)
                        VALUES (%s,%s,%s,%s,'scheduled') RETURNING id::text AS id""",
               (data["equipment_id"], mt, int(data.get("interval_days") or 90), d))
        _audit_log(conn, user, "maintenance_scheduled", "maintenance", r["id"], {"date": d, "type": mt})
    return {"id": r["id"]}


# ---------------------------------------------------------------------------
# Calendar: one feed over the real records
# ---------------------------------------------------------------------------

KINDS = {
    "event": "Event", "stock_order": "Stock delivery", "batch": "Incoming batch (QC)", "recall": "Recall return",
    "audit": "Audit", "maintenance": "Maintenance", "deviation": "Deviation due", "capa": "CAPA action",
    "activity": "Compliance activity", "expiry": "Stock expiring",
}


def calendar_feed(date_from: dt.date, date_to: dt.date, include_expiry: bool = True) -> Dict[str, Any]:
    today = _today()
    items: List[Dict[str, Any]] = []

    def add(kind: str, id_: str, date: Optional[dt.date], title: str, sub: str = "", status: str = "", done: bool = False,
            movable: bool = True, link: str = "", tone: str = "", meta: Optional[Dict[str, Any]] = None,
            can_be_overdue: bool = True) -> None:
        if not date:
            return
        overdue = can_be_overdue and (not done) and date < today
        # show future items in range, and anything still open that is overdue (surfaced on today)
        if not (date_from <= date <= date_to) and not (overdue and date_from <= today <= date_to):
            return
        items.append({"kind": kind, "id": str(id_), "date": date, "title": title, "subtitle": sub, "status": status,
                      "overdue": overdue, "done": done, "movable": movable and not done, "link": link,
                      "tone": tone or ("danger" if overdue else ""), "meta": meta or {}})

    with tx() as conn:
        for e in q(conn, """SELECT id::text AS id, title, description, event_type, start_time, location, metadata
                            FROM placeware_calendar_events WHERE start_time::date BETWEEN %s AND %s""", (date_from, date_to)):
            meta = e["metadata"] if isinstance(e["metadata"], dict) else json.loads(e["metadata"] or "{}")
            add("event", e["id"], e["start_time"].date(), e["title"], e["description"] or e["location"] or "", meta.get("status", ""),
                link="/calendar", meta={"event_type": e["event_type"], **meta}, can_be_overdue=False)
        for o in q(conn, """SELECT r.id::text AS id, r.sku, COALESCE(fp.name, r.sku) AS name, r.requested_qty, r.status, r.expected_date,
                                   r.po_id, s.name AS supplier FROM replenishment_requests r
                            LEFT JOIN fin_products fp ON fp.sku=r.sku LEFT JOIN suppliers s ON s.id=r.supplier_id
                            WHERE r.status='ordered' AND r.expected_date IS NOT NULL"""):
            add("stock_order", o["id"], o["expected_date"], f"Delivery: {o['name']}",
                f"{float(o['requested_qty']):g} units · {o['supplier'] or 'supplier'}{' · ref ' + o['po_id'] if o['po_id'] else ''}",
                "with supplier", link="/operations/purchase-orders?tab=orders")
        for b in q(conn, """SELECT id::text AS id, product_name, batch_number, expected_arrival_date, quantity, status, fin_batch_id
                            FROM nafdac_batch_registry WHERE status='pending' AND expected_arrival_date IS NOT NULL"""):
            add("batch", b["id"], b["expected_arrival_date"], f"Incoming batch: {b['product_name']}",
                f"batch {b['batch_number']}{' · ' + format(float(b['quantity']), 'g') + ' units' if b['quantity'] else ''}"
                f"{' · received, awaiting QC release' if b['fin_batch_id'] else ''}", "awaiting QC", link="/quality-control?tab=release")
        for r in q(conn, """SELECT id::text AS id, recall_id, product_name, batch_number, expected_return_date, status FROM recall_cases
                            WHERE status IN ('initiated','in_progress')"""):
            add("recall", r["id"], r["expected_return_date"], f"Recall {r['recall_id']}: {r['product_name']}",
                f"batch {r['batch_number']} · stock due back", r["status"].replace("_", " "), link="/quality-control?tab=recalls", tone="danger")
        for a in q(conn, """SELECT id::text AS id, audit_type, department, scheduled_date, status, assigned_to FROM audit_schedule
                            WHERE status IN ('scheduled','in_progress','overdue')"""):
            add("audit", a["id"], a["scheduled_date"], f"Audit: {a['audit_type']}", f"{a['department']}{' · ' + a['assigned_to'] if a['assigned_to'] else ''}",
                a["status"].replace("_", " "), link="/compliance?tab=audits")
        for m in q(conn, """SELECT m.id::text AS id, m.maintenance_type, m.next_maintenance_date, m.status, e.equipment_name, e.location
                            FROM maintenance_schedule m JOIN equipment_registry e ON e.id=m.equipment_id
                            WHERE m.status <> 'cancelled'"""):
            add("maintenance", m["id"], m["next_maintenance_date"], f"Maintenance: {m['equipment_name']}",
                f"{m['maintenance_type']} · {m['location']}", "due", link="/compliance?tab=maintenance")
        for d in q(conn, """SELECT id::text AS id, deviation_id, classification, observation, target_close_date, status, capa_actions
                            FROM deviation_reports WHERE status <> 'closed'"""):
            add("deviation", d["id"], d["target_close_date"], f"Close {d['deviation_id']} ({d['classification']})",
                (d["observation"] or "")[:80], d["status"].replace("_", " "), link="/compliance?tab=deviations",
                tone="danger" if d["classification"] == "critical" else "")
            for i, act in enumerate(d["capa_actions"] if isinstance(d["capa_actions"], list) else []):
                done = str(act.get("status", "")).lower() in ("done", "completed", "closed")
                add("capa", f"{d['id']}:{i}", _d(act.get("due_date")), f"CAPA: {act.get('action') or 'action'}",
                    f"{d['deviation_id']}{' · ' + act['owner'] if act.get('owner') else ''}", act.get("status") or "open", done=done,
                    link="/compliance?tab=deviations")
        for c in q(conn, """SELECT id::text AS id, activity_name, scheduled_date, status, department FROM compliance_activity_log
                            WHERE status IN ('scheduled','overdue','deferred')"""):
            add("activity", c["id"], c["scheduled_date"], c["activity_name"], c["department"] or "", c["status"], link="/compliance")
        if include_expiry:
            lots = lots_in_stock(conn)
            per_day: Dict[Any, Dict[str, Any]] = defaultdict(lambda: {"qty": 0.0, "value": 0.0, "lots": []})
            for l in lots:
                if l["expiry_date"] and date_from <= l["expiry_date"] <= date_to:
                    g = per_day[(l["expiry_date"], l["family"])]
                    g["qty"] += _f(l["qty"]); g["value"] += _f(l["value"]); g["lots"].append(l["batch_number"] or l["sku"])
            for (d0, fam), g in per_day.items():
                items.append({"kind": "expiry", "id": f"{fam}:{d0}", "date": d0, "title": f"Expires: {fam}",
                              "subtitle": f"{g['qty']:g} units · lots {', '.join(sorted(set(g['lots'])))}", "status": "",
                              "overdue": False, "done": d0 < today, "movable": False, "link": "/quality-control?tab=expiry",
                              "tone": "warning", "meta": {"value": round(g["value"], 2)}})
    # overdue open items are shown on today so nothing slips off the calendar
    for it in items:
        it["display_date"] = today if it["overdue"] else it["date"]
    items.sort(key=lambda i: (i["display_date"], i["kind"] != "recall", i["title"]))
    counts: Dict[str, int] = defaultdict(int)
    for it in items:
        counts[it["kind"]] += 1
    return {"from": date_from, "to": date_to, "items": items, "counts": dict(counts), "kinds": KINDS,
            "overdue": sum(1 for i in items if i["overdue"])}


def reschedule(user: Dict[str, Any], kind: str, id_: str, new_date: Any) -> Dict[str, Any]:
    """Move a calendar item: updates the record it comes from."""
    d = _d(new_date)
    if not d:
        raise QualityError("Choose the new date")
    with tx() as conn:
        if kind == "event":
            n = ex(conn, """UPDATE placeware_calendar_events SET start_time = %s::date + start_time::time,
                                   end_time = CASE WHEN end_time IS NULL THEN NULL ELSE end_time + (%s::date - start_time::date) END
                            WHERE id::text=%s""", (d, d, id_))
        elif kind == "stock_order":
            n = ex(conn, "UPDATE replenishment_requests SET expected_date=%s, updated_at=now() WHERE id::text=%s AND status='ordered'", (d, id_))
        elif kind == "batch":
            n = ex(conn, "UPDATE nafdac_batch_registry SET expected_arrival_date=%s, updated_at=now() WHERE id::text=%s", (d, id_))
        elif kind == "recall":
            n = ex(conn, "UPDATE recall_cases SET expected_return_date=%s, updated_at=now() WHERE id::text=%s", (d, id_))
        elif kind == "audit":
            n = ex(conn, """UPDATE audit_schedule SET scheduled_date=%s, month_due=%s, year=%s,
                                   status=CASE WHEN status='overdue' THEN 'scheduled' ELSE status END, updated_at=now()
                            WHERE id::text=%s""", (d, d.month, d.year, id_))
        elif kind == "maintenance":
            n = ex(conn, """UPDATE maintenance_schedule SET next_maintenance_date=%s,
                                   status=CASE WHEN status='overdue' THEN 'scheduled' ELSE status END, updated_at=now()
                            WHERE id::text=%s""", (d, id_))
        elif kind == "deviation":
            n = ex(conn, "UPDATE deviation_reports SET target_close_date=%s, updated_at=now() WHERE id::text=%s", (d, id_))
        elif kind == "capa":
            dev_id, idx = id_.rsplit(":", 1)
            row = q1(conn, "SELECT capa_actions FROM deviation_reports WHERE id::text=%s FOR UPDATE", (dev_id,))
            acts = (row or {}).get("capa_actions")
            acts = acts if isinstance(acts, list) else []
            if not row or int(idx) >= len(acts):
                raise LookupError("CAPA action not found")
            acts[int(idx)]["due_date"] = d.isoformat()
            n = ex(conn, "UPDATE deviation_reports SET capa_actions=%s::jsonb, updated_at=now() WHERE id::text=%s", (json.dumps(acts), dev_id))
        elif kind == "activity":
            n = ex(conn, "UPDATE compliance_activity_log SET scheduled_date=%s, updated_at=now() WHERE id::text=%s", (d, id_))
        else:
            raise QualityError(f"{KINDS.get(kind, kind)} items cannot be moved")
        if not n:
            raise LookupError("Item not found")
        _audit_log(conn, user, "rescheduled", kind, id_, {"date": d})
    return {"kind": kind, "id": id_, "date": d}


# ---------------------------------------------------------------------------
# Overview: Inventory & Quality at a glance
# ---------------------------------------------------------------------------

def overview() -> Dict[str, Any]:
    from src.services import books_analytics
    today = _today()
    exp = expiry_by_product(180)
    recalls = list_recalls()
    devs = list_deviations()
    batches = list_batches()
    feed = calendar_feed(today - dt.timedelta(days=1), today + dt.timedelta(days=30), include_expiry=False)
    with tx() as conn:
        audits = q1(conn, """SELECT COUNT(*) FILTER (WHERE status IN ('scheduled','in_progress') AND scheduled_date BETWEEN %s AND %s) AS due_30,
                                    COUNT(*) FILTER (WHERE status IN ('scheduled','overdue') AND scheduled_date < %s) AS overdue,
                                    COUNT(*) FILTER (WHERE status='completed' AND year=%s) AS done_this_year
                             FROM audit_schedule""", (today, today + dt.timedelta(days=30), today, today.year))
        maint = q1(conn, """SELECT COUNT(*) FILTER (WHERE status <> 'cancelled' AND next_maintenance_date BETWEEN %s AND %s) AS due_30,
                                   COUNT(*) FILTER (WHERE status <> 'cancelled' AND next_maintenance_date < %s) AS overdue,
                                   (SELECT COUNT(*) FROM equipment_registry WHERE status='active') AS equipment
                            FROM maintenance_schedule""", (today, today + dt.timedelta(days=30), today))
        held = q1(conn, """SELECT COUNT(DISTINCT b.id) AS lots, COALESCE(SUM(l.qty_remaining),0) AS units,
                                  COALESCE(SUM(l.qty_remaining * l.unit_cost),0) AS value
                           FROM fin_batches b JOIN fin_cost_layers l ON l.batch_id=b.id
                           WHERE b.status IN ('QUARANTINED','RECALLED') AND l.qty_remaining > 0""")
    open_recalls = [r for r in recalls if r["status"] in OPEN_RECALL]
    open_devs = [d for d in devs if d["status"] in OPEN_DEVIATION]
    pending_batches = [b for b in batches["batches"] if b["status"] == "pending"]
    s = exp["summary"]
    stock = books_analytics.stock_totals()
    # compliance score from what is actually overdue today (the stored 'overdue' statuses were never set)
    deductions = (audits["overdue"] * 8 + len(open_devs) * 3 + sum(1 for d in open_devs if d["overdue"]) * 3
                  + maint["overdue"] * 4 + len(open_recalls) * 5)
    return {
        "as_of": today,
        "stock": {"value": round(stock["value"], 2), "units": stock["units"], "items_in_stock": stock["skus_in_stock"],
                  "held_lots": held["lots"], "held_units": _f(held["units"]), "held_value": round(_f(held["value"]), 2)},
        "expiry": {k: {"products": v["products"], "units": v["units"], "value": round(v["value"], 2)} for k, v in s.items()},
        "expiry_unsellable_value": exp["unsellable_value"],
        "recalls": {"open": len(open_recalls), "overdue": sum(1 for r in open_recalls if r["overdue"]),
                    "customers_to_contact": sum(int(r["customers"] or 0) - int(r["contacted"] or 0) for r in open_recalls),
                    "units_frozen": sum(_f(r["units_frozen"]) for r in open_recalls),
                    "not_in_books": sum(1 for r in open_recalls if not r["fin_recall_id"])},
        "deviations": {"open": len(open_devs), "critical": sum(1 for d in open_devs if d["classification"] == "critical"),
                       "major": sum(1 for d in open_devs if d["classification"] == "major"),
                       "overdue": sum(1 for d in open_devs if d["overdue"]), "capa_overdue": sum(d["capa_overdue"] for d in open_devs)},
        "audits": {k: int(v or 0) for k, v in audits.items()},
        "maintenance": {k: int(v or 0) for k, v in maint.items()},
        "batches": {"pending": len(pending_batches), "late": sum(1 for b in pending_batches if b["late"]),
                    "received_unreleased": len(batches["received_unreleased"])},
        "compliance_score": max(0, 100 - deductions),
        "attention": [i for i in feed["items"] if i["overdue"]][:20],
        "upcoming": [i for i in feed["items"] if not i["overdue"] and i["date"] <= today + dt.timedelta(days=14)][:25],
    }
