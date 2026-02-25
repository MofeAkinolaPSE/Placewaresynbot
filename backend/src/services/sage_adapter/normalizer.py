from __future__ import annotations

from typing import List, Dict, Any
from .schemas import CustomerRow, ARRow, APRow, GLRow, InventoryRow, StaffRow


def to_customers(rows: List[Dict[str, Any]]) -> List[CustomerRow]:
    out: List[CustomerRow] = []
    for r in rows:
        out.append(CustomerRow(
            customer_id=str(r.get("customer_id", "")).strip(),
            name=str(r.get("name", "")).strip(),
            email=(r.get("email") or None),
            phone=(r.get("phone") or None),
            status=(r.get("status") or None),
        ))
    return out


def to_ar(rows: List[Dict[str, Any]]) -> List[ARRow]:
    out: List[ARRow] = []
    for r in rows:
        out.append(ARRow(
            invoice_id=str(r.get("invoice_id", "")).strip(),
            customer_id=str(r.get("customer_id", "")).strip(),
            date=str(r.get("date", "")).strip(),
            due_date=(r.get("due_date") or None),
            amount=float(r.get("amount", 0) or 0),
            balance=float(r.get("balance", 0) or 0),
            status=(r.get("status") or None),
        ))
    return out


def to_ap(rows: List[Dict[str, Any]]) -> List[APRow]:
    out: List[APRow] = []
    for r in rows:
        out.append(APRow(
            bill_id=str(r.get("bill_id", "")).strip(),
            vendor_id=str(r.get("vendor_id", "")).strip(),
            date=str(r.get("date", "")).strip(),
            due_date=(r.get("due_date") or None),
            amount=float(r.get("amount", 0) or 0),
            balance=float(r.get("balance", 0) or 0),
            status=(r.get("status") or None),
        ))
    return out


def to_gl(rows: List[Dict[str, Any]]) -> List[GLRow]:
    out: List[GLRow] = []
    for r in rows:
        out.append(GLRow(
            period=str(r.get("period", "")).strip(),
            account_code=str(r.get("account_code", "")).strip(),
            account_name=str(r.get("account_name", "")).strip(),
            debit=float(r.get("debit", 0) or 0),
            credit=float(r.get("credit", 0) or 0),
        ))
    return out


def to_inventory(rows: List[Dict[str, Any]]) -> List[InventoryRow]:
    out: List[InventoryRow] = []
    for r in rows:
        qty = float(r.get("quantity", 0) or 0)
        unit_cost = r.get("unit_cost")
        unit_cost = float(unit_cost) if unit_cost not in (None, "",) else None
        valuation = r.get("valuation")
        valuation = float(valuation) if valuation not in (None, "",) else None
        out.append(InventoryRow(
            sku=str(r.get("sku", "")).strip(),
            name=str(r.get("name", "")).strip(),
            quantity=qty,
            unit_cost=unit_cost,
            valuation=valuation,
            updated_at=(r.get("updated_at") or None),
            expiry_date=(r.get("expiry_date") or None),
        ))
    return out


def to_staff(rows: List[Dict[str, Any]]) -> List[StaffRow]:
    out: List[StaffRow] = []
    for r in rows:
        out.append(StaffRow(
            staff_id=str(r.get("staff_id", "")).strip(),
            full_name=str(r.get("full_name", "")).strip(),
            email=(r.get("email") or None),
            department=(r.get("department") or None),
            role=(r.get("role") or None),
            status=(r.get("status") or None),
        ))
    return out
