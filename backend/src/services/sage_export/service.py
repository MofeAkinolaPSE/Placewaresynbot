"""ACE -> Sage 50 export: load unexported ACE activity, build the CSVs, record batches.

`plan()` is read-only (preview). `generate()` re-plans under an advisory lock,
then records every exported source row in sage_export_items -- the
UNIQUE(doc_type, source_id) there is what guarantees a transaction never
reaches Sage twice.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import RealDictCursor

from src.db import db
from src.services.sage_export import builders as B

log = logging.getLogger(__name__)

# Invoice statuses that mean "sold": finance has approved, goods may be out.
SALE_STATUSES = ("finance_approved", "dispatched", "completed")
REVERSED_STATUSES = ("cancelled", "finance_rejected")
ADJUST_EVENT_TYPES = ("DAMAGE", "EXPIRY", "ADJUSTMENT")
LOCAL_TZ = "Africa/Lagos"

# Import order in Sage: a journal row referencing an unknown customer is
# rejected, and receipts apply to invoices that must already exist.
# File names are Sage's own template defaults, so a file saved where the
# Sage template points is picked up without browsing.
FILE_ORDER = [
    ("customer", "CUSTOMER.CSV", "Accounts Receivable > Customer List"),
    ("sales", "SALES.CSV", "Accounts Receivable > Sales Journal"),
    ("receipts", "RECEIPTS.CSV", "Accounts Receivable > Cash Receipts Journal"),
    ("adjust", "ADJUST.CSV", "Inventory > Adjustments Journal"),
]
FILE_NAME = {doc: fname for doc, fname, _ in FILE_ORDER}
DOCS = [doc for doc, _, _ in FILE_ORDER]
PREVIEW_ROWS = 25


class ExportError(Exception):
    pass


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

class _Conn:
    def __enter__(self):
        self.conn = db.pool.getconn()
        return self.conn

    def __exit__(self, exc_type, *_):
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            db.pool.putconn(self.conn)


def _q(conn, sql: str, params: Any = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_SETTINGS_FIELDS = (
    "cutover_date", "ar_account", "delivery_gl_account", "discount_gl_account",
    "writeoff_gl_account", "period_anchor_month", "period_anchor_number",
    "payment_method_map", "column_selection", "sage_open_until",
)


def get_settings(conn=None) -> Dict[str, Any]:
    if conn is None:
        with _Conn() as c:
            return get_settings(c)
    rows = _q(conn, "SELECT * FROM sage_export_settings WHERE id = 1")
    if not rows:
        raise ExportError("sage_export_settings is missing -- apply migration 113")
    return rows[0]


def update_settings(changes: Dict[str, Any], actor: Optional[str]) -> Dict[str, Any]:
    fields = {k: v for k, v in changes.items() if k in _SETTINGS_FIELDS}
    if not fields:
        return get_settings()
    sets, params = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        if k == "column_selection":
            v = {doc: B.select_columns(doc, cols) for doc, cols in (v or {}).items() if doc in B.HEADERS}
        params.append(json.dumps(v) if k in ("payment_method_map", "column_selection") else v)
    sets += ["updated_by = %s", "updated_at = now()"]
    params.append(actor)
    with _Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE sage_export_settings SET {', '.join(sets)} WHERE id = 1", params)
        return get_settings(conn)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _item_accounts(conn) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    rows = _q(conn, "SELECT * FROM v_sage_item_accounts WHERE NOT COALESCE(inactive, FALSE)")
    exact = {r["item_id"]: r for r in rows}
    folded = {r["item_id"].lower(): r["item_id"] for r in rows}
    return exact, folded


def _sage_customers(conn) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    rows = _q(conn, "SELECT customer_id, name FROM v_customers WHERE customer_id IS NOT NULL")
    by_id = {r["customer_id"].lower(): r["customer_id"] for r in rows}
    by_name: Dict[str, List[str]] = {}
    for r in rows:
        if r.get("name"):
            by_name.setdefault(r["name"].strip().lower(), []).append(r["customer_id"])
    return by_id, by_name


def _range_clause(col: str) -> str:
    # Inclusive date range, never before the cut-over date.
    return f"{col} BETWEEN %(from)s AND %(to)s AND (%(cutover)s::date IS NULL OR {col} >= %(cutover)s::date)"


def _load_invoices(conn, params) -> List[Dict[str, Any]]:
    d = f"(i.created_at AT TIME ZONE '{LOCAL_TZ}')::date"
    return _q(conn, f"""
        SELECT i.id, i.invoice_number, {d} AS inv_date, i.due_date, i.payment_terms,
               i.customer_name, i.company_name, i.customer_po, i.shipping_method,
               i.shipping_address, i.billing_address, i.tax_amount, i.total_amount, i.items,
               c.id AS crm_id, c.customer_code, c.name AS crm_name, c.contact_details
        FROM frontdesk_invoices i
        LEFT JOIN frontdesk_walk_ins w ON w.id = i.walk_in_id
        LEFT JOIN customers c ON c.id = w.customer_id
        WHERE i.status IN %(sale_statuses)s
          AND {_range_clause(d)}
          AND NOT EXISTS (SELECT 1 FROM sage_export_items x
                          WHERE x.doc_type = 'sales' AND x.source_id = i.id::text)
        ORDER BY i.created_at, i.invoice_number
    """, params)


def _load_receipts(conn, params) -> List[Dict[str, Any]]:
    receipts = _q(conn, f"""
        SELECT r.id, r.receipt_number, r.customer_id, r.customer_name, r.amount,
               r.payment_method, r.receipt_date
        FROM ar_receipts r
        WHERE r.status = 'posted'
          AND {_range_clause('r.receipt_date')}
          AND NOT EXISTS (SELECT 1 FROM sage_export_items x
                          WHERE x.doc_type = 'receipts' AND x.source_id = r.id::text)
        ORDER BY r.receipt_date, r.created_at
    """, params)
    if receipts:
        apps = _q(conn, """
            SELECT receipt_id::text AS receipt_id, invoice_id, amount_applied
            FROM ar_receipt_applications WHERE receipt_id = ANY(%s::uuid[]) ORDER BY created_at
        """, ([str(r["id"]) for r in receipts],))
        by_receipt: Dict[str, list] = {}
        for a in apps:
            by_receipt.setdefault(a["receipt_id"], []).append(
                {"invoice_id": a["invoice_id"], "amount": a["amount_applied"]})
        for r in receipts:
            r["applications"] = by_receipt.get(str(r["id"]), [])
    return receipts


def _load_adjustments(conn, params) -> List[Dict[str, Any]]:
    d = f"(e.created_at AT TIME ZONE '{LOCAL_TZ}')::date"
    return _q(conn, f"""
        SELECT e.id, e.sku, e.quantity_change, e.event_type, e.reference, {d} AS event_date
        FROM placeware_inventory_events e
        WHERE e.event_type IN %(adjust_types)s
          AND {_range_clause(d)}
          AND NOT EXISTS (SELECT 1 FROM sage_export_items x
                          WHERE x.doc_type = 'adjust' AND x.source_id = e.id::text)
        ORDER BY e.created_at, e.id
    """, params)


def _needs_reversal(conn) -> List[Dict[str, Any]]:
    """Records already sent to Sage that were cancelled/voided in ACE since.
    Sage won't learn about these from an import -- the accountant must void them."""
    return _q(conn, """
        SELECT 'sales' AS doc_type, i.invoice_number AS ref, i.status, b.created_at AS exported_at
        FROM sage_export_items x
        JOIN frontdesk_invoices i ON x.doc_type = 'sales' AND i.id::text = x.source_id
        JOIN sage_export_batches b ON b.id = x.batch_id
        WHERE i.status IN %s
        UNION ALL
        SELECT 'receipts', r.receipt_number, r.status, b.created_at
        FROM sage_export_items x
        JOIN ar_receipts r ON x.doc_type = 'receipts' AND r.id::text = x.source_id
        JOIN sage_export_batches b ON b.id = x.batch_id
        WHERE r.status = 'voided'
        ORDER BY exported_at DESC LIMIT 100
    """, (REVERSED_STATUSES,))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _resolve_sku(line: dict, folded: Dict[str, str]) -> Optional[str]:
    from src.routers.frontdesk import _resolve_item_sku  # reuse dispatch's exact-match rules
    sku = _resolve_item_sku(line)
    if not sku:
        return None
    return folded.get(sku.lower(), sku)


