"""assimilate_from_csv.py — Ingest ODBC-extracted Sage GL/inventory CSVs into Synbot.

This is the companion script to sage50/psql_extract_admin.ps1.  Run that
script first (as Administrator) to produce CSVs in sage50/extracted/, then
run this script to push those CSVs into the backend snapshot tables.

Usage
-----
    # Preview counts without writing to the DB
    python assimilate_from_csv.py --dry-run

    # Full ingest
    python assimilate_from_csv.py

    # Override CSV folder location
    python assimilate_from_csv.py --csv-dir path/to/extracted

Column mapping
--------------
Pervasive ODBC returns the column names defined in FILE.DDF / FIELD.DDF.
We don't know the exact names until the admin script runs, so every mapper
accepts a wide list of name variants.  If a column cannot be mapped, the
script prints the actual CSV headers so you can extend the mapper below.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# =============================================================================
# CONFIG
# =============================================================================

BACKEND_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@placeware.com"
ADMIN_PASS  = "pware1234"

# CSV files produced by psql_extract_admin.ps1
_DEFAULT_CSV_DIR = os.path.join(_HERE, "sage50", "extracted")

# =============================================================================
# HELPERS
# =============================================================================

def _get(row: Dict[str, str], *keys: str) -> str:
    """Return first non-empty value from row matching any of the given keys."""
    for k in keys:
        v = row.get(k, "")
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _safe_float(v: str) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _safe_date(v: str) -> str:
    """Normalise various Sage date formats to ISO YYYY-MM-DD or empty."""
    v = str(v).strip()
    if not v:
        return ""
    # Already ISO
    if len(v) == 10 and v[4] == "-":
        return v
    # YYYYMMDD
    if len(v) == 8 and v.isdigit():
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    # MM/DD/YY or MM/DD/YYYY (Sage US format)
    parts = v.replace("-", "/").split("/")
    if len(parts) == 3:
        m, d, y = parts
        if len(y) == 2:
            y = "20" + y
        try:
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except ValueError:
            pass
    return ""


# =============================================================================
# PER-TABLE MAPPERS
# Each mapper receives one CSV row (dict of str->str) and returns a
# backend-ready dict or raises ValueError to skip the row.
# =============================================================================

def _map_gl_journal(row: Dict[str, str], table: str) -> Optional[Dict[str, Any]]:
    """Map JrnlHdr or JrnlRow row → gl_journal_entries entity format.

    Backend expects: posting_date, account_id, description, debit_amount, credit_amount
    """
    # --- date ---
    date_raw = _get(
        row,
        "PostingDate", "postingdate", "posting_date",
        "PeriodDate", "perioddate", "Date", "date",
        "JournalDate", "journaldate", "TransactionDate",
    )
    posting_date = _safe_date(date_raw)

    # --- account code ---
    account_id = _get(
        row,
        "AccountRefNo", "AccountRefNumber", "AccountCode", "account_code",
        "AccountKey", "GLAccount", "GlAccountId", "AccountID", "account_id",
        "ChartKey", "ChartNo",
    )

    # For JrnlHdr rows (no account), use the reference / entry number as a
    # synthetic account_id so the row isn't silently dropped.
    if not account_id:
        account_id = _get(
            row,
            "JrnlKey", "JournalKey", "JournalEntryNo", "EntryNo",
            "ReferenceNo", "ReferenceNumber", "Reference", "Ref",
        )
    if not account_id:
        return None

    # --- description ---
    description = _get(
        row,
        "Description", "description", "Memo", "memo",
        "RowDescription", "RowDesc", "JournalDesc",
        "Reference", "ReferenceNumber",
    )

    # --- amounts ---
    # Some Sage versions store a signed Amount; others split to Debit/Credit.
    debit  = _safe_float(_get(row, "DebitAmount",  "Debit",  "debit_amount",  "debit"))
    credit = _safe_float(_get(row, "CreditAmount", "Credit", "credit_amount", "credit"))

    if debit == 0.0 and credit == 0.0:
        raw_amount_str = _get(
            row,
            "Amount", "amount", "NetAmount", "net_amount",
            "LineAmount", "lineamount",
        )
        if raw_amount_str:
            amt = _safe_float(raw_amount_str)
            if amt >= 0:
                debit = amt
            else:
                credit = -amt

    # Skip rows with no monetary value (e.g. JrnlHdr header-only rows)
    if debit == 0.0 and credit == 0.0:
        return None

    return {
        "posting_date":  posting_date,
        "account_id":    account_id,
        "description":   description or "Journal Entry",
        "debit_amount":  round(debit, 2),
        "credit_amount": round(credit, 2),
    }


def _map_invcost(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Map InventoryCosts row → inventory_transactions entity format.

    Backend expects: transaction_id, item_id, transaction_type,
                     quantity_in, quantity_out, unit_cost, transaction_date
    """
    txn_id = _get(
        row,
        "CostRecordNo", "CostRecordNumber", "RecordNo", "RecordNumber",
        "TransactionID", "transaction_id", "CostKey", "InvCostKey",
    )
    # Fall back to a row counter — caller will assign if txn_id is empty
    if not txn_id:
        return None

    item_id = _get(
        row,
        "ItemCode", "ItemID", "item_id", "ItemKey",
        "StockCode", "PartNumber", "ProductCode",
    )

    txn_type = _get(
        row,
        "TransactionType", "transaction_type", "CostType", "Type", "type",
        "TxnType",
    ) or "adjustment"

    qty_in  = _safe_float(_get(row, "QuantityIn",  "quantity_in",  "QtyIn",  "ReceivedQty"))
    qty_out = _safe_float(_get(row, "QuantityOut", "quantity_out", "QtyOut", "IssuedQty"))

    # Sage may store a signed Quantity: positive=in, negative=out
    if qty_in == 0.0 and qty_out == 0.0:
        qty_raw = _safe_float(_get(row, "Quantity", "quantity", "Qty", "qty"))
        if qty_raw >= 0:
            qty_in = qty_raw
        else:
            qty_out = -qty_raw

    unit_cost = _safe_float(_get(
        row,
        "UnitCost", "unit_cost", "CostPerUnit", "AverageCost", "Cost",
    ))
    txn_date = _safe_date(_get(
        row,
        "TransactionDate", "transaction_date", "Date", "date",
        "PostingDate", "CostDate",
    ))

    return {
        "transaction_id":   txn_id,
        "item_id":          item_id or None,
        "transaction_type": txn_type,
        "quantity_in":      round(qty_in, 4),
        "quantity_out":     round(qty_out, 4),
        "unit_cost":        round(unit_cost, 4),
        "transaction_date": txn_date or None,
        "reference_number": _get(row, "ReferenceNo", "Reference", "InvNo") or None,
    }


