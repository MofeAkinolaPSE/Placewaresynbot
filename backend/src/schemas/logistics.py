from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class Rider(BaseModel):
    name: str
    phone: Optional[str] = None
    vehicle: Optional[str] = None


class Delivery(BaseModel):
    reference: Optional[str] = None
    customer_id: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    quantity: Optional[float] = None
    status: Optional[str] = 'unassigned'


class Route(BaseModel):
    rider_id: str
    deliveries: List[str]
    route_meta: Optional[Dict[str, Any]] = None