def plan(date_from: dt.date, date_to: dt.date, conn=None) -> Dict[str, Any]:
    if conn is None:
        with _Conn() as c:
            return plan(date_from, date_to, c)
    if date_to < date_from:
        raise ExportError("'to' date is before 'from' date")

    settings = get_settings(conn)
    params = {
        "from": date_from, "to": date_to, "cutover": settings.get("cutover_date"),
        "sale_statuses": SALE_STATUSES, "adjust_types": ADJUST_EVENT_TYPES,
    }
    items, folded = _item_accounts(conn)
    sage_ids, sage_names = _sage_customers(conn)
    taken_ids = set(sage_ids) | {
        r["customer_code"].lower() for r in _q(conn, "SELECT customer_code FROM customers WHERE customer_code IS NOT NULL")
    }
    already_sent = {r["source_id"] for r in _q(conn, "SELECT source_id FROM sage_export_items WHERE doc_type = 'customer'")}

    # ---- Sales + the new customers they need ----------------------------
    new_customers: Dict[str, Dict[str, Any]] = {}   # crm_id -> customer
    invoices = []
    for r in _load_invoices(conn, params):
        cust_id, cust_name = _resolve_customer(r, sage_ids, sage_names, taken_ids, new_customers, already_sent)
        lines = []
        for l in r.get("items") or []:
            lines.append({**l, "sku": _resolve_sku(l, folded)})
        invoices.append({
            "id": str(r["id"]), "invoice_number": r["invoice_number"], "date": r["inv_date"],
            "due_date": r.get("due_date"), "terms": r.get("payment_terms"),
            "customer_id": cust_id, "customer_name": cust_name or r.get("company_name") or r.get("customer_name"),
            "customer_po": r.get("customer_po"), "ship_via": r.get("shipping_method"),
            "ship_address": r.get("shipping_address"), "tax_amount": r.get("tax_amount"),
            "total_amount": r.get("total_amount"), "lines": lines,
            "_crm_id": r.get("crm_id"),
        })
    sales_rows, sales_blocked, sales_ids = B.build_sales(invoices, items, settings)

    # Only send customers whose invoice actually made it into this batch.
    exported_inv = set(sales_ids)
    needed_crm = {str(i["_crm_id"]) for i in invoices if i["id"] in exported_inv and i.get("_crm_id")}
    customers = [c for k, c in new_customers.items() if k in needed_crm]
    customer_rows = B.build_customers(customers, dt.date.today())

    # ---- Receipts ------------------------------------------------------------
    receipts = [{
        "id": str(r["id"]), "receipt_number": r["receipt_number"],
        "customer_id": sage_ids.get((r.get("customer_id") or "").lower(), r.get("customer_id")),
        "customer_name": r.get("customer_name"), "date": r["receipt_date"],
        "amount": r["amount"], "payment_method": r.get("payment_method"),
        "applications": r.get("applications") or [],
    } for r in _load_receipts(conn, params)]
    receipt_rows, receipt_blocked, receipt_ids = B.build_receipts(receipts, settings)

    # ---- Adjustments --------------------------------------------------------
    events = [{
        "id": r["id"], "sku": folded.get((r.get("sku") or "").lower(), r.get("sku")),
        "quantity_change": r["quantity_change"], "event_type": r["event_type"],
        "reference": r.get("reference"), "date": r["event_date"],
    } for r in _load_adjustments(conn, params)]
    adjust_rows, adjust_blocked, adjust_ids = B.build_adjustments(events, items, settings)

    ar_total = sum(float(i["total_amount"] or 0) for i in invoices if i["id"] in exported_inv)
    receipts_total = sum(float(r["amount"] or 0) for r in receipts if r["id"] in set(receipt_ids))
    warnings = []
    if not items:
        warnings.append("No Sage item accounts loaded -- import ITEM.CSV as 'Item GL Accounts' on the Import tab first.")
    if not settings.get("cutover_date"):
        warnings.append("No cut-over date set. Set it before generating so nothing already keyed into Sage is exported.")

    rows_by_doc = {"customer": customer_rows, "sales": sales_rows, "receipts": receipt_rows, "adjust": adjust_rows}
    last = {r["doc_type"]: r["at"] for r in _q(conn, """
        SELECT x.doc_type, max(b.created_at) AS at
        FROM sage_export_items x JOIN sage_export_batches b ON b.id = x.batch_id GROUP BY 1
    """)}
    selection = settings.get("column_selection") or {}
    all_blocked = sales_blocked + receipt_blocked + adjust_blocked
    docs = {
        "customer": {"records": len(customers)},
        "sales": {"records": len(sales_ids), "total": round(ar_total, 2)},
        "receipts": {"records": len(receipt_ids), "total": round(receipts_total, 2)},
        "adjust": {"records": len(adjust_ids)},
    }
    for doc, meta in docs.items():
        meta.update({
            "rows": len(rows_by_doc[doc]),
            "file_name": FILE_NAME[doc],
            "headers": B.HEADERS[doc],
            "required": B.REQUIRED[doc],
            "ace_fields": [h for h in B.HEADERS[doc] if h in B.SET_BY_ACE.get(doc, ())],
            "defaults": {h: v for h, v in B.CONSTANTS.get(doc, {}).items() if v != ""},
            "columns": B.select_columns(doc, selection.get(doc)),
            "preview_rows": rows_by_doc[doc][:PREVIEW_ROWS],
            "blocked": sum(1 for b in all_blocked if b["doc_type"] == doc),
            "last_exported": last[doc].isoformat() if last.get(doc) else None,
        })
    if customers:
        docs["sales"]["depends_on"] = (
            f"Export the Customer List first: {len(customers)} customer(s) on these invoices are new to Sage"
        )

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "settings": _public_settings(settings),
        "docs": docs,
        "blocked": sales_blocked + receipt_blocked + adjust_blocked,
        "needs_reversal": _jsonable(_needs_reversal(conn)),
        "warnings": warnings,
        # internals for generate()
        "_rows": {"customer": customer_rows, "sales": sales_rows, "receipts": receipt_rows, "adjust": adjust_rows},
        "_ids": {
            "customer": [(str(c["crm_id"]), c["customer_id"]) for c in customers],
            "sales": sales_ids, "receipts": receipt_ids, "adjust": [str(i) for i in adjust_ids],
        },
        "_code_writebacks": [(c["crm_id"], c["customer_id"]) for c in customers if c.get("needs_code")],
    }


