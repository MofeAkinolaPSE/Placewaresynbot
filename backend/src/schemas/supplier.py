from pydantic import BaseModel
from typing import Optional


class Supplier(BaseModel):
    name: str
    category: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_terms: Optional[str] = None
    tax_id: Optional[str] = None
    bank_details: Optional[str] = None
    current_balance: Optional[float] = None
    status: Optional[str] = "active"


class SupplierDelivery(BaseModel):
    supplier_id: str
    scheduled_at: Optional[str] = None
    delivered_at: Optional[str] = None
    on_time: Optional[bool] = None
    price: Optional[float] = None
