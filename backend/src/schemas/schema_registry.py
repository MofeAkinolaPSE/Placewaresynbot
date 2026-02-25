from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class SchemaField(BaseModel):
    field_name: str
    data_type: str  # e.g. string, number, boolean, object, array
    required: bool = False
    source_table: Optional[str] = None
    validation_rules: Optional[Dict[str, Any]] = None
    approval_required: bool = False
    risk_weight: Optional[float] = None


class DepartmentSchema(BaseModel):
    department: str
    event_type: str
    fields: List[SchemaField]
    approval_required: bool = False
    workflow_id: Optional[str] = None
    version: int = 1
    created_by: Optional[str] = None
