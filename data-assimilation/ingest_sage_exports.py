"""ingest_sage_exports.py — Unified Sage 50 XLSX ingestor for all export subfolders.

Covers 5 subfolders (34 files total); Account-Payable/ is handled by
the existing ingest_ap_exports.py and is included here via delegation.

Subfolder → entity mapping
--------------------------
General Ledger/         → coa, gl_journal_entries, gl_detail, cash_register  (7 files)
Financial Statements/   → gl_account_summary                                 (1 file)
Account Receivable/     → customers, sales_invoices, sales_invoice_lines,
                          gl_detail                                          (12 files)
Inventory/              → items, stock_on_hand, inventory_transactions,
                          gl_detail                                           (8 files)
Account Reconciliation/ → reconciliation_tracking (via HTTP), cash_register  (6 files)
Account-Payable/        → vendors, purchase_orders, inventory_transactions,
                          gl_journal_entries                                  (8 files)

Usage
-----
    python ingest_sage_exports.py --dry-run
    python ingest_sage_exports.py --clean          # truncate snapshots, then import all
    python ingest_sage_exports.py --folder "General Ledger"
    python ingest_sage_exports.py                  # import all subfolders (no truncate)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime
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

SAGE_EXPORTS_DIR = os.path.join(_HERE, "sage-exports")

SUBFOLDERS = {
    "General Ledger":         os.path.join(SAGE_EXPORTS_DIR, "General Ledger"),
    "Financial Statements":   os.path.join(SAGE_EXPORTS_DIR, "Financial Statements"),
    "Account Receivable":     os.path.join(SAGE_EXPORTS_DIR, "Account-Receiveable"),
    "Inventory":              os.path.join(SAGE_EXPORTS_DIR, "Inventory"),
    "Account Reconciliation": os.path.join(SAGE_EXPORTS_DIR, "Account reconciliation"),
    "Account Payable":        os.path.join(SAGE_EXPORTS_DIR, "Account-Payable"),
}

# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        s = str(v).replace(",", "").strip()
        if not s or s.lower() in ("none", "null", "n/a", ""):
            return default
        return round(float(s), 4)
    except (ValueError, TypeError, AttributeError):
        return default


def _safe_float_or_none(v: Any) -> Optional[float]:
    if v is None or str(v).strip() in ("", "None", "null", "N/A"):
        return None
    try:
        return round(float(str(v).replace(",", "").strip()), 4)
    except (ValueError, TypeError):
        return None


def _safe_date(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    if not s or s.lower() in ("none", "null", ""):
        return ""
    # Already ISO
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    # M/D/YY or M/D/YYYY
    for sep in ("/", "-"):
        parts = s.replace("-", "/").split("/")
        if len(parts) == 3:
            m, d_s, y = parts[0], parts[1], parts[2]
            if len(y) == 2:
                y = "20" + y
            try:
                return f"{int(y):04d}-{int(m):02d}-{int(d_s):02d}"
            except ValueError:
                pass
    return ""


def _norm_header(h: Any) -> str:
    """Normalise a header cell to a clean snake_case key.

    Strips newlines, lowercases, then replaces every run of non-alphanumeric
    characters (spaces, slashes, hashes, dots, parens, etc.) with a single
    underscore and strips leading/trailing underscores.

    Examples:
      "Invoice/CM #"  → "invoice_cm"
      "Active?"       → "active"
      "Payee/Paid By" → "payee_paid_by"
      "Debit Amt"     → "debit_amt"
      "Qty on Hand"   → "qty_on_hand"
    """
    import re
    if h is None:
        return ""
    s = str(h).replace("\n", " ").strip().lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    s = s.strip('_')
    return s


def _read_xlsx(path: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Return (normalised_headers, rows) from an XLSX. Skips entirely-blank rows."""
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

    headers = [_norm_header(h) for h in raw_rows[0]]

    rows: List[Dict[str, Any]] = []
    for row_vals in raw_rows[1:]:
        if all(v is None or str(v).strip() == "" for v in row_vals):
            continue
        row: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            if h:
                row[h] = row_vals[i] if i < len(row_vals) else None
        rows.append(row)
    return headers, rows


