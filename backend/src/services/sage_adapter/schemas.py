from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List


class ImportMeta(BaseModel):
    source_system: str = Field(default="sage50")
    batch_id: str
    imported_at: str  # ISO8601


class CustomerRow(BaseModel):
    customer_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None


class ARRow(BaseModel):
    invoice_id: str
    customer_id: str
    date: str
    due_date: Optional[str] = None
    amount: float
    balance: float
    status: Optional[str] = None


class APRow(BaseModel):
    bill_id: str
    vendor_id: str
    date: str
    due_date: Optional[str] = None
    amount: float
    balance: float
    status: Optional[str] = None


class GLRow(BaseModel):
    period: str
    account_code: str
    account_name: str
    debit: float
    credit: float


class InventoryRow(BaseModel):
    sku: str
    name: str
    quantity: float
    unit_cost: Optional[float] = None
    valuation: Optional[float] = None
    updated_at: Optional[str] = None
    expiry_date: Optional[str] = None


class StaffRow(BaseModel):
    staff_id: str
    full_name: str
    email: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


class ImportBundle(BaseModel):
    meta: ImportMeta
    customers: List[CustomerRow] = []
    ar: List[ARRow] = []
    ap: List[APRow] = []
    gl: List[GLRow] = []
    inventory: List[InventoryRow] = []
    staff: List[StaffRow] = []
