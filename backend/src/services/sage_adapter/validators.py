from __future__ import annotations

import re
from typing import Sequence, Mapping

REQUIRED_CUSTOMERS = ["customer_id", "name"]
REQUIRED_AR = ["invoice_id", "customer_id", "date", "amount", "balance"]
REQUIRED_AP = ["bill_id", "vendor_id", "date", "amount", "balance"]
REQUIRED_GL = ["period", "account_code", "account_name", "debit", "credit"]
REQUIRED_INVENTORY = ["sku", "name", "quantity"]
REQUIRED_STAFF = ["staff_id", "full_name", "department"]

ALIASES_CUSTOMERS = {
    "customer_id": ["customer id", "customerid", "cust_id", "custid", "client_id", "client id"],
    "name": ["customer_name", "customer name", "client_name", "client name", "account_name"],
    "email": ["email_address", "email address", "mail"],
    "phone": ["phone_number", "phone number", "mobile", "telephone"],
    "status": ["customer_status", "state"],
}

ALIASES_AR = {
    "invoice_id": ["invoice id", "invoice_no", "invoice number", "inv_id", "inv_no"],
    "customer_id": ["customer id", "customerid", "cust_id", "client_id"],
    "date": ["invoice_date", "transaction_date", "posting_date", "txn_date"],
    "due_date": ["due date", "payment_due_date", "maturity_date"],
    "amount": ["invoice_amount", "total_amount", "gross_amount", "value"],
    "balance": ["outstanding", "outstanding_balance", "open_balance", "amount_due"],
    "status": ["invoice_status", "state"],
}

ALIASES_AP = {
    "bill_id": ["bill id", "bill_no", "bill number", "voucher_id", "voucher_no"],
    "vendor_id": ["vendor id", "supplier_id", "supplier id", "creditor_id"],
    "date": ["bill_date", "transaction_date", "posting_date", "txn_date"],
    "due_date": ["due date", "payment_due_date", "maturity_date"],
    "amount": ["bill_amount", "total_amount", "gross_amount", "value"],
    "balance": ["outstanding", "outstanding_balance", "open_balance", "amount_due"],
    "status": ["bill_status", "state"],
}

ALIASES_GL = {
    "period": ["month", "fiscal_period", "accounting_period"],
    "account_code": ["gl_code", "ledger_code", "acct_code", "account"],
    "account_name": ["gl_name", "ledger_name", "acct_name"],
    "debit": ["dr", "debit_amount", "debits"],
    "credit": ["cr", "credit_amount", "credits"],
}

ALIASES_INVENTORY = {
    "sku": ["sku_code", "item_code", "product_code", "code"],
    "name": ["item_name", "product_name", "description"],
    "quantity": ["qty", "stock", "on_hand", "quantity_on_hand"],
    "unit_cost": ["unit price", "unit_price", "cost_per_unit"],
    "valuation": ["value", "inventory_value", "stock_value"],
    "updated_at": ["updated at", "last_updated", "last_update"],
    "expiry_date": ["expiry", "exp_date", "expiration_date", "expiry date"],
}

ALIASES_STAFF = {
    "staff_id": ["employee_id", "employee id", "emp_id", "id"],
    "full_name": ["name", "employee_name", "staff_name", "employee name"],
    "email": ["email_address", "email address", "mail"],
    "department": ["dept", "team", "unit"],
    "role": ["job_title", "title", "position"],
    "status": ["employment_status", "active_status", "state"],
}

ALIASES_HR_PAYROLL = {
    "employee_id": ["staff_id", "emp_id", "employee id"],
    "salary": ["base_salary", "gross_salary", "monthly_salary"],
    "overtime_hours": ["ot_hours", "overtime", "extra_hours"],
    "overtime_rate": ["ot_rate", "overtime_pay_rate", "extra_rate"],
}

ALIASES_HR_ABSENCES = {
    "employee_id": ["staff_id", "emp_id", "employee id"],
    "date": ["absence_date", "day", "record_date"],
    "hours": ["absence_hours", "absent_hours", "time_lost_hours"],
}

ALIASES_OPS_ORDERS = {
    "order_id": ["order id", "sales_order_id", "so_id"],
    "created_at": ["created at", "order_date", "created_date"],
    "fulfilled_at": ["fulfilled at", "delivered_at", "completion_date"],
    "sku": ["sku_code", "item_code", "product_code"],
    "quantity": ["qty", "units", "order_quantity"],
}

ALIASES_OPS_DOWNTIME = {
    "machine_id": ["asset_id", "equipment_id", "machine id"],
    "started_at": ["start_time", "started at", "start_at"],
    "ended_at": ["end_time", "ended at", "end_at"],
    "minutes": ["downtime_minutes", "duration_minutes", "duration_mins"],
}

ALIASES_CRM_PIPELINE = {
    "opportunity_id": ["opportunity id", "deal_id", "pipeline_id"],
    "customer_id": ["customer id", "account_id", "client_id"],
    "amount": ["deal_amount", "value", "expected_value"],
    "stage": ["pipeline_stage", "sales_stage"],
    "status": ["deal_status", "state"],
    "close_date": ["expected_close_date", "target_close_date", "close date"],
}


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _build_lookup(required: Sequence[str], aliases: Mapping[str, Sequence[str]] | None = None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for field in required:
        lookup[_normalize_header(field)] = field
    for canonical, values in (aliases or {}).items():
        lookup[_normalize_header(canonical)] = canonical
        for v in values:
            lookup[_normalize_header(v)] = canonical
    return lookup


def resolve_headers(
    headers: Sequence[str],
    required: Sequence[str],
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> tuple[dict[str, str], list[str], list[str], list[str]]:
    lookup = _build_lookup(required=required, aliases=aliases)
    mapping: dict[str, str] = {}
    seen_canonical: set[str] = set()
    unknown: list[str] = []
    duplicates: list[str] = []

    for raw in headers:
        normalized = _normalize_header(raw)
        canonical = lookup.get(normalized)
        if not canonical and normalized.startswith("v"):
            canonical = lookup.get(normalized[1:])
        if not canonical:
            unknown.append(raw)
            continue
        if canonical in seen_canonical:
            duplicates.append(raw)
            continue
        mapping[raw] = canonical
        seen_canonical.add(canonical)

    missing = [field for field in required if field not in seen_canonical]
    return mapping, missing, unknown, duplicates


def canonicalize_rows(rows: Sequence[Mapping[str, object]], header_map: Mapping[str, str]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        canonical: dict[str, object] = {}
        for raw_key, value in row.items():
            mapped = header_map.get(str(raw_key))
            if mapped:
                canonical[mapped] = value
        out.append(canonical)
    return out


def validate_headers(
    headers: Sequence[str],
    required: Sequence[str],
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> bool:
    _, missing, _, _ = resolve_headers(headers=headers, required=required, aliases=aliases)
    return not missing