def _read_xlsx_raw(path: str) -> List[Tuple]:
    """Return raw rows (no header normalisation) — for free-form files."""
    try:
        import openpyxl
    except ImportError:
        sys.exit("ERROR: openpyxl not installed. Run: pip install openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    raw_rows = list(ws.iter_rows(values_only=True))
    wb.close()
    return raw_rows


def _get(row: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip() not in ("", "None"):
            return str(v).strip()
    return ""


def _sentinel(row: Dict[str, Any]) -> bool:
    """Return True if this row is a Sage sentinel/subtotal (Customer ID == '-')."""
    cid = str(row.get("customer_id", "") or "").strip()
    return cid == "-"


def _parse_expiry_from_item_type(raw: Any) -> str:
    """Extract an expiry date from Sage's free-text Item Type field.

    Placeware stores pharma expiry as MM/YY in Item Type (e.g. "12/25,",
    "09/25...", "02/21"). Returns the last day of that month as ISO date,
    or "" when no MM/YY pattern is present.
    """
    import re
    import calendar
    if raw is None:
        return ""
    m = re.search(r"(\d{1,2})\s*/\s*(\d{2,4})", str(raw))
    if not m:
        return ""
    mm, yy = int(m.group(1)), int(m.group(2))
    if not 1 <= mm <= 12:
        return ""
    if yy < 100:
        yy += 2000
    return f"{yy:04d}-{mm:02d}-{calendar.monthrange(yy, mm)[1]:02d}"


# =============================================================================
# GENERAL LEDGER (7 files)
# =============================================================================

def ingest_general_ledger(folder: str, datasets: Dict[str, List]) -> None:
    if not os.path.isdir(folder):
        print(f"  [WARN] General Ledger folder not found: {folder}")
        return

    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".xlsx") or fname.startswith("~$"):
            continue
        path  = os.path.join(folder, fname)
        stem  = fname.lower()

        # ── Chart of Accounts ─────────────────────────────────────────────
        if "chart of accounts" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                aid = _get(row, "account_id")
                if not aid:
                    continue
                active_raw = _get(row, "active")  # "Active?" → "active" after regex norm
                mapped.append({
                    "account_id":   aid,
                    "account_code": aid,
                    "account_name": _get(row, "account_description") or "Unknown",
                    "account_type": _get(row, "account_type") or None,
                    "is_active":    str(active_raw).lower() in ("yes", "true", "1", "y"),
                })
            datasets.setdefault("chart_of_accounts", []).extend(mapped)
            print(f"    {fname:<50} → chart_of_accounts     {len(mapped):>5} rows")

        # ── Trial Balance (GL Snapshot) ───────────────────────────────────
        elif "trial balance" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            period = datetime.now().strftime("%Y-%m")
            for row in rows:
                aid = _get(row, "account_id")
                if not aid:
                    continue
                debit  = _safe_float(_get(row, "debit_amt"))
                credit = _safe_float(_get(row, "credit_amt"))
                if debit == 0.0 and credit == 0.0:
                    continue
                mapped.append({
                    "posting_date": None,
                    "account_id":   aid,
                    "description":  _get(row, "account_description") or "Trial Balance",
                    "debit_amount": debit,
                    "credit_amount": credit,
                })
            datasets.setdefault("gl_journal_entries", []).extend(mapped)
            print(f"    {fname:<50} → gl_journal_entries    {len(mapped):>5} rows")

        # ── General Ledger (transaction-level) ───────────────────────────
        elif "general ledger" in stem and "trial" not in stem and "variance" not in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                aid = _get(row, "account_id")
                if not aid:
                    continue
                debit  = _safe_float_or_none(_get(row, "debit_amt"))
                credit = _safe_float_or_none(_get(row, "credit_amt"))
                # Skip Beginning Balance sentinel rows (both amounts None)
                if debit is None and credit is None:
                    continue
                mapped.append({
                    "account_code": aid,
                    "account_name": _get(row, "account_description") or None,
                    "txn_date":     _safe_date(_get(row, "date")) or None,
                    "reference":    _get(row, "reference") or None,
                    "journal_type": _get(row, "jrnl") or None,
                    "description":  _get(row, "trans_description") or None,
                    "debit":        debit or 0.0,
                    "credit":       credit or 0.0,
                    "source_file":  fname,
                })
            datasets.setdefault("gl_detail", []).extend(mapped)
            print(f"    {fname:<50} → gl_detail             {len(mapped):>5} rows")

        # ── General Journal ───────────────────────────────────────────────
        elif "general journal" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                aid = _get(row, "account_id")
                if not aid:
                    continue
                debit  = _safe_float(_get(row, "debit_amt"))
                credit = _safe_float(_get(row, "credit_amt"))
                if debit == 0.0 and credit == 0.0:
                    continue
                mapped.append({
                    "account_code": aid,
                    "account_name": _get(row, "account_description") or None,
                    "txn_date":     _safe_date(_get(row, "date")) or None,
                    "reference":    _get(row, "reference") or None,
                    "journal_type": "GJ",
                    "description":  _get(row, "trans_description") or None,
                    "debit":        debit,
                    "credit":       credit,
                    "source_file":  fname,
                })
            datasets.setdefault("gl_detail", []).extend(mapped)
            print(f"    {fname:<50} → gl_detail (GJ)        {len(mapped):>5} rows")

        # ── Cash Account Register ─────────────────────────────────────────
        elif "cash" in stem and "register" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                mapped.append({
                    "txn_date":        _safe_date(_get(row, "date")) or None,
                    "trans_no":        _get(row, "reference") or None,
                    "txn_type":        _get(row, "type") or None,
                    "description":     " ".join(filter(None, [
                        _get(row, "payee_paid_by"),
                        _get(row, "memo"),
                    ])) or None,
                    "reference":       _get(row, "reference") or None,
                    "payment_amount":  _safe_float(_get(row, "payment_amt")),
                    "receipt_amount":  _safe_float(_get(row, "receipt_amt")),
                    "running_balance": _safe_float_or_none(_get(row, "balance")),
                    "source_file":     fname,
                })
            datasets.setdefault("cash_register", []).extend(mapped)
            print(f"    {fname:<50} → cash_register         {len(mapped):>5} rows")

        # ── Account Variance (SKIP) ───────────────────────────────────────
        elif "variance" in stem:
            print(f"    {fname:<50} → SKIP (budget comparison)")

        else:
            print(f"    {fname:<50} → SKIP (unmatched)")


# =============================================================================
# FINANCIAL STATEMENTS (1 file)
# =============================================================================

def ingest_financial_statements(folder: str, datasets: Dict[str, List]) -> None:
    if not os.path.isdir(folder):
        print(f"  [WARN] Financial Statements folder not found: {folder}")
        return

    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".xlsx") or fname.startswith("~$"):
            continue
        path = os.path.join(folder, fname)
        stem = fname.lower()

        if "gl account" in stem or "account summar" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                acct = _get(row, "account_number")
                if not acct:
                    continue
                mapped.append({
                    "account_code":      acct,
                    "account_name":      _get(row, "account_description") or None,
                    "beginning_balance": _safe_float_or_none(_get(row, "beginning_balance")),
                    "debit_change":      _safe_float_or_none(_get(row, "debit_change")),
                    "credit_change":     _safe_float_or_none(_get(row, "credit_change")),
                    "net_change":        _safe_float_or_none(_get(row, "net_change")),
                    "ending_balance":    _safe_float_or_none(_get(row, "ending_balance")),
                })
            datasets.setdefault("gl_account_summary", []).extend(mapped)
            print(f"    {fname:<50} → gl_account_summary    {len(mapped):>5} rows")
        else:
            print(f"    {fname:<50} → SKIP (not GL account summary)")


# =============================================================================
# ACCOUNT RECEIVABLE (12 files)
# =============================================================================

