"""ingest_ap_exports.py — Ingest Sage 50 AP XLSX exports into ACE/Synbot.

Reads XLSX files from sage-exports/Account Payable/ and uploads via the
same ZIP-batch endpoint used by assimilate_from_csv.py.

Usage
-----
    python ingest_ap_exports.py --dry-run          # preview counts, no writes
    python ingest_ap_exports.py                     # full ingest all files
    python ingest_ap_exports.py --file vendors      # one entity only

File → Entity mapping
---------------------
  Vendor Master List.xlsx         → vendors          → sage_vendors_snapshot
  Items purchased from vendors.xlsx → inventory_transactions → sage_inv_transactions_snapshot
  Open AP invoices.xlsx           → purchase_orders  → sage_purchase_orders_snapshot
  Purchased journal.xlsx          → gl_journal_entries → sage_gl_snapshot
  Vendor transaction history.xlsx → purchase_orders  (vendor invoice history)
  Vendor ledgers.xlsx             → (validation only — not uploaded)
  Aged Payables.xlsx              → (validation only — not uploaded)
  Purchase order journal.xlsx     → vendors          (duplicate of Vendor Master List)
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# =============================================================================
# CONFIG
# =============================================================================

BACKEND_URL  = "http://localhost:8000"
ADMIN_EMAIL  = "admin@placeware.com"
ADMIN_PASS   = "pware1234"

AP_EXPORT_DIR = os.path.join(
    _HERE,
    "sage-exports",
    "Account-Payable",
)

# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(v: Any) -> float:
    try:
        return round(float(str(v).replace(",", "").strip()), 4)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _safe_date(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    if not s or s.lower() in ("none", "null", ""):
        return ""
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    for sep in ("/", "-"):
        parts = s.replace("-", "/").split("/")
        if len(parts) == 3:
            m, d_str, y = parts[0], parts[1], parts[2]
            if len(y) == 2:
                y = "20" + y
            try:
                return f"{int(y):04d}-{int(m):02d}-{int(d_str):02d}"
            except ValueError:
                pass
    return ""


def _read_xlsx(path: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Return (headers, rows) from an XLSX file. Skips entirely-blank rows."""
    try:
        import openpyxl
    except ImportError:
        sys.exit("ERROR: openpyxl not installed. Run: pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    raw_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not raw_rows:
        return [], []

    headers = [str(h).strip() if h is not None else "" for h in raw_rows[0]]

    rows: List[Dict[str, Any]] = []
    for row_vals in raw_rows[1:]:
        # Skip completely blank rows
        if all(v is None or str(v).strip() == "" for v in row_vals):
            continue
        row: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            if h:
                row[h] = row_vals[i] if i < len(row_vals) else None
        rows.append(row)

    return headers, rows


def _get(row: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip() not in ("", "None"):
            return str(v).strip()
    return ""


# =============================================================================
# COLUMN MAPPERS — one function per export type
# Each returns a list of ACE-ready row dicts (or empty list to skip row)
# =============================================================================

def _map_vendor_master(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Vendor Master List.xlsx / Purchase order journal.xlsx (same columns)
    Sage columns: Vendor ID | Vendor | Address line 1 | Address line 2 |
                  City ST ZIP | Contact | Telephone 1 | Telephone 2 |
                  Fax Number | 1099 Type | Tax Id No | Terms | Vend Since
    """
    out = []
    seen: set = set()
    for row in rows:
        vendor_id = _get(row, "Vendor ID")
        if not vendor_id or vendor_id in seen:
            continue
        # Skip rows that look like group headers (no Vendor Name)
        vendor_name = _get(row, "Vendor")
        if not vendor_name:
            continue
        seen.add(vendor_id)

        # "City ST ZIP" contains the city (and sometimes state/country).
        # Take the first meaningful token as the city value.
        city_raw = _get(row, "City ST ZIP")

        out.append({
            "vendor_id":     vendor_id,
            "vendor_name":   vendor_name,
            "contact_name":  _get(row, "Contact"),
            "address":       _get(row, "Address line 1"),
            "city":          city_raw,
            "phone":         _get(row, "Telephone 1"),
            "tax_id":        _get(row, "Tax Id No"),
            "payment_terms": _get(row, "Terms"),
            "status":        "active",
        })
    return out


def _map_items_purchased(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Items purchased from vendors.xlsx
    Sage columns: Vendor ID | Name | Item ID | Item Description | Qty | Stocking U/M | Amount
    Note: This is a SUMMARY report (no dates). One row per vendor+item combination.
          Creates a synthetic Purchase History transaction per row.
          unit_cost is derived as Amount / Qty when Qty > 0.
    """
    out = []
    counter = 0
    current_vendor = ""
    for row in rows:
        # Sage groups rows under each vendor — carry vendor forward
        vid = _get(row, "Vendor ID")
        if vid:
            current_vendor = vid

        item_id = _get(row, "Item ID")
        if not item_id:
            continue  # subtotal or blank row

        qty    = _safe_float(_get(row, "Qty"))
        amount = _safe_float(_get(row, "Amount"))

        # Derive unit cost from totals
        unit_cost = round(amount / qty, 4) if qty > 0 else 0.0

        counter += 1
        txn_id = f"AP_PURCH_{current_vendor}_{item_id}_{counter}"

        out.append({
            "transaction_id":   txn_id,
            "item_id":          item_id,
            "transaction_type": "Purchase History",
            "quantity_in":      qty,
            "quantity_out":     0.0,
            "unit_cost":        unit_cost,
            "reference_number": current_vendor,
            "transaction_date": None,
            "posted_by":        None,
        })
    return out


def _map_open_ap_invoices(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Open AP invoices.xlsx  (Vendor Management Detail)
    Sage columns: Vendor ID | Vendor Name | Account No | Current Balance |
                  Invoice No. | Terms | Date Due | Net to Pay | Days To Pay
    Maps to purchase_orders entity — open vendor invoices as AP obligations.
    """
    out = []
    seen: set = set()
    current_vendor = ""
    for row in rows:
        vid = _get(row, "Vendor ID")
        if vid:
            current_vendor = vid

        inv_no = _get(row, "Invoice No.")
        if not inv_no or not current_vendor:
            continue

        po_id = f"{current_vendor}_{inv_no}"
        if po_id in seen:
            continue
        seen.add(po_id)

        net_to_pay = _safe_float(_get(row, "Net to Pay"))
        date_due   = _safe_date(_get(row, "Date Due"))

        out.append({
            "po_id":                  po_id,
            "po_number":              inv_no,
            "vendor_id":              current_vendor,
            "order_date":             None,
            "expected_delivery_date": date_due or None,
            "total_amount":           net_to_pay,
            "tax_amount":             0.0,
            "discount_amount":        0.0,
            "net_amount":             net_to_pay,
            "status":                 "open",
            "created_by":             None,
        })
    return out


def _map_purchased_journal(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Purchased journal.xlsx  (Purchase Journal — GL format)
    Sage columns: Date | Account ID | Account Description |
                  Invoice/CM # | Line Description | Debit Amount | Credit Amount
    Maps directly to gl_journal_entries.
    """
    out = []
    for row in rows:
        account_id = _get(row, "Account ID")
        if not account_id:
            continue

        debit  = _safe_float(_get(row, "Debit Amount"))
        credit = _safe_float(_get(row, "Credit Amount"))
        if debit == 0.0 and credit == 0.0:
            continue

        description = _get(row, "Line Description") or _get(row, "Account Description")
        invoice_ref = _get(row, "Invoice/CM #")
        if invoice_ref:
            description = f"{invoice_ref} — {description}" if description else invoice_ref

        out.append({
            "posting_date":  _safe_date(_get(row, "Date")) or None,
            "account_id":    account_id,
            "description":   description or "AP Journal Entry",
            "debit_amount":  debit,
            "credit_amount": credit,
        })
    return out


def _map_vendor_txn_history(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Vendor transaction history.xlsx
    Sage columns: Vendor ID | Vendor Name | Invoice No. | Transaction | Trans No. | Date | Amount
    Invoice rows → purchase_orders (open AP invoices)
    Payment rows → skipped (reduce outstanding balance)
    """
    out = []
    seen: set = set()
    current_vendor = ""
    for row in rows:
        vid = _get(row, "Vendor ID")
        if vid:
            current_vendor = vid

        txn_type = _get(row, "Transaction").lower()
        trans_no = _get(row, "Trans No.")
        inv_no   = _get(row, "Invoice No.")

        if txn_type != "invoice" or not trans_no or not current_vendor:
            continue

        po_id = f"VTH_{current_vendor}_{trans_no}"
        if po_id in seen:
            continue
        seen.add(po_id)

        amount = _safe_float(_get(row, "Amount"))
        txn_date = _safe_date(_get(row, "Date"))

        out.append({
            "po_id":                  po_id,
            "po_number":              inv_no or trans_no,
            "vendor_id":              current_vendor,
            "order_date":             txn_date or None,
            "expected_delivery_date": None,
            "total_amount":           amount,
            "tax_amount":             0.0,
            "discount_amount":        0.0,
            "net_amount":             amount,
            "status":                 "open",
            "created_by":             None,
        })
    return out


# =============================================================================
# FILE → ENTITY DISPATCH TABLE
# (filename_pattern, entity_type, mapper_fn, upload=True/False)
# =============================================================================

_FILE_MAP = [
    ("vendor master list",        "vendors",                _map_vendor_master,        True),
    ("purchase order journal",    "vendors",                _map_vendor_master,        True),  # duplicate file
    ("items purchased",           "inventory_transactions", _map_items_purchased,      True),
    ("open ap invoices",          "purchase_orders",        _map_open_ap_invoices,     True),
    ("purchased journal",         "gl_journal_entries",     _map_purchased_journal,    True),
    ("vendor transaction history","purchase_orders",        _map_vendor_txn_history,   True),
    ("vendor ledgers",            None,                     None,                      False),  # validation only
    ("aged payables",             None,                     None,                      False),  # validation only
]


def _match_file(filename: str):
    stem = os.path.splitext(filename)[0].lower()
    for pattern, entity, mapper, upload in _FILE_MAP:
        if pattern in stem:
            return entity, mapper, upload
    return None, None, False


# =============================================================================
# LOAD ALL XLSX FILES
# =============================================================================

def build_datasets(
    ap_dir: str,
    only_entity: Optional[str],
    dry_run: bool,
) -> Dict[str, List[Dict[str, Any]]]:
    """Read and map all XLSX exports. Returns {entity: [rows]}."""
    datasets: Dict[str, List[Dict[str, Any]]] = {}

    xlsx_files = sorted(
        f for f in os.listdir(ap_dir) if f.lower().endswith(".xlsx")
    )
    if not xlsx_files:
        print(f"No XLSX files found in: {ap_dir}")
        sys.exit(1)

    for fname in xlsx_files:
        entity, mapper, do_upload = _match_file(fname)

        if not do_upload or entity is None or mapper is None:
            print(f"  {fname:<45} → SKIP (validation only)")
            continue

        if only_entity and entity != only_entity:
            continue

        path = os.path.join(ap_dir, fname)
        headers, rows = _read_xlsx(path)

        if not rows:
            print(f"  {fname:<45} → empty")
            continue

        sample = rows[:5] if dry_run else rows
        mapped = mapper(sample if dry_run else rows)

        print(f"  {fname:<45} → {entity:<25} {len(mapped):>5} rows"
              + (" [DRY RUN — first 5 source rows]" if dry_run else ""))

        if not mapped:
            print(f"    WARNING: 0 rows mapped. Headers were: {headers}")
            continue

        if entity not in datasets:
            datasets[entity] = []
        # Deduplicate by primary key where applicable
        datasets[entity].extend(mapped)

    # Deduplicate vendors by vendor_id (Vendor Master List + PO Journal are the same data)
    if "vendors" in datasets:
        seen_ids: set = set()
        deduped = []
        for r in datasets["vendors"]:
            vid = r.get("vendor_id", "")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                deduped.append(r)
        datasets["vendors"] = deduped

    # Merge purchase_orders across source files by (vendor_id, po_number).
    # "Open AP invoices" rows carry the due date; "Vendor transaction history"
    # rows carry the order date + invoice amount. The same invoice appears in
    # both files under different po_ids, so a po_id-only dedup keeps both
    # half-records and double-counts the totals.
    if "purchase_orders" in datasets:
        merged: Dict[tuple, Dict[str, Any]] = {}
        for r in datasets["purchase_orders"]:
            key = (r.get("vendor_id", ""), r.get("po_number", ""))
            if not key[0] or not key[1]:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(r)
                continue
            # Prefer the VTH row (real order date + amount) as the base
            base, other = (existing, r)
            if str(r.get("po_id", "")).startswith("VTH_"):
                base, other = (dict(r), existing)
                merged[key] = base
            base["order_date"] = base.get("order_date") or other.get("order_date")
            base["expected_delivery_date"] = (
                base.get("expected_delivery_date") or other.get("expected_delivery_date")
            )
            for amt_col in ("total_amount", "net_amount"):
                if not base.get(amt_col):
                    base[amt_col] = other.get(amt_col)
        datasets["purchase_orders"] = list(merged.values())

    return datasets


# =============================================================================
# AUTH + UPLOAD
# =============================================================================

def _get_token(backend_url: str, email: str, password: str) -> str:
    try:
        import requests
        import urllib3
    except ImportError:
        sys.exit("ERROR: 'requests' not installed. Run: pip install requests")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        resp = requests.post(
            f"{backend_url}/token",
            data={"username": email, "password": password},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:
        sys.exit(f"ERROR: Could not get auth token from {backend_url}\n  {exc}")


def _upload(
    datasets: Dict[str, List[Dict[str, Any]]],
    backend_url: str,
    token: str,
) -> Dict[str, Any]:
    from sage50.loader import upload_to_backend
    return upload_to_backend(datasets, backend_url, token)


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Sage 50 AP XLSX exports into ACE/Synbot"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview row counts without writing")
    parser.add_argument("--file", default=None,
                        help="Only process one entity type (e.g. 'vendors')")
    parser.add_argument("--backend", default=BACKEND_URL,
                        help=f"Backend URL (default: {BACKEND_URL})")
    args = parser.parse_args()

    t0 = time.time()
    batch_id = f"ap_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\n{'='*60}")
    print(f"  Sage 50 AP Export Ingestion")
    print(f"  Batch   : {batch_id}")
    print(f"  Source  : {AP_EXPORT_DIR}")
    print(f"  Backend : {args.backend}")
    if args.dry_run:
        print(f"  Mode    : DRY RUN — no writes")
    print(f"{'='*60}\n")

    print("Reading XLSX files:")
    datasets = build_datasets(AP_EXPORT_DIR, only_entity=args.file, dry_run=args.dry_run)

    if not datasets:
        print("\nNo uploadable data found.")
        sys.exit(0)

    print(f"\n{'─'*60}")
    print(f"{'Entity':<30} {'Rows':>8}")
    print(f"{'─'*60}")
    grand_total = 0
    for entity, rows in sorted(datasets.items()):
        print(f"  {entity:<28} {len(rows):>8}")
        grand_total += len(rows)
    print(f"{'─'*60}")
    print(f"  {'TOTAL':<28} {grand_total:>8}")

    if args.dry_run:
        print(f"\n[DRY RUN complete — {round(time.time()-t0,1)}s]\n")
        return

    print("\nFetching auth token ...", end=" ", flush=True)
    token = _get_token(args.backend, ADMIN_EMAIL, ADMIN_PASS)
    print("OK")

    print("Uploading to backend ...", end=" ", flush=True)
    try:
        result = _upload(datasets, args.backend, token)
        print("done\n")
    except Exception as exc:
        print(f"\nERROR during upload: {exc}")
        sys.exit(1)

    # Print per-entity results
    ds_map: Dict[str, Any] = {}
    for ds in result.get("datasets", []):
        ft = ds.get("file_type") or ds.get("file", "?")
        ds_map[ft] = ds

    print(f"{'─'*60}")
    for entity in sorted(datasets):
        info = ds_map.get(entity, {})
        inserted = info.get("rows_inserted", "?")
        status   = info.get("status", "?")
        err      = info.get("insert_error", "")
        err_str  = f"  ERR: {err[:55]}" if err else ""
        print(f"  {entity:<28} {str(inserted):>6} rows  [{status}]{err_str}")
    print(f"{'─'*60}")

    elapsed = round(time.time() - t0, 1)
    total_inserted = result.get("total_rows_inserted", 0)
    print(f"\n  Batch     : {batch_id}")
    print(f"  Inserted  : {total_inserted} rows")
    print(f"  Time      : {elapsed}s")
    print(f"  Status    : {result.get('status', 'unknown')}\n")


if __name__ == "__main__":
    main()
