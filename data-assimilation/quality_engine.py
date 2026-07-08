"""quality_engine.py — Data Quality Engine for the ACE pipeline.

Stage 2 of the ACE Data Engineering Pipeline (see docs.md/ACE-Data-Blueprint.md).

Validates raw Sage 50 rows against domain-specific rules before canonical
transformation.  Returns (valid_rows, quarantined_rows).  No silent failures —
every rejected row is returned with an error classification so the exception
manager can record it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

class QualityResult:
    def __init__(self, row: Dict[str, Any], error_type: str, field: str, severity: str):
        self.row        = row
        self.error_type = error_type
        self.field      = field
        self.severity   = severity   # RECOVERABLE | DATA_QUALITY | CRITICAL

    def as_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.error_type,
            "field":      self.field,
            "severity":   self.severity,
            "raw_record": self.row,
        }


# ---------------------------------------------------------------------------
# Per-entity validation rules
# ---------------------------------------------------------------------------

def _validate_customers(rows: List[Dict]) -> Tuple[List[Dict], List[QualityResult]]:
    valid: List[Dict] = []
    rejected: List[QualityResult] = []
    seen_ids: set = set()

    for row in rows:
        account_no = str(row.get("customer_id") or row.get("CustId") or "").strip()
        # In Sage 50, CustId often IS the customer name; Name (offset 781) is the legal name
        # and is frequently blank. Fall back to CustId as the display name if Name is empty.
        name       = str(row.get("name") or row.get("Name") or row.get("CustId") or "").strip()

        if not account_no:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "customer_id", "DATA_QUALITY"))
            continue
        if not name:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "name", "DATA_QUALITY"))
            continue
        if account_no in seen_ids:
            rejected.append(QualityResult(row, "DUPLICATE_KEY", "customer_id", "DATA_QUALITY"))
            continue

        seen_ids.add(account_no)
        valid.append(row)

    return valid, rejected


def _validate_vendors(rows: List[Dict]) -> Tuple[List[Dict], List[QualityResult]]:
    valid: List[Dict] = []
    rejected: List[QualityResult] = []
    seen_ids: set = set()

    for row in rows:
        vendor_id = str(row.get("vendor_id") or row.get("VendorId") or row.get("VendorID") or row.get("ID") or "").strip()
        name      = str(row.get("name")      or row.get("Name")     or row.get("VendorName") or "").strip()

        if not vendor_id:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "vendor_id", "DATA_QUALITY"))
            continue
        if not name:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "name", "DATA_QUALITY"))
            continue
        if vendor_id in seen_ids:
            rejected.append(QualityResult(row, "DUPLICATE_KEY", "vendor_id", "DATA_QUALITY"))
            continue

        seen_ids.add(vendor_id)
        valid.append(row)

    return valid, rejected


def _validate_chart_of_accounts(rows: List[Dict]) -> Tuple[List[Dict], List[QualityResult]]:
    valid: List[Dict] = []
    rejected: List[QualityResult] = []
    seen_ids: set = set()

    valid_types = {
        "asset", "liability", "equity", "revenue", "expense",
        "cost_of_goods", "income", "other", "",
    }

    for row in rows:
        account_id   = str(row.get("account_id")   or row.get("AcctId")  or row.get("AccountID") or "").strip()
        account_name = str(row.get("account_name") or row.get("Name")    or row.get("Description") or "").strip()
        account_type = str(row.get("account_type") or "").strip().lower()

        if not account_id:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "account_id", "DATA_QUALITY"))
            continue
        if not account_name:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "account_name", "DATA_QUALITY"))
            continue
        if account_type and account_type not in valid_types:
            rejected.append(QualityResult(row, "INVALID_VALUE", "account_type", "RECOVERABLE"))
            # Recoverable — include but flag
            valid.append(row)
            continue
        if account_id in seen_ids:
            rejected.append(QualityResult(row, "DUPLICATE_KEY", "account_id", "DATA_QUALITY"))
            continue

        seen_ids.add(account_id)
        valid.append(row)

    return valid, rejected


def _validate_items(rows: List[Dict]) -> Tuple[List[Dict], List[QualityResult]]:
    valid: List[Dict] = []
    rejected: List[QualityResult] = []
    seen_ids: set = set()

    for row in rows:
        item_id   = str(row.get("item_id")  or row.get("ItemId") or row.get("ItemID") or "").strip()
        item_name = str(row.get("item_name") or row.get("Name")  or row.get("Description") or "").strip()

        if not item_id:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "item_id", "DATA_QUALITY"))
            continue
        if not item_name:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "item_name", "RECOVERABLE"))
            # Recoverable — include anyway
            valid.append(row)
            continue

        # Price sanity
        for price_field in ("cost_price", "selling_price", "unit_cost"):
            raw_price = row.get(price_field)
            if raw_price is not None:
                try:
                    if float(str(raw_price).replace(",", "")) < 0:
                        rejected.append(QualityResult(row, "INVALID_VALUE", price_field, "RECOVERABLE"))
                except (ValueError, TypeError):
                    pass

        if item_id in seen_ids:
            rejected.append(QualityResult(row, "DUPLICATE_KEY", "item_id", "DATA_QUALITY"))
            continue

        seen_ids.add(item_id)
        valid.append(row)

    return valid, rejected


def _validate_stock_on_hand(rows: List[Dict]) -> Tuple[List[Dict], List[QualityResult]]:
    valid: List[Dict] = []
    rejected: List[QualityResult] = []

    for row in rows:
        item_id = str(row.get("item_id") or row.get("ItemID") or row.get("ItemId") or "").strip()
        if not item_id:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "item_id", "DATA_QUALITY"))
            continue
        valid.append(row)

    return valid, rejected


def _validate_sales_invoices(rows: List[Dict]) -> Tuple[List[Dict], List[QualityResult]]:
    valid: List[Dict] = []
    rejected: List[QualityResult] = []
    seen_ids: set = set()

    for row in rows:
        invoice_id = str(
            row.get("invoice_id") or row.get("InvoiceNo") or ""
        ).strip()

        if not invoice_id:
            rejected.append(QualityResult(row, "MISSING_REQUIRED_FIELD", "invoice_id", "DATA_QUALITY"))
            continue
        if invoice_id in seen_ids:
            rejected.append(QualityResult(row, "DUPLICATE_KEY", "invoice_id", "DATA_QUALITY"))
            continue

        # net_amount missing or zero is RECOVERABLE — amounts not yet decoded from binary
        amt_raw = row.get("net_amount") or row.get("Amount") or "0"
        try:
            if float(str(amt_raw).replace(",", "")) < 0:
                rejected.append(QualityResult(row, "INVALID_VALUE", "net_amount", "RECOVERABLE"))
        except (ValueError, TypeError):
            pass

        seen_ids.add(invoice_id)
        valid.append(row)

    return valid, rejected


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_VALIDATORS = {
    "customers":        _validate_customers,
    "vendors":          _validate_vendors,
    "chart_of_accounts": _validate_chart_of_accounts,
    "items":            _validate_items,
    "stock_on_hand":    _validate_stock_on_hand,
    "sales_invoices":   _validate_sales_invoices,
}


def validate(
    entity: str,
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[QualityResult]]:
    """Validate *rows* for *entity*.  Returns (valid_rows, rejected_results)."""
    validator = _VALIDATORS.get(entity)
    if validator is None:
        # Unknown entity — pass through without validation
        return rows, []
    return validator(rows)


def quality_summary(valid: List, rejected: List[QualityResult]) -> str:
    """Return a one-line human-readable quality summary."""
    total = len(valid) + len(rejected)
    if not rejected:
        return f"{total} read → {len(valid)} valid → 0 quarantined"
    by_severity: Dict[str, int] = {}
    for r in rejected:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
    sev_str = ", ".join(f"{k}:{v}" for k, v in by_severity.items())
    return f"{total} read → {len(valid)} valid → {len(rejected)} quarantined ({sev_str})"