def ingest_ar(folder: str, datasets: Dict[str, List]) -> None:
    if not os.path.isdir(folder):
        print(f"  [WARN] Account Receivable folder not found: {folder}")
        return

    # No cross-file deduplication — snapshot table accepts multiple source rows
    # per customer. The backend upserts on customer_id if needed.

    # Customer Management Details carries the real per-invoice due dates and
    # customer attribution; it sorts before Invoice Register, so this map is
    # ready when the register (which has no customer_id column) is parsed.
    ar_due_map: Dict[str, Dict[str, str]] = {}

    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".xlsx") or fname.startswith("~$"):
            continue
        path = os.path.join(folder, fname)
        stem = fname.lower()

        # ── Customer Master (primary customer file) ───────────────────────
        if "customer master" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                cid = _get(row, "customer_id")
                if not cid or cid == "-":
                    continue
                addr1 = _get(row, "address_line_1")
                addr2 = _get(row, "address_line_2")
                address = ", ".join(p for p in (addr1, addr2) if p) or None
                mapped.append({
                    "customer_id":    cid,
                    "name":           _get(row, "customer") or "Unknown",
                    "phone":          _get(row, "telephone_1") or _get(row, "telephone_2") or None,
                    "email":          _get(row, "email") or None,
                    "status":         "active",
                    "address":        address,
                    "city":           _get(row, "city_st_zip") or None,
                    "contact_person": _get(row, "bill_to_contact") or None,
                    "terms":          _get(row, "terms") or None,
                    "customer_since": _safe_date(row.get("cust_since")) or None,
                })
            datasets.setdefault("customers", []).extend(mapped)
            print(f"    {fname:<50} → customers             {len(mapped):>5} rows")

        # ── Customer List ─────────────────────────────────────────────────
        elif "customer list" in stem and "master" not in stem and "management" not in stem and "sales" not in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                cid = _get(row, "customer_id")
                if not cid:
                    continue
                mapped.append({
                    "customer_id": cid,
                    "name":        _get(row, "customer") or "Unknown",
                    "phone":       _get(row, "telephone_1") or None,
                    "email":       None,
                    "status":      "active",
                })
            datasets.setdefault("customers", []).extend(mapped)
            print(f"    {fname:<50} → customers (suppl.)    {len(mapped):>5} rows")

        # ── Contacts List ─────────────────────────────────────────────────
        elif "contacts" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                if _sentinel(row):
                    continue
                cid = _get(row, "customer_id")
                if not cid:
                    continue
                mapped.append({
                    "customer_id": cid,
                    "name":        _get(row, "customer") or "Unknown",
                    "phone":       _get(row, "telephone_1") or None,
                    "email":       _get(row, "email") or None,
                    "status":      "active",
                })
            datasets.setdefault("customers", []).extend(mapped)
            print(f"    {fname:<50} → customers (contacts)  {len(mapped):>5} rows")

        # ── Customer Management Details ───────────────────────────────────
        # Invoice-level rows: customer_id carries forward across the group.
        # Builds the invoice → (customer, due_date) map used by the Invoice
        # Register handler, since the register has no customer_id column.
        elif "management" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            cur_cid = ""
            for row in rows:
                if _sentinel(row):
                    continue
                cid = _get(row, "customer_id")
                if cid:
                    cur_cid = cid
                    mapped.append({
                        "customer_id": cid,
                        "name":        _get(row, "customer", "customer_name") or "Unknown",
                        "phone":       _get(row, "telephone_1") or None,
                        "email":       None,
                        "status":      "active",
                    })
                inv_no = _get(row, "invoice_no")
                due = _safe_date(row.get("date_due"))
                if cur_cid and inv_no and inv_no not in ar_due_map:
                    ar_due_map[inv_no] = {"customer_id": cur_cid, "due_date": due or ""}
            datasets.setdefault("customers", []).extend(mapped)
            print(f"    {fname:<50} → customers (mgmt)      {len(mapped):>5} rows "
                  f"(+{len(ar_due_map)} invoice due dates)")

        # ── Customer Sales History (per-customer profitability) ──────────
        elif "sales history" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                if _sentinel(row):
                    continue
                cid = _get(row, "customer_id")
                if not cid or cid.lower().startswith("report total"):
                    continue
                mapped.append({
                    "customer_id":   cid,
                    "name":          _get(row, "name", "customer") or None,
                    "amount":        _safe_float(_get(row, "amount")),
                    "cost_of_sales": _safe_float(_get(row, "cost_of_sales")),
                    "gross_profit":  _safe_float(_get(row, "gross_profit")),
                    "gross_margin":  _safe_float(_get(row, "gross_margin")),
                })
            datasets.setdefault("customer_sales", []).extend(mapped)
            print(f"    {fname:<50} → customer_sales        {len(mapped):>5} rows")

        # ── Invoice Register ──────────────────────────────────────────────
        elif "invoice register" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                if _sentinel(row):
                    continue
                # "Invoice/CM #" normalises to "invoice_cm" with regex norm
                inv_id = _get(row, "invoice_cm", "invoice_no", "invoice_cm_no")
                if not inv_id:
                    continue
                # Register has no customer_id column — resolve via the
                # Customer Management map, falling back to the row's name.
                mgmt = ar_due_map.get(inv_id) or {}
                cid = _get(row, "customer_id") or mgmt.get("customer_id") or _get(row, "name")
                amount = _safe_float(_get(row, "amount"))
                mapped.append({
                    "invoice_id":  inv_id,
                    "customer_id": cid or "UNKNOWN",
                    "date":        _safe_date(_get(row, "date")) or datetime.now().strftime("%Y-%m-%d"),
                    "due_date":    mgmt.get("due_date") or None,
                    "amount":      amount,
                    "balance":     amount,
                    "status":      "open",
                })
            datasets.setdefault("sales_invoices", []).extend(mapped)
            print(f"    {fname:<50} → sales_invoices        {len(mapped):>5} rows")

        # ── Aged Receivable ───────────────────────────────────────────────
        elif "aged" in stem and "receiveable" in stem or "aged_receiveable" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                if _sentinel(row):
                    continue
                cid = _get(row, "customer_id")
                if not cid:
                    continue
                # Construct a synthetic invoice_id from customer + aged balance
                inv_id = f"AGED_{cid}"
                amount = _safe_float(_get(row, "amount"))
                mapped.append({
                    "invoice_id":  inv_id,
                    "customer_id": cid,
                    "date":        datetime.now().strftime("%Y-%m-%d"),
                    "due_date":    None,
                    "amount":      amount,
                    "balance":     amount,
                    "status":      "open",
                })
            # Deduplicate by invoice_id
            seen: set = set()
            deduped = []
            for r in mapped:
                if r["invoice_id"] not in seen:
                    seen.add(r["invoice_id"])
                    deduped.append(r)
            datasets.setdefault("sales_invoices", []).extend(deduped)
            print(f"    {fname:<50} → sales_invoices (aged) {len(deduped):>5} rows")

        # ── Customer Ledger ───────────────────────────────────────────────
        elif "customer ledger" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            counter = 0
            for row in rows:
                if _sentinel(row):
                    continue
                cid = _get(row, "customer_id")
                if not cid:
                    continue
                counter += 1
                inv_id = _get(row, "invoice_cm", "invoice_no") or f"LEDGER_{cid}_{counter}"
                amount = _safe_float(_get(row, "amount"))
                mapped.append({
                    "invoice_id":  inv_id,
                    "customer_id": cid,
                    "date":        _safe_date(_get(row, "date")) or datetime.now().strftime("%Y-%m-%d"),
                    "due_date":    None,
                    "amount":      amount,
                    "balance":     amount,
                    "status":      "open",
                })
            datasets.setdefault("sales_invoices", []).extend(mapped)
            print(f"    {fname:<50} → sales_invoices (ledger){len(mapped):>5} rows")

        # ── Customer Transaction History ──────────────────────────────────
        elif "transaction history" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            counter = 0
            for row in rows:
                if _sentinel(row):
                    continue
                cid = _get(row, "customer_id")
                if not cid:
                    continue
                counter += 1
                inv_id = _get(row, "invoice_cm", "invoice_no") or f"TXH_{cid}_{counter}"
                amount = _safe_float(_get(row, "amount"))
                mapped.append({
                    "invoice_id":  inv_id,
                    "customer_id": cid,
                    "date":        _safe_date(_get(row, "date")) or datetime.now().strftime("%Y-%m-%d"),
                    "due_date":    None,
                    "amount":      amount,
                    "balance":     max(amount, 0),
                    "status":      "open",
                })
            datasets.setdefault("sales_invoices", []).extend(mapped)
            print(f"    {fname:<50} → sales_invoices (txhist){len(mapped):>5} rows")

        # ── Customer Sales History (SKIP — derived from AR) ───────────────
        elif "sales history" in stem:
            print(f"    {fname:<50} → SKIP (derived summary)")

        # ── Items Sold to Customers (invoice_lines) ───────────────────────
        elif "items sold" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            counter = 0
            for row in rows:
                if _sentinel(row):
                    continue
                item_id = _get(row, "item_id")
                cid     = _get(row, "customer_id")
                if not item_id:
                    continue
                counter += 1
                line_id = f"SOLD_{cid}_{item_id}_{counter}"
                qty     = _safe_float(_get(row, "qty"))
                amount  = _safe_float(_get(row, "amount"))
                cost    = _safe_float(_get(row, "cost_of_sales"))
                profit  = _safe_float(_get(row, "gross_profit"))
                mapped.append({
                    "line_id":      line_id,
                    "invoice_id":   f"SOLD_{cid}",
                    "item_id":      item_id,
                    "quantity":     qty,
                    "unit_price":   round(amount / qty, 4) if qty > 0 else 0.0,
                    "discount":     0.0,
                    "line_total":   amount,
                    "cost_at_sale": cost,
                    "gross_profit": profit,
                })
            datasets.setdefault("sales_invoice_lines", []).extend(mapped)
            print(f"    {fname:<50} → sales_invoice_lines   {len(mapped):>5} rows")

        # ── Cash Receipts Journal → gl_detail ─────────────────────────────
        elif "cash receipts" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                aid = _get(row, "account_id")
                if not aid:
                    continue
                debit  = _safe_float(_get(row, "debit_amnt"))
                credit = _safe_float(_get(row, "credit_amnt"))
                if debit == 0.0 and credit == 0.0:
                    continue
                mapped.append({
                    "account_code": aid,
                    "account_name": _get(row, "account_description") or None,
                    "txn_date":     _safe_date(_get(row, "date")) or None,
                    "reference":    _get(row, "transaction_ref") or None,
                    "journal_type": "CR",
                    "description":  _get(row, "line_description") or None,
                    "debit":        debit,
                    "credit":       credit,
                    "source_file":  fname,
                })
            datasets.setdefault("gl_detail", []).extend(mapped)
            print(f"    {fname:<50} → gl_detail (CR)        {len(mapped):>5} rows")

        # ── Sales Journal → gl_detail ─────────────────────────────────────
        elif "sales journal" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                aid = _get(row, "account_id")
                if not aid:
                    continue
                debit  = _safe_float(_get(row, "debit_amnt"))
                credit = _safe_float(_get(row, "credit_amnt"))
                if debit == 0.0 and credit == 0.0:
                    continue
                mapped.append({
                    "account_code": aid,
                    "account_name": _get(row, "account_description") or None,
                    "txn_date":     _safe_date(_get(row, "date")) or None,
                    "reference":    _get(row, "invoice_cm", "invoice_no") or None,
                    "journal_type": "SJ",
                    "description":  _get(row, "line_description") or None,
                    "debit":        debit,
                    "credit":       credit,
                    "source_file":  fname,
                })
            datasets.setdefault("gl_detail", []).extend(mapped)
            print(f"    {fname:<50} → gl_detail (SJ)        {len(mapped):>5} rows")

        else:
            print(f"    {fname:<50} → SKIP (unmatched)")


