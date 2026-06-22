from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class Supplier(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(..., max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[str] = Field(None, max_length=254)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)
    payment_terms: Optional[str] = Field(None, max_length=100)
    tax_id: Optional[str] = Field(None, max_length=50)
    bank_details: Optional[str] = Field(None, max_length=500)
    current_balance: Optional[float] = None
    status: Optional[str] = Field("active", max_length=20)


class SupplierDelivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    supplier_id: str = Field(..., max_length=64)
    scheduled_at: Optional[str] = Field(None, max_length=32)
    delivered_at: Optional[str] = Field(None, max_length=32)
    on_time: Optional[bool] = None
    price: Optional[float] = None