def _map_sales_invoice(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Map StoredTransHeaders (STXHDR) row → sales_invoices entity format."""
    inv_id = _get(
        row,
        "InvoiceNo", "InvoiceNumber", "invoice_id", "InvoiceID",
        "InvoiceKey", "STXKey", "TransNo", "TransNumber",
    )
    if not inv_id:
        return None

    customer_id = _get(
        row,
        "CustomerID", "customer_id", "CustCode", "CustID",
        "AccountCode", "ClientCode",
    )
    inv_date = _safe_date(_get(
        row,
        "InvoiceDate", "invoice_date", "Date", "date",
        "PostingDate", "TransDate",
    ))
    due_date = _safe_date(_get(row, "DueDate", "due_date", "PaymentDueDate"))
    net = _safe_float(_get(row, "NetAmount", "net_amount", "Amount", "SubTotal", "InvoiceTotal"))
    tax = _safe_float(_get(row, "TaxAmount", "tax_amount", "VATAmount", "TaxTotal"))
    status = _get(row, "Status", "status", "InvoiceStatus") or "open"

    return {
        "invoice_id":   inv_id,
        "customer_id":  customer_id or None,
        "invoice_date": inv_date or None,
        "due_date":     due_date or None,
        "net_amount":   round(net, 2),
        "tax_amount":   round(tax, 2),
        "status":       status.lower(),
    }


def _map_sales_line(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Map StoredTransRows (STXROW) row → sales_invoice_lines entity format."""
    line_id = _get(
        row,
        "RowKey", "LineKey", "LineID", "line_id",
        "STXRowKey", "LineNo", "RowNo",
    )
    inv_id = _get(
        row,
        "InvoiceNo", "InvoiceKey", "STXKey", "invoice_id",
        "TransNo", "HeaderKey",
    )
    if not line_id or not inv_id:
        return None

    item_id  = _get(row, "ItemCode", "ItemID", "item_id", "StockCode", "PartNo")
    qty      = _safe_float(_get(row, "Quantity", "quantity", "Qty"))
    uprice   = _safe_float(_get(row, "UnitPrice", "unit_price", "Price", "SalesPrice"))
    discount = _safe_float(_get(row, "Discount", "discount", "DiscountPercent"))
    total    = _safe_float(_get(row, "LineTotal", "line_total", "Amount", "ExtendedAmount"))

    return {
        "line_id":     line_id,
        "invoice_id":  inv_id,
        "item_id":     item_id or None,
        "quantity":    round(qty, 4),
        "unit_price":  round(uprice, 4),
        "discount":    round(discount, 2),
        "line_total":  round(total, 2),
    }


# =============================================================================
# CSV → entity mapper dispatch
# =============================================================================

# csv_filename_stem → (entity_type, mapper_fn)
_CSV_ENTITY_MAP: List[Tuple[str, str, Any]] = [
    ("jrnlhdr",   "gl_journal_entries",      lambda r: _map_gl_journal(r, "jrnlhdr")),
    ("jrnlrow",   "gl_journal_entries",      lambda r: _map_gl_journal(r, "jrnlrow")),
    ("invcost",   "inventory_transactions",  _map_invcost),
    ("stxhdr",    "sales_invoices",           _map_sales_invoice),
    ("stxrow",    "sales_invoice_lines",      _map_sales_line),
    # The tables below are already extracted by hard_reader; these CSV versions
    # are treated as enrichment (uploaded with the same entity key — idempotent).
    ("chart",     "chart_of_accounts",        None),  # passthrough, see _load_csv
    ("taxcode",   None,                        None),  # no backend mapper yet — logged only
    ("bankrec",   None,                        None),
    ("budgets",   None,                        None),
    ("lineitem",  None,                        None),  # hard_reader already covers this
    ("vendors",   None,                        None),
    ("customers", None,                        None),
]


def _load_csv(csv_path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _map_csv_to_entity(
    stem: str,
    raw_rows: List[Dict[str, str]],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Return (entity_type, mapped_rows) for the given CSV stem, or (None, []) if unsupported."""
    for csv_stem, entity, mapper in _CSV_ENTITY_MAP:
        if stem.lower() == csv_stem:
            if entity is None or mapper is None:
                return None, []

            mapped: List[Dict[str, Any]] = []
            skipped = 0
            for i, row in enumerate(raw_rows):
                try:
                    result = mapper(row)
                    if result is not None:
                        mapped.append(result)
                    else:
                        skipped += 1
                except (ValueError, KeyError):
                    skipped += 1

            if skipped > 0 and len(mapped) == 0:
                # Print actual headers to help tune the mapper
                if raw_rows:
                    headers = list(raw_rows[0].keys())
                    print(f"  WARNING: all rows skipped for {stem}.csv")
                    print(f"  Actual columns: {headers}")
            elif skipped > 0:
                print(f"  {stem}: {skipped} rows skipped (missing required fields)")

            return entity, mapped

    return None, []


# =============================================================================
# DEDUPLICATION: jrnlhdr + jrnlrow both map to gl_journal_entries.
# Merge them into one dataset keyed by entity.
# =============================================================================

def _build_datasets(
    csv_dir: str,
    dry_run: bool,
    batch_id: str = "",
) -> Dict[str, List[Dict[str, Any]]]:
    """Read all CSVs, run mappers, merge same-entity datasets.

    Stage 1 (Bronze): raw CSV rows are archived before any transformation.
    Mapper failures are written to exceptions.jsonl via exception_manager.
    """
    import glob as _glob

    # Pipeline support — import lazily so script still works without them
    try:
        import bronze_layer as _bronze
        import exception_manager as _exc_mgr
        import quality_engine as _qe
        _pipeline_available = True
    except ImportError:
        _pipeline_available = False

    csv_files = sorted(_glob.glob(os.path.join(csv_dir, "*.csv")))
    if not csv_files:
        print(f"No CSVs found in: {csv_dir}")
        print("Run psql_extract_admin.ps1 as Administrator first.")
        sys.exit(1)

    # entity → accumulated rows
    datasets: Dict[str, List[Dict[str, Any]]] = {}

    for path in csv_files:
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        raw_rows = _load_csv(path)
        if not raw_rows:
            print(f"  {stem}.csv: empty — skipped")
            continue

        # Stage 1 — Bronze: archive raw rows before any transformation
        if batch_id and _pipeline_available and not dry_run:
            try:
                _bronze.save(batch_id, "csv_import", stem, raw_rows)
            except Exception:
                pass

        # Dry-run: limit to 5 rows per file
        if dry_run:
            raw_rows = raw_rows[:5]

        entity, mapped = _map_csv_to_entity(stem, raw_rows)
        if entity is None:
            print(f"  {stem}.csv: {len(raw_rows)} rows (no backend entity — logged only)")
            continue

        if not mapped:
            print(f"  {stem}.csv: 0 mappable rows")
            # Log as exception so steward can investigate
            if batch_id and _pipeline_available and not dry_run:
                try:
                    from quality_engine import QualityResult
                    for r in raw_rows:
                        _exc_mgr.log(
                            batch_id, "csv_import", stem,
                            QualityResult(r, "MAPPER_FAILED", "all_fields", "DATA_QUALITY"),
                        )
                except Exception:
                    pass
            continue

        if entity not in datasets:
            datasets[entity] = []
        datasets[entity].extend(mapped)

    # Deduplicate GL entries by (posting_date, account_id, debit, credit) in case
    # jrnlhdr and jrnlrow produced overlapping rows.
    if "gl_journal_entries" in datasets:
        seen = set()
        deduped = []
        for row in datasets["gl_journal_entries"]:
            key = (
                row.get("posting_date"),
                row.get("account_id"),
                row.get("debit_amount"),
                row.get("credit_amount"),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(row)
        datasets["gl_journal_entries"] = deduped

    return datasets


# =============================================================================
# MAIN
# =============================================================================

def _get_token() -> str:
    try:
        import requests
    except ImportError:
        sys.exit("ERROR: 'requests' not installed.  Run: pip install requests")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        resp = requests.post(
            f"{BACKEND_URL}/token",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASS},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:
        sys.exit(f"ERROR: Could not fetch token from {BACKEND_URL}\n  {exc}")


def _upload(datasets: Dict[str, List[Dict[str, Any]]], token: str) -> Dict[str, Any]:
    from sage50.loader import upload_to_backend
    try:
        return upload_to_backend(datasets, BACKEND_URL, token)
    except Exception as exc:
        return {"status": "error", "error": str(exc), "total_rows_inserted": 0}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest psql_extract_admin.ps1 CSV output into Synbot backend",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows, don't write")
    parser.add_argument(
        "--csv-dir", default=_DEFAULT_CSV_DIR,
        help=f"Folder containing extracted CSVs (default: {_DEFAULT_CSV_DIR})",
    )
    args = parser.parse_args()

    t0 = time.time()
    batch_id = f"batch_csv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    csv_dir = os.path.normpath(args.csv_dir)
    print(f"\n[Batch: {batch_id}]")
    print(f"CSV dir  : {csv_dir}")
    print(f"Backend  : {BACKEND_URL}")
    if args.dry_run:
        print("Mode     : DRY RUN (first 5 rows per CSV, no writes)")
    print()

    datasets = _build_datasets(csv_dir, dry_run=args.dry_run, batch_id=batch_id)

    if not datasets:
        print("\nNo mappable data found. Check the CSV column headers above.")
        sys.exit(0)

    print(f"\n{'Entity':<30} {'Rows':>8}")
    print("─" * 42)
    grand_total = 0
    for entity, rows in sorted(datasets.items()):
        print(f"  {entity:<28} {len(rows):>8}")
        grand_total += len(rows)
    print("─" * 42)
    print(f"  {'TOTAL':<28} {grand_total:>8}")

    if args.dry_run:
        print("\n[DRY RUN — nothing written]\n")
        return

    print("\nFetching auth token ...", end=" ", flush=True)
    token = _get_token()
    print("OK")

    print("Uploading to backend ...", end=" ", flush=True)
    result = _upload(datasets, token)
    print("done")
    print()

    status = result.get("status", "unknown")
    total_inserted = result.get("total_rows_inserted", 0)

    ds_map: Dict[str, Any] = {}
    for ds in result.get("datasets", []):
        ft = ds.get("file_type") or ds.get("file", "?")
        ds_map[ft] = ds

    for entity in sorted(datasets):
        ds_info = ds_map.get(entity, {})
        inserted = ds_info.get("rows_inserted", 0)
        st = ds_info.get("status", "?")
        err = ds_info.get("insert_error", "")
        err_str = f"  ERR: {err[:60]}" if err else ""
        print(f"  {entity:<30} {str(inserted):>6} rows   [{st}]{err_str}")

    if status not in ("succeeded", "partial_success"):
        err = result.get("error", "")
        if err:
            print(f"\nUpload error: {err[:200]}")

    elapsed = round(time.time() - t0, 1)
    mode = "[LIVE — data written to Synbot]"

    exception_count = 0
    try:
        import exception_manager as _em
        exception_count = len(_em.read_exceptions(batch_id=batch_id))
    except Exception:
        pass

    print(f"\n{'─'*50}")
    print(f"  Batch   {batch_id}")
    print(f"  TOTAL   {total_inserted:>6} rows inserted")
    print(f"  Time    {elapsed}s")
    print(f"  Mode    {mode}")
    print(f"  Exceptions: {exception_count} logged → exceptions.jsonl")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