def _resolve_customer(r, sage_ids, sage_names, taken_ids, new_customers, already_sent):
    """Return (sage_customer_id, display_name) for an invoice row, registering
    a new Sage customer when the CRM customer isn't in Sage yet."""
    crm_id = r.get("crm_id")
    if crm_id is not None:
        code = (r.get("customer_code") or "").strip()
        if code and code.lower() in sage_ids:
            return sage_ids[code.lower()], r.get("crm_name")
        key = str(crm_id)
        if key in new_customers:
            return new_customers[key]["customer_id"], r.get("crm_name")
        if code and len(code) > B.MAX_CUSTOMER_ID:
            return None, r.get("crm_name")
        needs_code = not code
        if needs_code:
            code = B.propose_customer_id(r.get("crm_name") or "", taken_ids)
            taken_ids.add(code.lower())
        if key not in already_sent:
            cd = r.get("contact_details") or {}
            new_customers[key] = {
                "crm_id": crm_id, "customer_id": code, "name": r.get("crm_name"),
                "phone": cd.get("phone"), "email": cd.get("email"),
                "address": cd.get("address"), "city": cd.get("city"), "needs_code": needs_code,
            }
        return code, r.get("crm_name")

    # Walk-in with no CRM link: accept only an unambiguous exact match.
    for name in (r.get("company_name"), r.get("customer_name")):
        n = (name or "").strip().lower()
        if not n:
            continue
        if n in sage_ids:
            return sage_ids[n], name
        ids = sage_names.get(n) or []
        if len(ids) == 1:
            return ids[0], name
    return None, r.get("company_name") or r.get("customer_name")