# =============================================================================
# INVENTORY (8 files)
# =============================================================================

def ingest_inventory(folder: str, datasets: Dict[str, List]) -> None:
    if not os.path.isdir(folder):
        print(f"  [WARN] Inventory folder not found: {folder}")
        return

    # Track item_ids seen within THIS run only for enrichment files
    # so we don't duplicate within a single source file. Cross-file
    # duplicates are fine — sage_items_snapshot is a snapshot table.
    items_in_master: set = set()

    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".xlsx") or fname.startswith("~$"):
            continue
        path = os.path.join(folder, fname)
        stem = fname.lower()

        # ── Item Master List ──────────────────────────────────────────────
        if "item master" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                iid = _get(row, "item_id")
                if not iid:
                    continue
                items_in_master.add(iid)
                mapped.append({
                    "item_id":            iid,
                    "item_name":          _get(row, "item_description") or "Unknown",
                    "category":           _get(row, "item_class") or None,
                    "unit":               _get(row, "stocking_u_m") or None,
                    "cost_price":         _safe_float(_get(row, "item_cost")),
                    "selling_price":      _safe_float(_get(row, "price_level_1")),
                    "preferred_vendor_id": _get(row, "preferred_vendor_id") or None,
                    # Placeware stores pharma expiry as MM/YY in the free-text
                    # Item Type field — parse it into a real date.
                    "expiry_date":        _parse_expiry_from_item_type(row.get("item_type")) or None,
                    "is_active":          True,
                })
            datasets.setdefault("items", []).extend(mapped)
            print(f"    {fname:<50} → items                 {len(mapped):>5} rows")

        # ── Item Price List (selling_price enrichment) ────────────────────
        elif "price list" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                iid = _get(row, "item_id")
                # Only add items NOT already covered by Item Master
                if not iid or iid in items_in_master:
                    continue
                mapped.append({
                    "item_id":       iid,
                    "item_name":     _get(row, "item_description") or "Unknown",
                    "selling_price": _safe_float(_get(row, "price_level_1")),
                    "is_active":     True,
                })
            datasets.setdefault("items", []).extend(mapped)
            print(f"    {fname:<50} → items (prices)        {len(mapped):>5} rows")

        # ── Stock Status ──────────────────────────────────────────────────
        elif "stock status" in stem or "inventiry stock" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                iid = _get(row, "item_id")
                if not iid:
                    continue
                mapped.append({
                    "item_id":          iid,
                    "item_name":        _get(row, "item_description") or iid,
                    "quantity_on_hand": _safe_float(_get(row, "qty_on_hand")),
                    "reorder_level":    _safe_float(_get(row, "min_stock")),
                    "reorder_quantity": _safe_float(_get(row, "reorder_qty")),
                    "unit":             _get(row, "u_m") or None,
                    "category":         _get(row, "item_class") or None,
                })
            datasets.setdefault("stock_on_hand", []).extend(mapped)
            print(f"    {fname:<50} → stock_on_hand         {len(mapped):>5} rows")

        # ── Inventory Valuation ───────────────────────────────────────────
        elif "valuation" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                iid = _get(row, "item_id")
                if not iid:
                    continue
                mapped.append({
                    "item_id":          iid,
                    "item_name":        _get(row, "item_description") or iid,
                    "quantity_on_hand": _safe_float(_get(row, "qty_on_hand")),
                    "unit_cost":        _safe_float(_get(row, "avg_cost")),
                    "valuation":        _safe_float(_get(row, "item_value")),
                    "storage_condition": _get(row, "cost_method") or None,
                })
            datasets.setdefault("stock_on_hand", []).extend(mapped)
            print(f"    {fname:<50} → stock_on_hand (val.)  {len(mapped):>5} rows")

        # ── Inventory Activity (unit activity) ────────────────────────────
        elif "unit_activity" in stem or "unit activity" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            counter = 0
            for row in rows:
                iid = _get(row, "item_id")
                if not iid:
                    continue
                counter += 1
                for txn_type, col in [
                    ("beg_qty",    "beg_qty"),
                    ("sold",       "units_sold"),
                    ("purchased",  "units_purc"),
                    ("adjustment", "adjust_qty"),
                ]:
                    qty_str = _get(row, col)
                    qty = _safe_float(qty_str)
                    if qty == 0.0 and not qty_str:
                        continue
                    mapped.append({
                        "transaction_id":   f"ACT_{iid}_{txn_type}_{counter}",
                        "item_id":          iid,
                        "transaction_type": txn_type,
                        "quantity_in":      qty if txn_type in ("purchased", "beg_qty") else 0.0,
                        "quantity_out":     qty if txn_type == "sold" else 0.0,
                        "unit_cost":        0.0,
                        "transaction_date": None,
                        "posted_by":        None,
                    })
            datasets.setdefault("inventory_transactions", []).extend(mapped)
            print(f"    {fname:<50} → inventory_transactions {len(mapped):>5} rows")

        # ── Item Costing (cost_price + valuation enrichment) ─────────────
        # Transaction-level costing report: one row per receipt/sale per item.
        # "Item Cost" on receipt rows is the unit cost; "Remaining Qty" /
        # "Remain Value" are running balances — the last populated row per
        # item is its current position. This is the only Sage export in the
        # folder that actually carries cost figures (Item Master and the
        # Valuation report export with those columns blank).
        elif "costing" in stem:
            _, rows = _read_xlsx(path)
            latest_cost: Dict[str, float] = {}
            latest_val: Dict[str, float] = {}
            for row in rows:
                iid = _get(row, "item_id")
                if not iid:
                    continue
                cost = _safe_float(_get(row, "item_cost") or _get(row, "actual_cost"))
                if cost > 0.0:
                    latest_cost[iid] = cost  # rows are chronological; keep last
                remain_val = _safe_float(_get(row, "remain_value"))
                if _get(row, "remaining_qty") or remain_val:
                    latest_val[iid] = remain_val

            # Enrich existing items rows in place (master exported cost as 0)
            enriched = 0
            for r in datasets.get("items", []):
                iid = r.get("item_id")
                if iid in latest_cost and not r.get("cost_price"):
                    r["cost_price"] = latest_cost[iid]
                    enriched += 1
            # Items with cost but absent from the master become minimal rows
            appended = []
            for iid, cost in latest_cost.items():
                if iid not in items_in_master:
                    appended.append({
                        "item_id":    iid,
                        "item_name":  iid,
                        "cost_price": cost,
                        "is_active":  True,
                    })
            datasets.setdefault("items", []).extend(appended)

            # Enrich stock rows with unit cost + running valuation
            stock_enriched = 0
            for r in datasets.get("stock_on_hand", []):
                iid = r.get("item_id")
                if not iid:
                    continue
                if iid in latest_cost and not r.get("unit_cost"):
                    r["unit_cost"] = latest_cost[iid]
                    stock_enriched += 1
                if iid in latest_val and not r.get("valuation"):
                    r["valuation"] = latest_val[iid]
            print(f"    {fname:<50} → items (costing)       "
                  f"{enriched:>5} enriched / {len(appended)} new / {stock_enriched} stock rows costed")

        # ── Buyers Report (preferred_vendor_id enrichment) ────────────────
        elif "buyers" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                iid = _get(row, "item_id")
                if not iid or iid in items_in_master:
                    continue
                vid = (_get(row, "vendor_id") or _get(row, "preferred_vendor_id")
                       or _get(row, "vendor"))
                if not vid:
                    continue
                mapped.append({
                    "item_id":            iid,
                    "item_name":          _get(row, "item_description") or iid,
                    "preferred_vendor_id": vid,
                    "is_active":          True,
                })
            datasets.setdefault("items", []).extend(mapped)
            print(f"    {fname:<50} → items (buyers)        {len(mapped):>5} rows")

        # ── COGS Journal → gl_detail ──────────────────────────────────────
        elif "cost of goods" in stem or "cogs" in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                aid = _get(row, "gl_acct_id") or _get(row, "account_id")
                if not aid:
                    continue
                debit  = _safe_float(_get(row, "debit_amount"))
                credit = _safe_float(_get(row, "credit_amount"))
                if debit == 0.0 and credit == 0.0:
                    continue
                mapped.append({
                    "account_code": aid,
                    "account_name": None,
                    "txn_date":     _safe_date(_get(row, "date")) or None,
                    "reference":    _get(row, "reference") or None,
                    "journal_type": "COGS",
                    "description":  _get(row, "line_description") or None,
                    "debit":        debit,
                    "credit":       credit,
                    "source_file":  fname,
                })
            datasets.setdefault("gl_detail", []).extend(mapped)
            print(f"    {fname:<50} → gl_detail (COGS)      {len(mapped):>5} rows")

        else:
            print(f"    {fname:<50} → SKIP (unmatched)")


