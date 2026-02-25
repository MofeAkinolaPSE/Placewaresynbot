from pydantic import BaseModel
from typing import Optional, Dict, Any


class Supplier(BaseModel):
    name: str
    category: Optional[str] = None
    contact: Optional[Dict[str, Any]] = None


class SupplierDelivery(BaseModel):
    supplier_id: str
    scheduled_at: Optional[str] = None
    delivered_at: Optional[str] = None
    on_time: Optional[bool] = None
    price: Optional[float] = None
