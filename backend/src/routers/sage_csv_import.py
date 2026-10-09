"""
sage_csv_import.py — POST /sage/import/csv

Accepts multipart CSV file uploads for each of the 10 ACE
data-package file types and persists them to their corresponding
Supabase snapshot tables.

Supported file_type values:
  chart_of_accounts       → sage_coa_snapshot
  vendors                 → sage_vendors_snapshot
  customers               → sage_customers_snapshot
  items                   → sage_items_snapshot
  stock_on_hand           → sage_inventory_snapshot
  purchase_orders         → sage_purchase_orders_snapshot
  sales_invoices          → sage_ar_snapshot
  sales_invoice_lines     → sage_invoice_lines_snapshot
  inventory_transactions  → sage_inv_transactions_snapshot
  gl_journal_entries      → sage_gl_snapshot
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import re
import uuid
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from src.cache import invalidate_cache_tags, clear_cache
from src.db import audit_event, create_import_job, db, insert_snapshot
from src.middleware import verify_jwt, require_role

logger = logging.getLogger("sage_csv_import")

router = APIRouter(prefix="/sage/import", tags=["sage-import"])


def _prune_old_batches(table: str, keep: int = 14) -> int:
    """Delete rows from all but the most recent `keep` batches of `table`.

    Snapshot tables are pure-append (insert_snapshot never deletes), which is
    fine for one-time historical loads but grows unbounded under a recurring
    upload cadence — every prior day's batch stays in the table forever,
    invisible to reads (which always filter to the latest batch_id) but still
    taking up space. Called after each sales_invoices/sales_invoice_lines
    import so the daily-refresh flow doesn't need any separate scheduled job.
    Best-effort: failures are logged, never raised — pruning is a housekeeping
    step, not something that should fail an otherwise-successful upload.
    """
    from src.db import get_psycopg_dsn
    try:
        import psycopg2
    except ImportError:
        return 0

    sql = f"""
        DELETE FROM public."{table}"
        WHERE batch_id NOT IN (
            SELECT batch_id FROM (
                SELECT DISTINCT batch_id, MAX(imported_at) AS latest
                FROM public."{table}"
                GROUP BY batch_id
                ORDER BY latest DESC
                LIMIT %s
            ) recent
        )
    """
    try:
        conn = psycopg2.connect(get_psycopg_dsn())
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql, (keep,))
            deleted = cur.rowcount
        conn.close()
        if deleted > 0:
            logger.info(f"_prune_old_batches: removed {deleted} rows from {table} outside the last {keep} batches")
        return deleted
    except Exception as exc:
        logger.warning(f"_prune_old_batches: failed for {table} (non-fatal): {exc}")
        return 0


def _sync_placeware_invoices(batch_id: str) -> None:
    """Upsert placeware_invoices from a freshly-imported sage_ar_snapshot batch.

    Called automatically after every sales_invoices CSV import so that
    placeware_invoices stays in sync without a separate manual step.
    """
    rows = (
        db.table("sage_ar_snapshot")
        .select("invoice_id, customer_id, date, due_date, amount, balance, status")
        .eq("batch_id", batch_id)
        .execute()
        .data or []
    )
    if not rows:
        return

    # Bulk-fetch customer names once to avoid N+1 queries
    cust_ids = list({r["customer_id"] for r in rows if r.get("customer_id")})
    name_map: dict[str, str] = {}
    if cust_ids:
        custs = (
            db.table("v_customers")
            .select("customer_id, name")
            .in_("customer_id", cust_ids)
            .execute()
            .data or []
        )
        name_map = {c["customer_id"]: c["name"] for c in custs}

    upsert_rows = [
        {
            "invoice_id":    r["invoice_id"],
            "customer_id":   r.get("customer_id"),
            "customer_name": name_map.get(r.get("customer_id") or "", None),
            "invoice_date":  r.get("date"),
            "due_date":      r.get("due_date"),
            "total_amount":  r.get("amount"),
            "outstanding":   r.get("balance"),
            "status":        r.get("status") or "open",
            "synced_from":   "sage_50",
            "updated_at":    datetime.datetime.utcnow().replace(
                tzinfo=datetime.timezone.utc
            ).isoformat(),
        }
        for r in rows
        if r.get("invoice_id")
    ]
    if upsert_rows:
        db.table("placeware_invoices").upsert(
            upsert_rows, on_conflict="invoice_id"
        ).execute()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_import_role(request: Request) -> Dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {"admin", "finance", "management"}
    if not roles.intersection(allowed):
        raise HTTPException(
            status_code=403,
            detail=f"Roles required: {sorted(allowed)}. Caller has: {sorted(roles)}",
        )
    return payload


# ---------------------------------------------------------------------------
# Column-mapping registry
# Each mapper receives a raw CSV row (dict of str→str) and returns a cleaned
# dict ready to be stamped with batch_id / imported_at by insert_snapshot().
# Any validation error should raise ValueError with a human-readable message.
# ---------------------------------------------------------------------------

def _safe_float(val: Optional[str], default: float = 0.0) -> float:
    try:
        return float(val) if val not in (None, "", "None", "N/A") else default
    except (ValueError, TypeError):
        return default


def _safe_bool(val: Optional[str], default: bool = True) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "t")


def _safe_date(val: Optional[str]) -> Optional[str]:
    """Return ISO date string or None."""
    if not val or val.strip() in ("", "None", "N/A", "null"):
        return None
    return val.strip()


def _norm_header(h: Any) -> str:
    """Normalise a header cell to a clean snake_case key.

    Same regex-based approach as data-assimilation/ingest_sage_exports.py's
    _norm_header — handles the punctuation Sage 50 report headers actually
    contain ("Invoice/CM #", "Invoice No.", "Amnt Remaining") that a plain
    space/dash replace misses.
    """
    if h is None:
        return ""
    s = str(h).replace("\n", " ").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _read_xlsx_rows(raw_bytes: bytes) -> List[Dict[str, str]]:
    """Parse an .xlsx file into a list of normalised-header row dicts,
    matching the shape csv.DictReader produces so the rest of the pipeline
    (mappers, validation) is identical regardless of upload format."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        raw_rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not raw_rows:
        return []

    headers = [_norm_header(h) for h in raw_rows[0]]
    rows: List[Dict[str, str]] = []
    for values in raw_rows[1:]:
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        row: Dict[str, str] = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            v = values[i] if i < len(values) else None
            row[h] = "" if v is None else str(v)
        rows.append(row)
    return rows


# -- individual mapper functions --------------------------------------------

