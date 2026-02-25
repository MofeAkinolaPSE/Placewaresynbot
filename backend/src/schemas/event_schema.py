from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class EventPayload(BaseModel):
    department: str = Field(..., description="Owning department name")
    event_type: str = Field(..., description="Type of event, e.g. StockIn, Delivered")
    linked_project_id: Optional[str] = Field(None)
    linked_customer_id: Optional[str] = Field(None)
    linked_supplier_id: Optional[str] = Field(None)
    payload: Dict[str, Any] = Field(..., description="Structured JSON payload validated by Schema Registry")
    status: str = Field("draft")
    created_by: Optional[str] = Field(None)
    timestamp: Optional[datetime] = Field(None)
    approval_status: Optional[str] = Field(None)
    risk_score: Optional[float] = Field(None)
    version_hash: Optional[str] = Field(None)
