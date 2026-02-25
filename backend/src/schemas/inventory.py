from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class InventoryItem(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    unit: Optional[str] = 'each'


class StockLevel(BaseModel):
    item_id: str
    location: str
    quantity: float


class InventoryMovement(BaseModel):
    item_id: str
    change: float
    movement_type: str
    source: Optional[str] = None
    destination: Optional[str] = None
    created_by: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class InventoryRequest(BaseModel):
    requester: Optional[str] = None
    item_id: str
    quantity: float
    status: Optional[str] = 'pending'