# =============================================================================
# ACCOUNT RECONCILIATION (6 files)
# =============================================================================

def ingest_reconciliation(folder: str, recon_rows: List[Dict], datasets: Dict[str, List]) -> None:
    """Parse reconciliation files.

    Rows for reconciliation_tracking go into recon_rows list (uploaded via
    POST /finance/reconciliation/log, not via the batch ZIP endpoint).
    Cash register rows go into datasets['cash_register'].
    """
    if not os.path.isdir(folder):
        print(f"  [WARN] Reconciliation folder not found: {folder}")
        return

    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".xlsx") or fname.startswith("~$"):
            continue
        path = os.path.join(folder, fname)
        stem = fname.lower()

        # ── Account Reconciliation (free-form key-value layout) ───────────
        if "account reconciliation" in stem and "accounts register" not in stem:
            raw = _read_xlsx_raw(path)
            gl_balance   = None
            bank_balance = None
            period       = None
            account_code = "BANK"

            for row in raw:
                if not row or all(c is None for c in row):
                    continue
                label = str(row[0]).strip().lower() if row[0] else ""
                # Try col index 4 first (Sage standard), then col 3 or 5
                for val_idx in (4, 3, 5, 2):
                    val = row[val_idx] if len(row) > val_idx else None
                    if val is not None and str(val).strip() not in ("", "None"):
                        break

                if "gl balance" in label or "book balance" in label:
                    gl_balance = _safe_float_or_none(val)
                elif "bank" in label and "balance" in label:
                    bank_balance = _safe_float_or_none(val)
                elif "period" in label or "date" in label or "ending" in label:
                    period = _safe_date(val) or str(val or "").strip() or None
                elif "account" in label and ("number" in label or "no" in label or "id" in label):
                    candidate = str(val or "").strip()
                    if candidate:
                        account_code = candidate

            recon_rows.append({
                "account_code":     account_code,
                "account_name":     "Bank Account",
                "snapshot_type":    "account_reconciliation",
                "reconciled_period": period,
                "gl_balance":       gl_balance,
                "bank_balance":     bank_balance,
            })
            print(f"    {fname:<50} → reconciliation_tracking (acct_recon)")

        # ── Accounts Register → cash_register ─────────────────────────────
        elif "accounts register" in stem or stem.startswith("account") and "register" in stem and "reconciliation" not in stem:
            _, rows = _read_xlsx(path)
            mapped = []
            for row in rows:
                desc = _get(row, "trans_desc")
                if desc and desc.lower() == "beginning balance":
                    continue
                mapped.append({
                    "txn_date":       _safe_date(_get(row, "date")) or None,
                    "trans_no":       _get(row, "trans_no") or None,
                    "txn_type":       _get(row, "type") or None,
                    "description":    desc or None,
                    "reference":      _get(row, "trans_no") or None,
                    "payment_amount": _safe_float(_get(row, "withdrawal_amt")),
                    "receipt_amount": _safe_float(_get(row, "deposit_amt")),
                    "running_balance": _safe_float_or_none(_get(row, "balance")),
                    "source_file":    fname,
                })
            datasets.setdefault("cash_register", []).extend(mapped)
            print(f"    {fname:<50} → cash_register         {len(mapped):>5} rows")

        # ── Bank Deposit Report ───────────────────────────────────────────
        elif "bank deposit" in stem:
            _, rows = _read_xlsx(path)
            amounts = []
            for row in rows:
                amt_str = _get(row, "amount")
                amt = _safe_float_or_none(amt_str)
                if amt is not None:
                    amounts.append(amt)
            outstanding_total = round(sum(amounts), 2) if amounts else None
            recon_rows.append({
                "account_code":     "BANK_DEPOSIT",
                "account_name":     "Bank Deposit Report",
                "snapshot_type":    "bank_deposit_report",
                "reconciled_period": None,
                "gl_balance":       None,
                "bank_balance":     None,
                "outstanding_count": len(amounts),
                "outstanding_total": outstanding_total,
            })
            print(f"    {fname:<50} → reconciliation_tracking (bank_deposit) {len(amounts)} items")

        # ── Deposits in Transit ───────────────────────────────────────────
        elif "deposits in transit" in stem:
            _, rows = _read_xlsx(path)
            amounts = []
            for row in rows:
                amt_str = _get(row, "trans_amt")
                amt = _safe_float_or_none(amt_str)
                if amt is not None:
                    amounts.append(amt)
            recon_rows.append({
                "account_code":     "DEPOSITS_IN_TRANSIT",
                "account_name":     "Deposits in Transit",
                "snapshot_type":    "deposits_in_transit",
                "reconciled_period": None,
                "gl_balance":       None,
                "bank_balance":     None,
                "outstanding_count": len(amounts),
                "outstanding_total": round(sum(amounts), 2) if amounts else None,
            })
            print(f"    {fname:<50} → reconciliation_tracking (deposits_transit) {len(amounts)} items")

        # ── Other Outstanding Items ───────────────────────────────────────
        elif "other outstanding" in stem:
            _, rows = _read_xlsx(path)
            amounts = []
            for row in rows:
                amt_str = _get(row, "trans_amt")
                amt = _safe_float_or_none(amt_str)
                if amt is not None:
                    amounts.append(amt)
            recon_rows.append({
                "account_code":     "OTHER_OUTSTANDING",
                "account_name":     "Other Outstanding Items",
                "snapshot_type":    "other_outstanding_items",
                "reconciled_period": None,
                "gl_balance":       None,
                "bank_balance":     None,
                "outstanding_count": len(amounts),
                "outstanding_total": round(sum(amounts), 2) if amounts else None,
            })
            print(f"    {fname:<50} → reconciliation_tracking (other_outstanding) {len(amounts)} items")

        # ── Outstanding Checks ────────────────────────────────────────────
        elif "outstanding checks" in stem:
            _, rows = _read_xlsx(path)
            amounts = []
            for row in rows:
                amt_str = _get(row, "trans_amt")
                amt = _safe_float_or_none(amt_str)
                if amt is not None:
                    amounts.append(abs(amt))
            recon_rows.append({
                "account_code":     "OUTSTANDING_CHECKS",
                "account_name":     "Outstanding Checks",
                "snapshot_type":    "outstanding_checks",
                "reconciled_period": None,
                "gl_balance":       None,
                "bank_balance":     None,
                "outstanding_count": len(amounts),
                "outstanding_total": round(sum(amounts), 2) if amounts else None,
            })
            print(f"    {fname:<50} → reconciliation_tracking (outstanding_checks) {len(amounts)} items")

        else:
            print(f"    {fname:<50} → SKIP (unmatched)")


