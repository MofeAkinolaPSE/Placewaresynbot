from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any


class Rider(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(..., max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    vehicle: Optional[str] = Field(None, max_length=50)


class Delivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference: Optional[str] = Field(None, max_length=100)
    customer_id: Optional[str] = Field(None, max_length=64)
    address: Optional[Dict[str, Any]] = None
    quantity: Optional[float] = Field(None, ge=0)
    status: Optional[str] = Field('unassigned', max_length=20)


class Route(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rider_id: str = Field(..., max_length=64)
    deliveries: List[str] = Field(..., max_length=200)
    route_meta: Optional[Dict[str, Any]] = None