def _public_settings(s: Dict[str, Any]) -> Dict[str, Any]:
    return _jsonable({k: s.get(k) for k in _SETTINGS_FIELDS})


def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


def public_plan(p: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in p.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Generate / download
# ---------------------------------------------------------------------------

def generate(date_from: dt.date, date_to: dt.date, actor: Optional[str],
             docs: Optional[List[str]] = None) -> Dict[str, Any]:
    wanted = [d for d in DOCS if d in (docs or DOCS)]
    if not wanted:
        raise ExportError(f"Choose at least one document: {', '.join(DOCS)}")
    with _Conn() as conn:
        with conn.cursor() as cur:
            # Serialise exports so two clicks can't both claim the same rows.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('ace_sage_export'))")
        settings = get_settings(conn)
        if not settings.get("cutover_date"):
            raise ExportError("Set the cut-over date in Export settings before generating a batch")
        p = plan(date_from, date_to, conn)
        if "sales" in wanted and "customer" not in wanted and p["_rows"]["customer"]:
            # Sage rejects an invoice for a customer it doesn't know yet.
            raise ExportError(p["docs"]["sales"]["depends_on"])
        if not any(p["_rows"][d] for d in wanted):
            names = ", ".join(FILE_NAME[d] for d in wanted)
            raise ExportError(f"Nothing new to export in {names} for this period")

        selection = settings.get("column_selection") or {}
        files = {
            FILE_NAME[doc]: B.to_csv(doc, p["_rows"][doc], selection.get(doc))
            for doc in wanted if p["_rows"][doc]
        }
        counts = {doc: {k: p["docs"][doc].get(k) for k in ("records", "rows", "total")}
                  for doc in wanted if p["_rows"][doc]}
        blocked = [b for b in p["blocked"] if b["doc_type"] in wanted]
        batch = _q(conn, """
            INSERT INTO sage_export_batches (period_from, period_to, counts, blocked, files, created_by)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at
        """, (date_from, date_to, json.dumps(counts), json.dumps(blocked), json.dumps(files), actor))[0]
        bid = batch["id"]

        items: List[Tuple] = []
        if "customer" in wanted:
            for crm_id, code in p["_ids"]["customer"]:
                items.append((bid, "customer", "customers", crm_id, code))
        for doc, table in (("sales", "frontdesk_invoices"), ("receipts", "ar_receipts"),
                           ("adjust", "placeware_inventory_events")):
            if doc in wanted:
                items += [(bid, doc, table, i, None) for i in p["_ids"][doc]]
        with conn.cursor() as cur:
            for it in items:
                cur.execute("""
                    INSERT INTO sage_export_items (batch_id, doc_type, source_table, source_id, sage_ref)
                    VALUES (%s, %s, %s, %s, %s) ON CONFLICT (doc_type, source_id) DO NOTHING
                """, it)
                if cur.rowcount != 1:  # impossible under the lock; refuse rather than double-post
                    raise ExportError(f"{it[1]} {it[3]} was already exported -- refresh and retry")
            for crm_id, code in (p["_code_writebacks"] if "customer" in wanted else []):
                # Remember the Sage ID we assigned so the next export reuses it.
                cur.execute("UPDATE customers SET customer_code = %s WHERE id = %s AND customer_code IS NULL",
                            (code, crm_id))
            try:
                cur.execute("SAVEPOINT sync_log")
                cur.execute("""
                    INSERT INTO placeware_sage_sync_log (entity_type, direction, synbot_id, status, payload)
                    VALUES ('export_batch', 'synbot_to_sage', %s, 'exported', %s)
                """, (str(bid), json.dumps({"counts": counts, "period": p["period"]})))
            except Exception as exc:  # audit trail is nice-to-have, never block the batch
                cur.execute("ROLLBACK TO SAVEPOINT sync_log")
                log.warning("sage export: sync log write failed: %s", exc)

        return {"id": str(bid), "created_at": batch["created_at"].isoformat(),
                "files": list(files), "counts": counts, "blocked": blocked}


def list_batches(limit: int = 50) -> List[Dict[str, Any]]:
    with _Conn() as conn:
        rows = _q(conn, """
            SELECT id, period_from, period_to, counts, jsonb_array_length(blocked) AS blocked_count,
                   (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(files) k) AS files,
                   created_by, created_at
            FROM sage_export_batches ORDER BY created_at DESC LIMIT %s
        """, (limit,))
    return _jsonable(rows)


def delete_batch(batch_id: str) -> int:
    """Release a batch's records so they export again -- only for a batch the
    accountant confirms was NOT imported into Sage (e.g. the import failed)."""
    with _Conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sage_export_batches WHERE id = %s", (batch_id,))
            return cur.rowcount


def batch_file(batch_id: str, file_name: str) -> bytes:
    """One CSV from a batch, byte-identical to what was generated."""
    with _Conn() as conn:
        rows = _q(conn, "SELECT files FROM sage_export_batches WHERE id = %s", (batch_id,))
    files = (rows[0]["files"] or {}) if rows else {}
    if file_name not in files:
        raise ExportError("File not found in this batch")
    # cp1252 like Sage's own exports; unmappable chars are replaced, not dropped.
    return files[file_name].encode("cp1252", errors="replace")


def batch_zip(batch_id: str) -> Tuple[str, bytes]:
    with _Conn() as conn:
        rows = _q(conn, "SELECT * FROM sage_export_batches WHERE id = %s", (batch_id,))
    if not rows:
        raise ExportError("Batch not found")
    b = rows[0]
    files: Dict[str, str] = b["files"] or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, fname, _ in FILE_ORDER:
            if fname in files:
                # cp1252 like Sage's own exports; unmappable chars are replaced, not dropped.
                zf.writestr(fname, files[fname].encode("cp1252", errors="replace"))
        zf.writestr("README.txt", _readme(b, files))
    name = f"ace_to_sage_{b['period_from']}_{b['period_to']}.zip"
    return name, buf.getvalue()


def _readme(b: Dict[str, Any], files: Dict[str, str]) -> str:
    lines = [
        "ACE -> Sage 50 import batch",
        f"Batch:   {b['id']}",
        f"Period:  {b['period_from']} to {b['period_to']}",
        f"Created: {b['created_at']:%Y-%m-%d %H:%M} by {b.get('created_by') or '-'}",
        "",
        "BEFORE YOU START",
        "  * Back up the Sage company (File > Back Up).",
        "  * Post any supplier bills for this period in Sage first, so stock is",
        "    received before it is sold.",
        "",
        "IMPORT IN THIS ORDER (File > Select Import/Export, pick the template, Import,",
        "Options tab: 'First Row Contains Headings' ticked, then OK):",
    ]
    n = 0
    for doc, fname, where in FILE_ORDER:
        if fname in files:
            n += 1
            lines.append(f"  {n}. {fname:<16} -> {where}")
    lines += [
        "",
        "AFTER IMPORT",
        "  * Check the Sales Journal / Cash Receipts Journal reports for the period.",
        "  * Re-export Aged Receivables into ACE's Sage Import page so ACE sees the",
        "    new invoices as open receivables.",
        "  * If an import FAILED and nothing was posted, delete this batch in ACE",
        "    (Export history) so its records can be exported again.",
        "",
        "Do not key these invoices/receipts into Sage by hand as well -- they would",
        "post twice.",
    ]
    return "\r\n".join(lines) + "\r\n"
