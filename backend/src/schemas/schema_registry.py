from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any


class SchemaField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field_name: str = Field(..., max_length=100)
    data_type: str = Field(..., max_length=20)  # string, number, boolean, object, array
    required: bool = False
    source_table: Optional[str] = Field(None, max_length=100)
    validation_rules: Optional[Dict[str, Any]] = None
    approval_required: bool = False
    risk_weight: Optional[float] = Field(None, ge=0.0, le=1.0)


class DepartmentSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    department: str = Field(..., max_length=100)
    event_type: str = Field(..., max_length=100)
    fields: List[SchemaField] = Field(..., max_length=200)
    approval_required: bool = False
    workflow_id: Optional[str] = Field(None, max_length=64)
    version: int = Field(1, ge=1)
    created_by: Optional[str] = Field(None, max_length=100)