def _map_chart_of_accounts(row: Dict[str, str]) -> Dict[str, Any]:
    account_id = (row.get("account_id") or row.get("account_no") or row.get("id") or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    return {
        "account_id": account_id,
        "account_code": (row.get("account_code") or row.get("account_no") or account_id).strip(),
        "account_name": (row.get("account_name") or row.get("account_description") or row.get("description") or row.get("name") or "Unknown").strip(),
        "account_type": row.get("account_type", "").strip() or None,
        "parent_account_id": row.get("parent_account_id", "").strip() or None,
        "description": row.get("description", "").strip() or None,
        "is_active": _safe_bool(row.get("is_active"), default=True),
    }


def _map_vendors(row: Dict[str, str]) -> Dict[str, Any]:
    vendor_id = (row.get("vendor_id") or row.get("vendor_no") or row.get("id") or "").strip()
    if not vendor_id:
        raise ValueError("vendor_id is required")
    return {
        "vendor_id": vendor_id,
        "vendor_name": (row.get("vendor_name") or row.get("name") or row.get("company_name") or "Unknown").strip(),
        "contact_name": row.get("contact_name", "").strip() or None,
        "email": row.get("email", "").strip() or None,
        "phone": row.get("phone", "").strip() or None,
        "address": row.get("address", "").strip() or None,
        "city": row.get("city", "").strip() or None,
        "state": row.get("state", "").strip() or None,
        "country": row.get("country", "").strip() or None,
        "payment_terms": row.get("payment_terms", "").strip() or None,
        "tax_id": row.get("tax_id", "").strip() or None,
        "status": row.get("status", "active").strip() or "active",
    }


def _map_customers(row: Dict[str, str]) -> Dict[str, Any]:
    customer_id = (row.get("customer_id") or row.get("customer_no") or row.get("id") or "").strip()
    if not customer_id:
        raise ValueError("customer_id is required")
    return {
        "customer_id": customer_id,
        "name": (row.get("name") or row.get("customer_name") or row.get("company_name") or "Unknown").strip(),
        "email": row.get("email", "").strip() or None,
        "phone": row.get("phone", "").strip() or None,
        "status": row.get("status", "active").strip() or "active",
        "address": (row.get("address") or "").strip() or None,
        "city": (row.get("city") or "").strip() or None,
        "contact_person": (row.get("contact_person") or "").strip() or None,
        "terms": (row.get("terms") or "").strip() or None,
        "customer_since": _safe_date(row.get("customer_since")) or None,
    }


def _map_customer_sales(row: Dict[str, str]) -> Dict[str, Any]:
    customer_id = (row.get("customer_id") or "").strip()
    if not customer_id:
        raise ValueError("customer_id is required")
    return {
        "customer_id": customer_id,
        "name": (row.get("name") or "").strip() or None,
        "amount": _safe_float(row.get("amount")),
        "cost_of_sales": _safe_float(row.get("cost_of_sales")),
        "gross_profit": _safe_float(row.get("gross_profit")),
        "gross_margin": _safe_float(row.get("gross_margin")),
    }


def _map_items(row: Dict[str, str]) -> Dict[str, Any]:
    def _first(*keys: str) -> str:
        for k in keys:
            v = row.get(k)
            if v is not None and str(v).strip() not in ("", "None", "N/A", "null"):
                return str(v).strip()
        return ""

    item_id = _first("item_id", "code", "item_code", "stock_code", "sku", "id")
    if not item_id:
        raise ValueError("item_id is required")
    return {
        "item_id": item_id,
        "item_name": _first("item_name", "description", "name", "stock_description") or "Unknown",
        "category": _first("category", "item_category", "item_class", "product_category", "group") or None,
        "unit": _first("unit", "unit_of_measure", "uom", "uom_code") or None,
        "cost_price": _safe_float(
            row.get("cost_price") or row.get("standard_cost") or row.get("unit_cost")
            or row.get("average_cost") or row.get("cost")
        ),
        "selling_price": _safe_float(
            row.get("selling_price") or row.get("sale_price")
            or row.get("unit_price") or row.get("price")
        ),
        "vat_category": _first("vat_category", "tax_code", "tax_type", "vat_code") or None,
        "reorder_level": _safe_float(row.get("reorder_level") or row.get("minimum_quantity") or row.get("reorder_point")),
        "preferred_vendor_id": _first("preferred_vendor_id", "vendor_id", "pref_vendor") or None,
        "expiry_date": _safe_date(row.get("expiry_date") or row.get("expiry")),
        "batch_number": _first("batch_number", "batch", "lot_number", "lot_code") or None,
        "is_active": _safe_bool(row.get("is_active") or row.get("active"), default=True),
        "company_id": row.get("company_id") or None,
    }


def _map_stock_on_hand(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps stock_on_hand.csv → sage_inventory_snapshot columns."""
    item_id = row.get("item_id", "").strip()
    if not item_id:
        raise ValueError("item_id is required")
    return {
        "sku": item_id,
        # CSV may not have item_name; fall back to description or item_id
        "name": (
            row.get("item_name", "").strip()
            or row.get("item_description", "").strip()
            or row.get("description", "").strip()
            or item_id
        ),
        # Support both Sage Classic (quantity_on_hand) and Sage 200 (quantity_available)
        "quantity": _safe_float(row.get("quantity_on_hand") or row.get("quantity_available") or row.get("qty_on_hand") or row.get("qty")),
        "unit_cost": _safe_float(row.get("unit_cost") or row.get("average_cost") or row.get("cost") or row.get("cost_price")),
        "valuation": _safe_float(row.get("total_value") or row.get("stock_value") or row.get("valuation") or row.get("total_cost")),
        "updated_at": _safe_date(row.get("last_updated")) or datetime.datetime.utcnow().isoformat(),
        "warehouse_id": row.get("warehouse_id", "").strip() or None,
        "reorder_level": _safe_float(row.get("reorder_level")),
        "reorder_quantity": _safe_float(row.get("reorder_quantity")),
        "expiry_date": _safe_date(row.get("expiry_date")),
        "batch_number": row.get("batch_number", "").strip() or None,
        "storage_condition": row.get("storage_condition", "").strip() or None,
    }


def _map_purchase_orders(row: Dict[str, str]) -> Dict[str, Any]:
    po_id = row.get("po_id", "").strip()
    if not po_id:
        raise ValueError("po_id is required")
    return {
        "po_id": po_id,
        "po_number": row.get("po_number", po_id).strip(),
        "vendor_id": row.get("vendor_id", "").strip() or None,
        "order_date": _safe_date(row.get("order_date")),
        "expected_delivery_date": _safe_date(row.get("expected_delivery_date")),
        "total_amount": _safe_float(row.get("total_amount")),
        "tax_amount": _safe_float(row.get("tax_amount")),
        "discount_amount": _safe_float(row.get("discount_amount")),
        "net_amount": _safe_float(row.get("net_amount")),
        # Blank status is left NULL, not fabricated as "open" — a bulk historical
        # PO export with a mostly-empty status column would otherwise count every
        # row as a currently-open order (see purchase_orders_summary()'s stale-date
        # handling for how NULL status is actually resolved into open/closed).
        "status": row.get("status", "").strip() or None,
        "warehouse_id": row.get("warehouse_id", "").strip() or None,
        "created_by": row.get("created_by", "").strip() or None,
    }


def _map_sales_invoices(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps sales_invoices.csv/.xlsx → sage_ar_snapshot columns.

    Also accepts Sage 50's "Customer Management Details" report shape
    directly (invoice_no, date_due, amnt_remaining) — the recurring daily AR
    refresh source. That report carries the real outstanding balance per
    invoice, so amnt_remaining is used as both amount and balance rather than
    the amount==balance guess used for sources that only have a status flag.
    """
    invoice_id = (row.get("invoice_id") or row.get("invoice_no") or row.get("inv_no") or "").strip()
    customer_id = (row.get("customer_id") or row.get("customer_no") or row.get("account_id") or "").strip()
    if not invoice_id:
        raise ValueError("invoice_id is required")
    if not customer_id:
        raise ValueError("customer_id is required")
    raw_date = _safe_date(row.get("invoice_date") or row.get("date")) or datetime.date.today().isoformat()

    remaining_raw = row.get("amnt_remaining")
    if remaining_raw not in (None, "", "None", "N/A"):
        # Real outstanding balance from Sage — use it for both amount and
        # balance since this report shape has no separate original-total column.
        remaining = _safe_float(remaining_raw)
        net_amount = remaining
        balance = remaining
        status = (row.get("status") or ("paid" if remaining <= 0 else "open")).strip().lower()
    else:
        net_amount = _safe_float(row.get("net_amount") or row.get("amount") or row.get("total_amount") or row.get("invoice_amount") or row.get("net_amount_due"))
        status = row.get("status", "unpaid").strip().lower()
        # AR balance: for paid invoices it's 0; for unpaid/partial it's net_amount
        balance = 0.0 if status == "paid" else net_amount

    due_date = _safe_date(row.get("due_date") or row.get("date_due"))
    return {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "date": raw_date,
        "due_date": due_date,
        "amount": net_amount,
        "balance": balance,
        "status": status,
    }


def _map_invoice_lines(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps sales_invoice_lines.csv/.xlsx → sage_invoice_lines_snapshot columns.

    Also accepts Sage 50's "Items sold to customers" report shape directly
    (customer_id, item_id, qty, amount, cost_of_sales, gross_profit) — that
    report has no invoice-number column at all (it's a customer-level product
    listing, not per-invoice lines), so when line_id/invoice_id are absent
    they're synthesized from customer_id+item_id. This is a real limitation
    of the source data, not a bug: rows can't be tied back to a specific
    invoice. Downstream consumers (e.g. CRM 360 "top purchased items") sum by
    item_id anyway, so this is fine for that use case.
    """
    item_id = (row.get("item_id") or "").strip() or None
    customer_id = (row.get("customer_id") or "").strip()

    line_id = row.get("line_id", "").strip()
    invoice_id = row.get("invoice_id", "").strip()
    if not invoice_id:
        if not customer_id:
            raise ValueError("invoice_id (or customer_id, to synthesize one) is required")
        invoice_id = f"SOLD_{customer_id}"
    if not line_id:
        line_id = f"{invoice_id}_{item_id}" if item_id else invoice_id

    quantity = _safe_float(row.get("quantity") or row.get("qty"))
    line_total = _safe_float(row.get("line_total") or row.get("amount"))
    cost_at_sale = _safe_float(row.get("cost_at_sale") or row.get("cost_of_sales"))
    gross_profit_raw = row.get("gross_profit")
    gross_profit = (
        _safe_float(gross_profit_raw)
        if gross_profit_raw not in (None, "", "None", "N/A")
        else round(line_total - cost_at_sale, 4)
    )
    unit_price = _safe_float(row.get("unit_price")) or (
        round(line_total / quantity, 4) if quantity else 0.0
    )

    return {
        "line_id": line_id,
        "invoice_id": invoice_id,
        "item_id": item_id,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount": _safe_float(row.get("discount")),
        "line_total": line_total,
        "cost_at_sale": cost_at_sale,
        "gross_profit": gross_profit,
    }


def _map_inventory_transactions(row: Dict[str, str]) -> Dict[str, Any]:
    txn_id = row.get("transaction_id", "").strip()
    if not txn_id:
        raise ValueError("transaction_id is required")
    return {
        "transaction_id": txn_id,
        "item_id": row.get("item_id", "").strip() or None,
        "warehouse_id": row.get("warehouse_id", "").strip() or None,
        "transaction_type": row.get("transaction_type", "").strip() or None,
        "quantity_in": _safe_float(row.get("quantity_in")),
        "quantity_out": _safe_float(row.get("quantity_out")),
        "unit_cost": _safe_float(row.get("unit_cost")),
        "reference_number": row.get("reference_number", "").strip() or None,
        "transaction_date": _safe_date(row.get("transaction_date")),
        "posted_by": row.get("posted_by", "").strip() or None,
    }


def _map_gl_journal_entries(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps gl_journal_entries.csv → sage_gl_snapshot columns."""
    posting_date = _safe_date(row.get("posting_date") or row.get("date")) or ""
    # Derive YYYY-MM period from posting_date
    period = posting_date[:7] if len(posting_date) >= 7 else "0000-00"
    account_code = row.get("account_id", "").strip() or row.get("account_code", "").strip()
    if not account_code:
        raise ValueError("account_id / account_code is required")
    return {
        "period": period,
        "account_code": account_code,
        "account_name": row.get("description", "").strip() or "Journal Entry",
        "debit": _safe_float(row.get("debit_amount")),
        "credit": _safe_float(row.get("credit_amount")),
    }


def _map_staff(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps staff CSV → sage_staff_snapshot columns."""
    # Accept multiple possible column name variants for robustness
    staff_id = (
        row.get("staff_id") or row.get("StaffID") or
        row.get("employee_id") or row.get("EmployeeID") or
        row.get("ID") or ""
    ).strip()
    if not staff_id:
        raise ValueError("staff_id / employee_id is required")
    full_name = (
        row.get("full_name") or row.get("FullName") or
        row.get("name") or row.get("Name") or
        row.get("Employee Name") or ""
    ).strip()
    if not full_name:
        raise ValueError("full_name / name is required")
    return {
        "staff_id": staff_id,
        "full_name": full_name,
        "email": (row.get("email") or row.get("Email") or row.get("EmailAddress") or "").strip().lower() or None,
        "department": (row.get("department") or row.get("Department") or row.get("Dept") or "").strip() or None,
        "role": (row.get("role") or row.get("Role") or row.get("Position") or row.get("Title") or row.get("Job Title") or "").strip() or None,
        "status": (row.get("status") or row.get("Status") or "active").strip().lower() or "active",
    }


def _map_gl_detail(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps gl_detail.csv → sage_gl_detail_snapshot columns."""
    account_code = (row.get("account_code") or row.get("account_id") or "").strip()
    if not account_code:
        raise ValueError("account_code / account_id is required")
    return {
        "account_code":    account_code,
        "account_name":    row.get("account_name", "").strip() or None,
        "txn_date":        _safe_date(row.get("txn_date") or row.get("date")),
        "reference":       row.get("reference", "").strip() or None,
        "journal_type":    row.get("journal_type", "").strip() or None,
        "description":     row.get("description", "").strip() or None,
        "debit":           _safe_float(row.get("debit")),
        "credit":          _safe_float(row.get("credit")),
        "running_balance": _safe_float(row.get("running_balance")) if row.get("running_balance", "").strip() else None,
        "source_file":     row.get("source_file", "").strip() or None,
    }


def _map_cash_register(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps cash_register.csv → sage_cash_register_snapshot columns."""
    return {
        "txn_date":        _safe_date(row.get("txn_date") or row.get("date")),
        "trans_no":        row.get("trans_no", "").strip() or None,
        "txn_type":        row.get("txn_type", "").strip() or None,
        "description":     row.get("description", "").strip() or None,
        "reference":       row.get("reference", "").strip() or None,
        "payment_amount":  _safe_float(row.get("payment_amount")),
        "receipt_amount":  _safe_float(row.get("receipt_amount")),
        "running_balance": _safe_float(row.get("running_balance")) if row.get("running_balance", "").strip() else None,
        "source_file":     row.get("source_file", "").strip() or None,
    }


def _map_gl_account_summary(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps gl_account_summary.csv → sage_gl_account_summary_snapshot columns."""
    account_code = (row.get("account_code") or row.get("account_number") or "").strip()
    if not account_code:
        raise ValueError("account_code / account_number is required")
    return {
        "account_code":      account_code,
        "account_name":      row.get("account_name", "").strip() or None,
        "beginning_balance": _safe_float(row.get("beginning_balance")) if row.get("beginning_balance", "").strip() else None,
        "debit_change":      _safe_float(row.get("debit_change")) if row.get("debit_change", "").strip() else None,
        "credit_change":     _safe_float(row.get("credit_change")) if row.get("credit_change", "").strip() else None,
        "net_change":        _safe_float(row.get("net_change")) if row.get("net_change", "").strip() else None,
        "ending_balance":    _safe_float(row.get("ending_balance")) if row.get("ending_balance", "").strip() else None,
    }


def _map_hr_payroll(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps HR payroll CSV → sage_payroll_snapshot columns.

    Supported columns (case-insensitive key lookup):
      employee_id, department, period, salary, overtime_hours, overtime_rate,
      total_gross, net_pay, deductions
    """
    employee_id = (
        row.get("employee_id") or row.get("EmployeeID") or row.get("Employee ID") or
        row.get("emp_id") or ""
    ).strip()
    if not employee_id:
        raise ValueError("employee_id is required")

    def _f(key: str, *aliases: str) -> Optional[float]:
        for k in (key, *aliases):
            v = row.get(k) or row.get(k.title()) or row.get(k.upper())
            if v and str(v).strip():
                try:
                    return float(str(v).replace(",", "").strip())
                except (ValueError, TypeError):
                    continue
        return None

    salary = _f("salary", "Salary", "base_salary", "BaseSalary") or 0.0
    ot_hrs = _f("overtime_hours", "OvertimeHours", "ot_hours") or 0.0
    ot_rate = _f("overtime_rate", "OvertimeRate", "ot_rate") or 0.0
    ot_cost = ot_hrs * ot_rate
    total_gross = _f("total_gross", "TotalGross", "gross_pay") or (salary + ot_cost)
    deductions = _f("deductions", "Deductions", "total_deductions") or 0.0
    net_pay = _f("net_pay", "NetPay", "net") or (total_gross - deductions)

    return {
        "employee_id": employee_id,
        "department": (
            row.get("department") or row.get("Department") or row.get("dept") or ""
        ).strip() or None,
        "period": (
            row.get("period") or row.get("Period") or row.get("pay_period") or ""
        ).strip() or None,
        "salary": salary,
        "overtime_hours": ot_hrs,
        "overtime_rate": ot_rate,
        "total_gross": round(total_gross, 2),
        "deductions": round(deductions, 2),
        "net_pay": round(net_pay, 2),
    }


def _map_item_accounts(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps Sage's Inventory Item List import/export template (ITEM.CSV) ->
    sage_item_accounts. Headers arrive normalised by _norm_header, so
    "G/L COGS/Salary Acct" is g_l_cogs_salary_acct. Feeds the Sage export's
    per-item Sales/Inventory/COGS accounts (routers/sage_export.py)."""
    item_id = (row.get("item_id") or "").strip()
    if not item_id:
        raise ValueError("Item ID is required")

    def _s(key: str) -> Optional[str]:
        return (row.get(key) or "").strip() or None

    return {
        "item_id": item_id,
        "item_description": _s("item_description"),
        "item_class": _s("item_class"),
        "inactive": _safe_bool(row.get("inactive"), default=False),
        "sales_account": _s("g_l_sales_account"),
        "inventory_account": _s("g_l_inventory_account"),
        "cogs_account": _s("g_l_cogs_salary_acct"),
        "costing_method": _s("costing_method"),
        "last_unit_cost": _safe_float(row.get("last_unit_cost")),
        "sales_price_1": _safe_float(row.get("sales_price_1")),
        "stocking_um": _s("stocking_u_m"),
    }


# ---------------------------------------------------------------------------
# Registry: file_type → (target_table, mapper_fn)
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Tuple[str, Callable[[Dict[str, str]], Dict[str, Any]]]] = {
    "chart_of_accounts": ("sage_coa_snapshot", _map_chart_of_accounts),
    "vendors": ("sage_vendors_snapshot", _map_vendors),
    "customers": ("sage_customers_snapshot", _map_customers),
    "customer_sales": ("sage_customer_sales_snapshot", _map_customer_sales),
    "items": ("sage_items_snapshot", _map_items),
    "stock_on_hand": ("sage_inventory_snapshot", _map_stock_on_hand),
    "purchase_orders": ("sage_purchase_orders_snapshot", _map_purchase_orders),
    "sales_invoices": ("sage_ar_snapshot", _map_sales_invoices),
    "sales_invoice_lines": ("sage_invoice_lines_snapshot", _map_invoice_lines),
    "inventory_transactions": ("sage_inv_transactions_snapshot", _map_inventory_transactions),
    "gl_journal_entries": ("sage_gl_snapshot", _map_gl_journal_entries),
    "staff": ("sage_staff_snapshot", _map_staff),
    "hr_payroll": ("sage_payroll_snapshot", _map_hr_payroll),
    "gl_detail": ("sage_gl_detail_snapshot", _map_gl_detail),
    "cash_register": ("sage_cash_register_snapshot", _map_cash_register),
    "gl_account_summary": ("sage_gl_account_summary_snapshot", _map_gl_account_summary),
    "item_accounts": ("sage_item_accounts", _map_item_accounts),
}

# Human-friendly metadata for UI listing
SUPPORTED_TYPES: List[Dict[str, Any]] = [
    {
        "file_type": "chart_of_accounts",
        "label": "Chart of Accounts",
        "description": "Full account code hierarchy (COA). Required columns: account_id, account_code, account_name.",
        "target_table": "sage_coa_snapshot",
        "required_columns": ["account_id", "account_code", "account_name"],
    },
    {
        "file_type": "vendors",
        "label": "Vendors",
        "description": "Supplier master list. Required: vendor_id, vendor_name.",
        "target_table": "sage_vendors_snapshot",
        "required_columns": ["vendor_id", "vendor_name"],
    },
    {
        "file_type": "customers",
        "label": "Customers",
        "description": "Customer master list. Required: customer_id, name.",
        "target_table": "sage_customers_snapshot",
        "required_columns": ["customer_id", "name"],
    },
    {
        "file_type": "items",
        "label": "Product Items",
        "description": "Product/SKU catalogue. Required: item_id, item_name.",
        "target_table": "sage_items_snapshot",
        "required_columns": ["item_id", "item_name"],
    },
    {
        "file_type": "stock_on_hand",
        "label": "Stock on Hand",
        "description": "Current warehouse inventory balances. Required: item_id, quantity_on_hand.",
        "target_table": "sage_inventory_snapshot",
        "required_columns": ["item_id", "quantity_on_hand"],
    },
    {
        "file_type": "purchase_orders",
        "label": "Purchase Orders",
        "description": "Supplier PO history. Required: po_id, po_number.",
        "target_table": "sage_purchase_orders_snapshot",
        "required_columns": ["po_id", "po_number"],
    },
    {
        "file_type": "sales_invoices",
        "label": "Sales Invoices",
        "description": "AR invoice register. Required: invoice_id, customer_id, invoice_date, net_amount, status.",
        "target_table": "sage_ar_snapshot",
        "required_columns": ["invoice_id", "customer_id", "invoice_date", "net_amount", "status"],
    },
    {
        "file_type": "sales_invoice_lines",
        "label": "Sales Invoice Lines",
        "description": "Per-line revenue and margin detail. Required: line_id, invoice_id.",
        "target_table": "sage_invoice_lines_snapshot",
        "required_columns": ["line_id", "invoice_id"],
    },
    {
        "file_type": "inventory_transactions",
        "label": "Inventory Transactions",
        "description": "Stock movement ledger (purchases, sales, transfers, adjustments). Required: transaction_id.",
        "target_table": "sage_inv_transactions_snapshot",
        "required_columns": ["transaction_id"],
    },
    {
        "file_type": "gl_journal_entries",
        "label": "GL Journal Entries",
        "description": "General Ledger double-entry journal. Required: account_id/account_code, debit_amount, credit_amount, posting_date.",
        "target_table": "sage_gl_snapshot",
        "required_columns": ["posting_date", "account_id", "debit_amount", "credit_amount"],
    },
    {
        "file_type": "staff",
        "label": "Staff Registry",
        "description": "Employee / staff master list. Required: staff_id/employee_id, full_name/name.",
        "target_table": "sage_staff_snapshot",
        "required_columns": ["staff_id", "full_name"],
    },
    {
        "file_type": "hr_payroll",
        "label": "HR Payroll",
        "description": "Payroll run data with salary, overtime, deductions, and net pay. Required: employee_id.",
        "target_table": "sage_payroll_snapshot",
        "required_columns": ["employee_id"],
    },
    {
        "file_type": "gl_detail",
        "label": "GL Transactions (Detail)",
        "description": "Transaction-level General Ledger: GL, General Journal, Sales Journal, Cash Receipts, COGS. Required: account_code.",
        "target_table": "sage_gl_detail_snapshot",
        "required_columns": ["account_code"],
    },
    {
        "file_type": "cash_register",
        "label": "Cash Account Register",
        "description": "Cash account transaction register with running balance.",
        "target_table": "sage_cash_register_snapshot",
        "required_columns": ["txn_date"],
    },
    {
        "file_type": "gl_account_summary",
        "label": "GL Account Summary",
        "description": "Per-account beginning and ending balances (Financial Statements export). Required: account_code.",
        "target_table": "sage_gl_account_summary_snapshot",
        "required_columns": ["account_code"],
    },
    {
        "file_type": "item_accounts",
        "label": "Item GL Accounts (for Sage export)",
        "description": "Sage's Inventory Item List template export (ITEM.CSV). Gives each item its Sales/Inventory/COGS accounts so ACE can build Sage Sales Journal imports.",
        "target_table": "sage_item_accounts",
        "required_columns": ["Item ID", "G/L Sales Account", "G/L Inventory Account", "G/L COGS/Salary Acct"],
    },
]

# Cache-tag groups to bust after successful imports
_CACHE_TAGS: Dict[str, List[str]] = {
    "chart_of_accounts": ["finance", "finance_kpis"],
    "vendors": ["finance", "procurement"],
    "customers": ["crm", "finance_kpis", "executive_summary"],
    "items": ["inventory", "finance"],
    "stock_on_hand": ["inventory", "executive", "executive_summary"],
    "purchase_orders": ["procurement", "finance", "finance_kpis"],
    "sales_invoices": ["finance", "finance_kpis", "finance_trend", "executive", "executive_summary"],
    "sales_invoice_lines": ["finance", "finance_kpis"],
    "inventory_transactions": ["inventory", "finance_kpis"],
    "gl_journal_entries": ["finance", "finance_kpis", "finance_trend", "executive", "executive_summary"],
    "staff": ["staff", "executive_summary"],
    "hr_payroll": ["finance", "payroll", "executive_summary"],
    "gl_detail": ["finance", "finance_gl_detail"],
    "cash_register": ["finance", "finance_kpis"],
    "gl_account_summary": ["finance", "finance_kpis", "executive_summary"],
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_SAGE_SNAPSHOT_TABLES = [
    "sage_gl_snapshot", "sage_gl_transactions", "sage_coa_snapshot",
    "sage_customers_snapshot", "sage_vendors_snapshot", "sage_items_snapshot",
    "sage_inventory_snapshot", "sage_ar_snapshot", "sage_ap_snapshot",
    "sage_inv_transactions_snapshot", "sage_invoice_lines_snapshot",
    "sage_purchase_orders_snapshot", "sage_payroll_snapshot", "sage_staff_snapshot",
    "sage_gl_detail_snapshot", "sage_cash_register_snapshot", "sage_gl_account_summary_snapshot",
]


@router.post("/truncate")
def truncate_sage_snapshots(request: Request):
    """Truncate all sage_*_snapshot tables to prepare for a fresh import.

    WARNING: This deletes all imported Sage data from the snapshot tables.
    Application tables (customers, suppliers, opportunities, customer_360,
    reconciliation_tracking) are NOT touched.

    Roles: admin only.
    """
    user = _require_import_role(request)
    roles = set(user.get("roles") or [])
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin role required for truncate")

    from src.db import get_psycopg_dsn
    try:
        import psycopg2
    except ImportError:
        raise HTTPException(status_code=500, detail="psycopg2 not installed in backend")

    table_list = ", ".join(f'public."{t}"' for t in _SAGE_SNAPSHOT_TABLES)
    sql = f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE;"

    try:
        conn = psycopg2.connect(get_psycopg_dsn())
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.close()
    except Exception as exc:
        logger.error(f"truncate_sage_snapshots failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Truncate failed: {exc}")

    logger.info(f"truncate_sage_snapshots: cleared {len(_SAGE_SNAPSHOT_TABLES)} tables by {user.get('sub','?')}")
    return {"status": "ok", "tables_truncated": _SAGE_SNAPSHOT_TABLES}


@router.get("/supported")
def list_supported_types():
    """List all supported CSV file types with their target tables and required columns."""
    return {"file_types": SUPPORTED_TYPES}


@router.get("/freshness")
def import_freshness(request: Request):
    """Return the most recent import timestamp for the daily-refresh tables.

    Powers the "AR data last updated: N days ago" banner on the Sage Import
    page — no auth-role gate beyond a valid JWT, since this is just a
    read-only staleness indicator.
    """
    verify_jwt(request)
    tables = {
        "sales_invoices": "sage_ar_snapshot",
        "sales_invoice_lines": "sage_invoice_lines_snapshot",
    }
    result: Dict[str, Optional[str]] = {}
    for file_type, table in tables.items():
        try:
            resp = (
                db.table(table)
                .select("imported_at")
                .order("imported_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            result[file_type] = rows[0]["imported_at"] if rows else None
        except Exception as exc:
            logger.warning(f"import_freshness: query failed for {table}: {exc}")
            result[file_type] = None
    return {"last_imported": result}


@router.get("/jobs")
def list_import_jobs(request: Request, limit: int = 20):
    """Return the most recent CSV import jobs (newest first).

    Roles: admin, finance, management
    """
    _require_import_role(request)
    try:
        resp = (
            db.table("placeware_import_jobs")
            .select("id,domain,batch_id,status,row_count,imported_at,finished_at,metadata")
            .ilike("metadata->>'source'", "%csv_upload%")
            .order("imported_at", desc=True)
            .limit(max(1, min(limit, 100)))
            .execute()
        )
        return {"jobs": resp.data or [], "count": len(resp.data or [])}
    except Exception as exc:
        logger.warning(f"list_import_jobs: DB query failed: {exc}")
        return {"jobs": [], "count": 0}


@router.post("/csv")
async def upload_csv(
    request: Request,
    file_type: str = Form(..., description="One of the supported file_type slugs, e.g. 'sales_invoices'"),
    file: UploadFile = File(..., description="UTF-8 encoded CSV file"),
    company_id: Optional[str] = Form(None, description="Company tag for multi-company setups, e.g. 'PlacewareNig'"),
):
    # ── 0. Auth ──────────────────────────────────────────────────────────────
    user = _require_import_role(request)   # ← capture return value

    # ── 1. Validate file_type ────────────────────────────────────────────────
    file_type = file_type.strip().lower()
    if file_type not in _REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown file_type '{file_type}'. "
                f"Supported: {sorted(_REGISTRY.keys())}"
            ),
        )
    target_table, mapper = _REGISTRY[file_type]

    # ── 2. Validate MIME / filename ──────────────────────────────────────────
    filename = (file.filename or "upload.csv").lower()
    is_xlsx = filename.endswith(".xlsx")
    if not (filename.endswith(".csv") or is_xlsx):
        raise HTTPException(
            status_code=415,
            detail="Only .csv or .xlsx files are accepted",
        )

    # ── 3. Read file ─────────────────────────────────────────────────────────
    raw_bytes = await file.read()
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw_bytes) > 20 * 1024 * 1024:  # 20 MB safety cap
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")

    # ── 4. Parse into row dicts (CSV and XLSX converge on the same shape) ────
    if is_xlsx:
        try:
            raw_rows = _read_xlsx_rows(raw_bytes)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot parse .xlsx file: {exc}") from exc
        if not raw_rows:
            raise HTTPException(status_code=400, detail="XLSX has a header but no data rows")
        row_iter = enumerate(raw_rows, start=2)  # row 1 is the header row
    else:
        try:
            content = raw_bytes.decode("utf-8-sig")  # strips BOM if present
        except UnicodeDecodeError:
            try:
                content = raw_bytes.decode("latin-1")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Cannot decode file: {exc}") from exc

        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            raise HTTPException(status_code=400, detail="CSV has no header row")
        # Normalise headers so Sage 50 exports like "Amnt Remaining" or
        # "Invoice/CM #" match the mapper's snake_case keys.
        reader.fieldnames = [_norm_header(h) for h in reader.fieldnames]
        row_iter = ((n, dict(r)) for n, r in enumerate(reader, start=2))

    mapped_rows: List[Dict[str, Any]] = []
    validation_errors: List[Dict[str, Any]] = []

    for line_num, raw_row in row_iter:
        try:
            raw_dict = dict(raw_row)
            # Inject company_id from Form param so mappers can pick it up
            if company_id and "company_id" not in raw_dict:
                raw_dict["company_id"] = company_id
            mapped = mapper(raw_dict)
            # Ensure company_id is set on item/stock rows even if mapper didn't handle it
            if company_id and file_type in ("items", "stock_on_hand") and not mapped.get("company_id"):
                mapped["company_id"] = company_id
            mapped_rows.append(mapped)
        except (ValueError, KeyError) as exc:
            validation_errors.append({"line": line_num, "error": str(exc)})
            if len(validation_errors) >= 50:
                break  # cap error collection; likely a structural issue

    total_parsed = len(mapped_rows)

    if total_parsed == 0 and not validation_errors:
        raise HTTPException(status_code=400, detail="File has a header but no data rows")

    if validation_errors and total_parsed == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "All rows failed validation",
                "errors": validation_errors,
            },
        )

    # ── 5. Persist batch ─────────────────────────────────────────────────────
    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()
    actor = user.get("sub", "unknown")

    job_id = create_import_job(
        domain="sage",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={
            "source": "csv_upload",
            "file_type": file_type,
            "original_filename": file.filename,
            "target_table": target_table,
            "actor": actor,
            "validation_error_count": len(validation_errors),
        },
        status="running",
    )

    rows_inserted = 0
    insert_error: Optional[str] = None
    try:
        rows_inserted = insert_snapshot(target_table, batch_id, imported_at, mapped_rows)
    except Exception as exc:
        insert_error = str(exc)
        logger.error(
            f"upload_csv: insert_snapshot failed "
            f"file_type={file_type} table={target_table} batch={batch_id}: {exc}"
        )

    # ── 6. Update job status ─────────────────────────────────────────────────
    final_status = "succeeded" if not insert_error else "failed"
    try:
        db.table("placeware_import_jobs").update({
            "status": final_status,
            "row_count": rows_inserted,
            "finished_at": datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat(),
        }).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning(f"upload_csv: job status update failed: {exc}")

    # ── 6a. Auto-populate placeware_invoices on AR import ────────────────────
    if file_type == "sales_invoices" and rows_inserted > 0:
        try:
            _sync_placeware_invoices(batch_id)
            logger.info(f"upload_csv: synced placeware_invoices from batch={batch_id}")
        except Exception as exc:
            logger.warning(f"upload_csv: placeware_invoices sync failed (non-fatal): {exc}")

    # ── 6a-ii. Prune old batches for recurring-upload tables ─────────────────
    # sales_invoices / sales_invoice_lines are the daily-refresh targets — cap
    # history so the tables don't grow unbounded across many upload cycles.
    if file_type in ("sales_invoices", "sales_invoice_lines") and rows_inserted > 0:
        _prune_old_batches(target_table, keep=14)
    if file_type == "item_accounts" and rows_inserted > 0:
        _prune_old_batches(target_table, keep=3)

    # ── 6b. Mirror purchase orders into AP snapshot ───────────────────────────
    # AP data originates from purchase_orders.csv — open POs represent payables.
    if file_type == "purchase_orders" and rows_inserted > 0:
        try:
            ap_rows: List[Dict[str, Any]] = []
            for po in mapped_rows:
                po_status = str(po.get("status") or "").lower()
                amount = float(po.get("total_amount") or po.get("net_amount") or 0)
                # Outstanding balance: full amount if open/pending, zero if closed/received
                balance = amount if po_status in ("open", "pending", "partial") else 0.0
                ap_rows.append({
                    "bill_id": po.get("po_id", ""),
                    "vendor_id": po.get("vendor_id") or "unknown",
                    "date": po.get("order_date") or imported_at[:10],
                    "due_date": po.get("expected_delivery_date"),
                    "amount": amount,
                    "balance": balance,
                    "status": po_status or "open",
                })
            if ap_rows:
                insert_snapshot("sage_ap_snapshot", batch_id, imported_at, ap_rows)
                logger.info(f"upload_csv: mirrored {len(ap_rows)} rows into sage_ap_snapshot batch={batch_id}")
        except Exception as exc:
            logger.warning(f"upload_csv: AP mirror failed (non-fatal): {exc}")

    # ── 6c. Upsert vendors into suppliers table ─────────────────────────────
    # suppliers is the authoritative table for the Suppliers dashboard.
    # CSV columns are upserted (keyed on external_vendor_id); agent-owned metric
    # columns (reliability_score, avg_delay_days, etc.) are never touched here.
    if file_type == "vendors" and rows_inserted > 0:
        try:
            supplier_rows: List[Dict[str, Any]] = [
                {
                    "external_vendor_id": v.get("vendor_id", ""),
                    "name": v.get("vendor_name") or "Unknown",
                    "contact_name": v.get("contact_name"),
                    "contact_email": v.get("email"),
                    "phone": v.get("phone"),
                    "address": v.get("address"),
                    "payment_terms": v.get("payment_terms"),
                    "tax_id": v.get("tax_id"),
                    "bank_details": v.get("bank_details"),
                    "current_balance": v.get("current_balance"),
                    "status": v.get("status") or "active",
                }
                for v in mapped_rows
                if v.get("vendor_id", "").strip()
            ]
            if supplier_rows:
                db.table("suppliers").upsert(
                    supplier_rows, on_conflict="external_vendor_id"
                ).execute()
                logger.info(
                    f"upload_csv: upserted {len(supplier_rows)} rows into "
                    f"suppliers table batch={batch_id}"
                )
        except Exception as exc:
            logger.warning(f"upload_csv: suppliers upsert failed (non-fatal): {exc}")

    # ── 7. Bust caches ───────────────────────────────────────────────────────
    # Always invalidate — even on failure — so stale zero-values don't persist
    invalidate_cache_tags(*_CACHE_TAGS.get(file_type, []))
    if rows_inserted > 0:
        clear_cache()  # full flush — guarantees all in-process TTL entries are cleared

    # ── 8. Audit ─────────────────────────────────────────────────────────────
    audit_event(
        "sage_csv_import",
        {
            "file_type": file_type,
            "target_table": target_table,
            "original_filename": file.filename,
            "batch_id": batch_id,
            "rows_inserted": rows_inserted,
            "validation_errors": len(validation_errors),
            "actor": actor,
            "status": final_status,
        },
        event_class="data_ingestion",
        action="csv_upload",
        outcome=final_status,
        actor_id=actor,
    )

    logger.info(
        f"upload_csv: file_type={file_type} table={target_table} "
        f"inserted={rows_inserted} errors={len(validation_errors)} "
        f"batch={batch_id} actor={actor}"
    )

    # ── 9. Build response ────────────────────────────────────────────────────
    response: Dict[str, Any] = {
        "file_type": file_type,
        "target_table": target_table,
        "batch_id": batch_id,
        "rows_parsed": total_parsed,
        "rows_inserted": rows_inserted,
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors[:50],
        "status": final_status,
        "imported_at": imported_at,
    }

    if insert_error:
        response["insert_error"] = insert_error
        raise HTTPException(status_code=500, detail=response)

    return JSONResponse(status_code=200, content=response)


# ---------------------------------------------------------------------------
# Batch ZIP upload  POST /sage/import/batch
# ---------------------------------------------------------------------------
# Accepts a ZIP produced by sage50_extractor.py (or assembled manually).
# Each CSV inside the ZIP is matched to a file_type by filename stem.
# e.g.  customers.csv         → file_type "customers"
#       sales_invoices.csv    → file_type "sales_invoices"
#       gl_journal_entries.csv → file_type "gl_journal_entries"
# All recognised files are imported in a single shared batch_id so they
# can be traced together.  Unrecognised files are skipped (logged).
# ---------------------------------------------------------------------------

# Filename stem → file_type mapping (case-insensitive).
# The extractor uses exact file_type slugs as filenames, but we also
# accept common alternatives for hand-assembled ZIPs.
_FILENAME_ALIASES: Dict[str, str] = {
    # canonical names (extractor output)
    "chart_of_accounts": "chart_of_accounts",
    "vendors": "vendors",
    "customers": "customers",
    "items": "items",
    "stock_on_hand": "stock_on_hand",
    "purchase_orders": "purchase_orders",
    "sales_invoices": "sales_invoices",
    "sales_invoice_lines": "sales_invoice_lines",
    "inventory_transactions": "inventory_transactions",
    "gl_journal_entries": "gl_journal_entries",
    "staff": "staff",
    "hr_payroll": "hr_payroll",
    # common Sage export name variants
    "customer": "customers",
    "vendor": "vendors",
    "supplier": "vendors",
    "suppliers": "vendors",
    "inventory": "stock_on_hand",
    "stock": "stock_on_hand",
    "invoice": "sales_invoices",
    "invoices": "sales_invoices",
    "ar_invoices": "sales_invoices",
    "ar_invoice": "sales_invoices",
    "invoice_lines": "sales_invoice_lines",
    "invoice_items": "sales_invoice_lines",
    "po": "purchase_orders",
    "purchase_order": "purchase_orders",
    "gl": "gl_journal_entries",
    "journal": "gl_journal_entries",
    "journal_entries": "gl_journal_entries",
    "general_ledger": "gl_journal_entries",
    "coa": "chart_of_accounts",
    "accounts": "chart_of_accounts",
    "employee": "staff",
    "employees": "staff",
    "payroll": "hr_payroll",
    "gl_detail": "gl_detail",
    "cash_register": "cash_register",
    "gl_account_summary": "gl_account_summary",
    "customer_sales": "customer_sales",
}


def _stem(filename: str) -> str:
    """Return lowercase stem of a filename (no directory, no extension)."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]  # strip any path
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem.lower().replace(" ", "_").replace("-", "_")


@router.post("/batch")
async def upload_batch_zip(
    request: Request,
    file: UploadFile = File(..., description="ZIP archive from sage50_extractor.py or hand-assembled"),
):
    """Import a ZIP bundle of Sage 50 CSV exports in one request.

    The ZIP should contain one CSV per data entity, named by file_type slug
    (e.g. customers.csv, sales_invoices.csv).  All CSVs share a single
    batch_id so the full export is traceable as one ingestion event.

    Roles: admin, finance, management
    """
    user = _require_import_role(request)
    actor = user.get("sub", "unknown")

    # -- validate upload
    filename = (file.filename or "upload.zip").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=415, detail="Only .zip files are accepted")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw_bytes) > 200 * 1024 * 1024:  # 200 MB cap
        raise HTTPException(status_code=413, detail="ZIP exceeds 200 MB limit")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="File is not a valid ZIP archive")

    # -- shared batch context
    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

    job_id = create_import_job(
        domain="sage",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={
            "source": "batch_zip_upload",
            "original_filename": file.filename,
            "actor": actor,
        },
        status="running",
    )

    # -- process each CSV inside the ZIP
    results: List[Dict[str, Any]] = []
    all_cache_tags: set = set()
    total_inserted = 0
    total_errors = 0

    for zip_entry in zf.namelist():
        # skip directories and the manifest
        if zip_entry.endswith("/") or _stem(zip_entry) == "manifest":
            continue
        if not zip_entry.lower().endswith(".csv"):
            continue

        file_type = _FILENAME_ALIASES.get(_stem(zip_entry))
        if file_type is None:
            logger.info(f"upload_batch_zip: skipping unrecognised file '{zip_entry}'")
            results.append({"file": zip_entry, "status": "skipped", "reason": "unrecognised filename"})
            continue

        if file_type not in _REGISTRY:
            results.append({"file": zip_entry, "status": "skipped", "reason": f"no mapper for {file_type}"})
            continue

        target_table, mapper = _REGISTRY[file_type]

        try:
            raw_csv_bytes = zf.read(zip_entry)
        except Exception as exc:
            results.append({"file": zip_entry, "file_type": file_type, "status": "error", "reason": str(exc)})
            total_errors += 1
            continue

        # decode
        try:
            content = raw_csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                content = raw_csv_bytes.decode("latin-1")
            except UnicodeDecodeError as exc:
                results.append({"file": zip_entry, "file_type": file_type, "status": "error", "reason": f"decode error: {exc}"})
                total_errors += 1
                continue

        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            results.append({"file": zip_entry, "file_type": file_type, "status": "skipped", "reason": "no header row"})
            continue
        reader.fieldnames = [
            h.strip().lower().replace(" ", "_").replace("-", "_")
            for h in reader.fieldnames
        ]

        mapped_rows: List[Dict[str, Any]] = []
        validation_errors: List[Dict[str, Any]] = []

        for line_num, raw_row in enumerate(reader, start=2):
            try:
                mapped_rows.append(mapper(dict(raw_row)))
            except (ValueError, KeyError) as exc:
                validation_errors.append({"line": line_num, "error": str(exc)})
                if len(validation_errors) >= 50:
                    break

        if not mapped_rows:
            results.append({
                "file": zip_entry, "file_type": file_type,
                "status": "skipped", "reason": "no valid rows after mapping",
                "validation_errors": validation_errors[:10],
            })
            continue

        # insert snapshot
        rows_inserted = 0
        insert_error: Optional[str] = None
        try:
            rows_inserted = insert_snapshot(target_table, batch_id, imported_at, mapped_rows)
            total_inserted += rows_inserted
        except Exception as exc:
            insert_error = str(exc)
            total_errors += 1
            logger.error(f"upload_batch_zip: insert failed for {file_type}: {exc}")

        # AP mirror for purchase orders
        if file_type == "purchase_orders" and rows_inserted > 0:
            try:
                ap_rows: List[Dict[str, Any]] = []
                for po in mapped_rows:
                    po_status = str(po.get("status") or "").lower()
                    amount = float(po.get("total_amount") or po.get("net_amount") or 0)
                    balance = amount if po_status in ("open", "pending", "partial") else 0.0
                    ap_rows.append({
                        "bill_id": po.get("po_id", ""),
                        "vendor_id": po.get("vendor_id") or "unknown",
                        "date": po.get("order_date") or imported_at[:10],
                        "due_date": po.get("expected_delivery_date"),
                        "amount": amount,
                        "balance": balance,
                        "status": po_status or "open",
                    })
                if ap_rows:
                    insert_snapshot("sage_ap_snapshot", batch_id, imported_at, ap_rows)
            except Exception as exc:
                logger.warning(f"upload_batch_zip: AP mirror failed (non-fatal): {exc}")

        # suppliers upsert for vendors
        if file_type == "vendors" and rows_inserted > 0:
            try:
                supplier_rows = [
                    {
                        "external_vendor_id": v.get("vendor_id", ""),
                        "name": v.get("vendor_name") or "Unknown",
                        "contact_name": v.get("contact_name"),
                        "contact_email": v.get("email"),
                        "phone": v.get("phone"),
                        "address": v.get("address"),
                        "payment_terms": v.get("payment_terms"),
                        "tax_id": v.get("tax_id"),
                        "bank_details": v.get("bank_details"),
                        "current_balance": v.get("current_balance"),
                        "status": v.get("status") or "active",
                    }
                    for v in mapped_rows if v.get("vendor_id", "").strip()
                ]
                if supplier_rows:
                    db.table("suppliers").upsert(supplier_rows, on_conflict="external_vendor_id").execute()
            except Exception as exc:
                logger.warning(f"upload_batch_zip: suppliers upsert failed (non-fatal): {exc}")

        for tag in _CACHE_TAGS.get(file_type, []):
            all_cache_tags.add(tag)

        results.append({
            "file": zip_entry,
            "file_type": file_type,
            "target_table": target_table,
            "rows_inserted": rows_inserted,
            "validation_error_count": len(validation_errors),
            "status": "succeeded" if not insert_error else "failed",
            **({"insert_error": insert_error} if insert_error else {}),
        })

    zf.close()

    # -- finalise job record
    final_status = "succeeded" if total_errors == 0 else ("partial_success" if total_inserted > 0 else "failed")
    try:
        db.table("placeware_import_jobs").update({
            "status": final_status,
            "row_count": total_inserted,
            "finished_at": datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat(),
            "counts": {r["file_type"]: r.get("rows_inserted", 0) for r in results if "file_type" in r},
        }).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning(f"upload_batch_zip: job status update failed: {exc}")

    # -- bust caches
    if all_cache_tags:
        invalidate_cache_tags(*all_cache_tags)
    if total_inserted > 0:
        clear_cache()

    # -- audit
    audit_event(
        "sage_batch_import",
        {
            "original_filename": file.filename,
            "batch_id": batch_id,
            "datasets": [r.get("file_type") for r in results if r.get("status") == "succeeded"],
            "total_rows_inserted": total_inserted,
            "actor": actor,
            "status": final_status,
        },
        event_class="data_ingestion",
        action="batch_zip_upload",
        outcome=final_status,
        actor_id=actor,
    )

    logger.info(
        f"upload_batch_zip: batch={batch_id} status={final_status} "
        f"inserted={total_inserted} errors={total_errors} actor={actor}"
    )

    return JSONResponse(status_code=200, content={
        "batch_id": batch_id,
        "status": final_status,
        "total_rows_inserted": total_inserted,
        "datasets": results,
        "imported_at": imported_at,
    })
