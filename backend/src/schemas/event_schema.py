from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime


class EventPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    department: str = Field(..., max_length=100, description="Owning department name")
    event_type: str = Field(..., max_length=100, description="Type of event, e.g. StockIn, Delivered")
    linked_project_id: Optional[str] = Field(None, max_length=64)
    linked_customer_id: Optional[str] = Field(None, max_length=64)
    linked_supplier_id: Optional[str] = Field(None, max_length=64)
    payload: Dict[str, Any] = Field(..., description="Structured JSON payload validated by Schema Registry")
    status: str = Field("draft", max_length=20)
    created_by: Optional[str] = Field(None, max_length=100)
    timestamp: Optional[datetime] = Field(None)
    approval_status: Optional[str] = Field(None, max_length=20)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    version_hash: Optional[str] = Field(None, max_length=128)
