"""
sage_csv_import.py — POST /sage/import/csv

Accepts multipart CSV file uploads for each of the 10 PlacewareBot
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
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from src.cache import invalidate_cache_tags
from src.db import audit_event, create_import_job, db, insert_snapshot
from src.middleware import verify_jwt, require_role

logger = logging.getLogger("sage_csv_import")

router = APIRouter(prefix="/sage/import", tags=["sage-import"])

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


# -- individual mapper functions --------------------------------------------

def _map_chart_of_accounts(row: Dict[str, str]) -> Dict[str, Any]:
    account_id = row.get("account_id", "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    return {
        "account_id": account_id,
        "account_code": row.get("account_code", "").strip() or account_id,
        "account_name": row.get("account_name", "").strip() or "Unknown",
        "account_type": row.get("account_type", "").strip() or None,
        "parent_account_id": row.get("parent_account_id", "").strip() or None,
        "description": row.get("description", "").strip() or None,
        "is_active": _safe_bool(row.get("is_active"), default=True),
    }


def _map_vendors(row: Dict[str, str]) -> Dict[str, Any]:
    vendor_id = row.get("vendor_id", "").strip()
    if not vendor_id:
        raise ValueError("vendor_id is required")
    return {
        "vendor_id": vendor_id,
        "vendor_name": row.get("vendor_name", "").strip() or "Unknown",
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
    customer_id = row.get("customer_id", "").strip()
    if not customer_id:
        raise ValueError("customer_id is required")
    return {
        "customer_id": customer_id,
        "name": row.get("name", "").strip() or "Unknown",
        "email": row.get("email", "").strip() or None,
        "phone": row.get("phone", "").strip() or None,
        "status": row.get("status", "active").strip() or "active",
    }


def _map_items(row: Dict[str, str]) -> Dict[str, Any]:
    item_id = row.get("item_id", "").strip()
    if not item_id:
        raise ValueError("item_id is required")
    return {
        "item_id": item_id,
        "item_name": row.get("item_name", "").strip() or "Unknown",
        "category": row.get("category", "").strip() or None,
        "unit": row.get("unit", "").strip() or None,
        "cost_price": _safe_float(row.get("cost_price")),
        "selling_price": _safe_float(row.get("selling_price")),
        "vat_category": row.get("vat_category", "").strip() or None,
        "reorder_level": _safe_float(row.get("reorder_level")),
        "preferred_vendor_id": row.get("preferred_vendor_id", "").strip() or None,
        "is_active": _safe_bool(row.get("is_active"), default=True),
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
            or row.get("description", "").strip()
            or item_id
        ),
        # Support both Sage Classic (quantity_on_hand) and Sage 200 (quantity_available)
        "quantity": _safe_float(row.get("quantity_on_hand") or row.get("quantity_available")),
        "unit_cost": _safe_float(row.get("unit_cost") or row.get("average_cost")),
        "valuation": _safe_float(row.get("total_value") or row.get("stock_value")),
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
        "status": row.get("status", "open").strip() or "open",
        "warehouse_id": row.get("warehouse_id", "").strip() or None,
        "created_by": row.get("created_by", "").strip() or None,
    }


def _map_sales_invoices(row: Dict[str, str]) -> Dict[str, Any]:
    """Maps sales_invoices.csv → sage_ar_snapshot columns."""
    invoice_id = row.get("invoice_id", "").strip()
    customer_id = row.get("customer_id", "").strip()
    if not invoice_id:
        raise ValueError("invoice_id is required")
    if not customer_id:
        raise ValueError("customer_id is required")
    raw_date = _safe_date(row.get("invoice_date")) or datetime.date.today().isoformat()
    net_amount = _safe_float(row.get("net_amount"))
    status = row.get("status", "unpaid").strip().lower()
    # AR balance: for paid invoices it's 0; for unpaid/partial it's net_amount
    balance = 0.0 if status == "paid" else net_amount
    return {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "date": raw_date,
        "due_date": _safe_date(row.get("due_date")),
        "amount": net_amount,
        "balance": balance,
        "status": status,
    }


def _map_invoice_lines(row: Dict[str, str]) -> Dict[str, Any]:
    line_id = row.get("line_id", "").strip()
    invoice_id = row.get("invoice_id", "").strip()
    if not line_id:
        raise ValueError("line_id is required")
    if not invoice_id:
        raise ValueError("invoice_id is required")
    return {
        "line_id": line_id,
        "invoice_id": invoice_id,
        "item_id": row.get("item_id", "").strip() or None,
        "quantity": _safe_float(row.get("quantity")),
        "unit_price": _safe_float(row.get("unit_price")),
        "discount": _safe_float(row.get("discount")),
        "line_total": _safe_float(row.get("line_total")),
        "cost_at_sale": _safe_float(row.get("cost_at_sale")),
        "gross_profit": _safe_float(row.get("gross_profit")),
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


# ---------------------------------------------------------------------------
# Registry: file_type → (target_table, mapper_fn)
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Tuple[str, Callable[[Dict[str, str]], Dict[str, Any]]]] = {
    "chart_of_accounts": ("sage_coa_snapshot", _map_chart_of_accounts),
    "vendors": ("sage_vendors_snapshot", _map_vendors),
    "customers": ("sage_customers_snapshot", _map_customers),
    "items": ("sage_items_snapshot", _map_items),
    "stock_on_hand": ("sage_inventory_snapshot", _map_stock_on_hand),
    "purchase_orders": ("sage_purchase_orders_snapshot", _map_purchase_orders),
    "sales_invoices": ("sage_ar_snapshot", _map_sales_invoices),
    "sales_invoice_lines": ("sage_invoice_lines_snapshot", _map_invoice_lines),
    "inventory_transactions": ("sage_inv_transactions_snapshot", _map_inventory_transactions),
    "gl_journal_entries": ("sage_gl_snapshot", _map_gl_journal_entries),
    "staff": ("sage_staff_snapshot", _map_staff),
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
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/supported")
async def list_supported_types():
    """List all supported CSV file types with their target tables and required columns."""
    return {"file_types": SUPPORTED_TYPES}


@router.get("/jobs")
async def list_import_jobs(request: Request, limit: int = 20):
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
    if not filename.endswith(".csv"):
        raise HTTPException(
            status_code=415,
            detail="Only .csv files are accepted",
        )

    # ── 3. Read & decode file ────────────────────────────────────────────────
    raw_bytes = await file.read()
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw_bytes) > 20 * 1024 * 1024:  # 20 MB safety cap
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")

    try:
        content = raw_bytes.decode("utf-8-sig")  # strips BOM if present
    except UnicodeDecodeError:
        try:
            content = raw_bytes.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Cannot decode file: {exc}") from exc

    # ── 4. Parse CSV ─────────────────────────────────────────────────────────
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV has no header row")

    mapped_rows: List[Dict[str, Any]] = []
    validation_errors: List[Dict[str, Any]] = []

    for line_num, raw_row in enumerate(reader, start=2):  # line 1 is header
        try:
            mapped = mapper(dict(raw_row))
            mapped_rows.append(mapped)
        except (ValueError, KeyError) as exc:
            validation_errors.append({"line": line_num, "error": str(exc)})
            if len(validation_errors) >= 50:
                break  # cap error collection; likely a structural issue

    total_parsed = len(mapped_rows)

    if total_parsed == 0 and not validation_errors:
        raise HTTPException(status_code=400, detail="CSV has a header but no data rows")

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

    # ── 7. Bust caches ───────────────────────────────────────────────────────
    # Always invalidate — even on failure — so stale zero-values don't persist
    invalidate_cache_tags(*_CACHE_TAGS.get(file_type, []))

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
