from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from enum import Enum


class MovementType(str, Enum):
    purchase = "purchase"
    sale = "sale"
    adjustment = "adjustment"
    transfer = "transfer"
    write_off = "write_off"


class InventoryItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sku: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    unit: Optional[str] = Field('each', max_length=20)


class StockLevel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(..., max_length=64)
    location: str = Field(..., max_length=100)
    quantity: float


class InventoryMovement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(..., max_length=64)
    change: float
    movement_type: MovementType
    source: Optional[str] = Field(None, max_length=100)
    destination: Optional[str] = Field(None, max_length=100)
    created_by: Optional[str] = Field(None, max_length=100)
    metadata: Optional[Dict[str, Any]] = None


class InventoryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requester: Optional[str] = Field(None, max_length=100)
    item_id: str = Field(..., max_length=64)
    quantity: float = Field(..., gt=0)
    status: Optional[str] = Field('pending', max_length=20)