# =============================================================================
# ACCOUNT PAYABLE — delegate to ingest_ap_exports logic
# =============================================================================

def ingest_ap(folder: str, datasets: Dict[str, List]) -> None:
    if not os.path.isdir(folder):
        print(f"  [WARN] Account Payable folder not found: {folder}")
        return
    # Import the AP ingestor logic directly
    try:
        from ingest_ap_exports import build_datasets as ap_build
    except ImportError:
        print("  [WARN] ingest_ap_exports.py not importable — skipping AP subfolder")
        return

    ap_datasets = ap_build(folder, only_entity=None, dry_run=False)
    for entity, rows in ap_datasets.items():
        datasets.setdefault(entity, []).extend(rows)
        print(f"    [AP] {entity:<46} {len(rows):>5} rows")


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
    resp = requests.post(
        f"{backend_url}/token",
        data={"username": email, "password": password},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _truncate(backend_url: str, token: str) -> None:
    try:
        import requests
        import urllib3
    except ImportError:
        sys.exit("ERROR: 'requests' not installed.")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    resp = requests.post(
        f"{backend_url}/sage/import/truncate",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        verify=False,
    )
    if resp.status_code not in (200, 201):
        print(f"  [WARN] Truncate endpoint returned {resp.status_code}: {resp.text[:200]}")
    else:
        tables = resp.json().get("tables_truncated", [])
        print(f"  Truncated {len(tables)} snapshot tables.")


def _upload_batch(datasets: Dict[str, List], backend_url: str, token: str) -> Dict[str, Any]:
    from sage50.loader import upload_to_backend
    return upload_to_backend(datasets, backend_url, token, timeout=600)


def _upload_reconciliation(recon_rows: List[Dict], backend_url: str, token: str) -> None:
    """POST each reconciliation row to /finance/reconciliation/log."""
    try:
        import requests
        import urllib3
    except ImportError:
        sys.exit("ERROR: 'requests' not installed.")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    ok = 0
    for row in recon_rows:
        import json
        payload = {k: v for k, v in row.items() if v is not None}
        resp = requests.post(
            f"{backend_url}/finance/reconciliation/log",
            headers=headers,
            data=json.dumps(payload),
            timeout=15,
            verify=False,
        )
        if resp.status_code in (200, 201):
            ok += 1
        else:
            print(f"  [WARN] reconciliation/log failed ({resp.status_code}) for "
                  f"{row.get('snapshot_type')}: {resp.text[:150]}")

    print(f"  Reconciliation rows uploaded: {ok}/{len(recon_rows)}")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest all Sage 50 XLSX exports into ACE/Synbot"
    )
    parser.add_argument("--dry-run",  action="store_true",
                        help="Parse files and print counts, no writes")
    parser.add_argument("--clean",    action="store_true",
                        help="Truncate all sage_*_snapshot tables before importing")
    parser.add_argument("--folder",   default=None,
                        help="Process only one subfolder, e.g. 'General Ledger'")
    parser.add_argument("--backend",  default=BACKEND_URL,
                        help=f"Backend base URL (default: {BACKEND_URL})")
    args = parser.parse_args()

    t0 = time.time()
    print(f"\n{'='*65}")
    print(f"  Sage 50 Full Export Ingestion")
    print(f"  Source : {SAGE_EXPORTS_DIR}")
    print(f"  Backend: {args.backend}")
    if args.clean:
        print(f"  Mode   : CLEAN + IMPORT (truncates snapshot tables first)")
    elif args.dry_run:
        print(f"  Mode   : DRY RUN — no writes")
    print(f"{'='*65}\n")

    # ── Auth ──────────────────────────────────────────────────────────────
    if not args.dry_run:
        print("Fetching auth token ...", end=" ", flush=True)
        token = _get_token(args.backend, ADMIN_EMAIL, ADMIN_PASS)
        print("OK")
    else:
        token = ""

    # ── Truncate ──────────────────────────────────────────────────────────
    if args.clean and not args.dry_run:
        print("\nTruncating snapshot tables ...")
        _truncate(args.backend, token)

    # ── Parse all subfolders ──────────────────────────────────────────────
    datasets: Dict[str, List[Dict]] = {}
    recon_rows: List[Dict]          = []

    run_all = args.folder is None

    def _run(label: str, fn, *fn_args):
        if run_all or args.folder == label:
            print(f"\n[{label}]")
            fn(*fn_args)

    _run("General Ledger",         ingest_general_ledger,    SUBFOLDERS["General Ledger"],       datasets)
    _run("Financial Statements",   ingest_financial_statements, SUBFOLDERS["Financial Statements"], datasets)
    _run("Account Receivable",     ingest_ar,                SUBFOLDERS["Account Receivable"],   datasets)
    _run("Inventory",              ingest_inventory,          SUBFOLDERS["Inventory"],            datasets)
    _run("Account Reconciliation", ingest_reconciliation,    SUBFOLDERS["Account Reconciliation"], recon_rows, datasets)
    _run("Account Payable",        ingest_ap,                SUBFOLDERS["Account Payable"],       datasets)

    # ── Deduplication ─────────────────────────────────────────────────────
    # Vendors: deduplicate by vendor_id
    if "vendors" in datasets:
        seen: set = set()
        deduped = [r for r in datasets["vendors"]
                   if r.get("vendor_id") and not (r["vendor_id"] in seen or seen.add(r["vendor_id"]))]
        datasets["vendors"] = deduped

    # Chart of accounts: deduplicate by account_id
    if "chart_of_accounts" in datasets:
        seen = set()
        datasets["chart_of_accounts"] = [
            r for r in datasets["chart_of_accounts"]
            if r.get("account_id") and not (r["account_id"] in seen or seen.add(r["account_id"]))
        ]

    # Items: deduplicate by item_id
    if "items" in datasets:
        seen = set()
        datasets["items"] = [
            r for r in datasets["items"]
            if r.get("item_id") and not (r["item_id"] in seen or seen.add(r["item_id"]))
        ]

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  {'Entity':<38} {'Rows':>8}")
    print(f"{'─'*65}")
    grand_total = 0
    for entity, rows in sorted(datasets.items()):
        print(f"  {entity:<38} {len(rows):>8}")
        grand_total += len(rows)
    if recon_rows:
        print(f"  {'reconciliation_tracking':<38} {len(recon_rows):>8}  (via /log endpoint)")
    print(f"{'─'*65}")
    print(f"  {'TOTAL snapshot rows':<38} {grand_total:>8}")

    if args.dry_run:
        print(f"\n[DRY RUN complete — {round(time.time()-t0, 1)}s]\n")
        return

    if not datasets and not recon_rows:
        print("\nNo uploadable data found. Exiting.")
        sys.exit(0)

    # ── Upload snapshot batch — entity by entity, chunked for large sets ──
    CHUNK_SIZE = 50_000   # rows per HTTP request
    total_inserted = 0

    if datasets:
        print(f"\nUploading {len(datasets)} entities to backend (chunk size {CHUNK_SIZE:,}) ...")
        print(f"{'─'*65}")
        for entity, rows in sorted(datasets.items()):
            if not rows:
                print(f"  {entity:<38}      0 rows  [skip]")
                continue
            chunks = [rows[i:i+CHUNK_SIZE] for i in range(0, len(rows), CHUNK_SIZE)]
            entity_inserted = 0
            ok = True
            for chunk_idx, chunk in enumerate(chunks):
                label = f"{entity} [{chunk_idx+1}/{len(chunks)}]" if len(chunks) > 1 else entity
                try:
                    result = _upload_batch({entity: chunk}, args.backend, token)
                    for ds in result.get("datasets", []):
                        entity_inserted += ds.get("rows_inserted", 0)
                    err_ds = next((ds for ds in result.get("datasets", []) if ds.get("insert_error")), None)
                    if err_ds:
                        print(f"  {label:<38} {entity_inserted:>6} rows  [WARN: {str(err_ds['insert_error'])[:40]}]")
                    else:
                        chunk_info = f"chunk {chunk_idx+1}" if len(chunks) > 1 else ""
                        if chunk_info:
                            print(f"  {label:<38} {len(chunk):>6} rows  [ok]")
                except Exception as exc:
                    print(f"  {label:<38} ERROR: {exc}")
                    ok = False
                    break
            if ok:
                print(f"  {entity:<38} {entity_inserted:>6} rows  [done]")
            total_inserted += entity_inserted
        print(f"{'─'*65}")
        print(f"  Total inserted: {total_inserted}")

    # ── Upload reconciliation rows ────────────────────────────────────────
    if recon_rows:
        print("\nUploading reconciliation tracking rows ...")
        _upload_reconciliation(recon_rows, args.backend, token)

    elapsed = round(time.time() - t0, 1)
    print(f"\n  Completed in {elapsed}s\n")


if __name__ == "__main__":
    main()
