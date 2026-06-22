from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class Document(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    approval_status: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    current_version: Optional[str] = None


class DocumentVersion(BaseModel):
    id: str
    document_id: str
    version_number: int
    storage_path: str
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[str] = None
    checksum: Optional[str] = None


class AttachRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    attached_to_table: Optional[str] = Field(None, max_length=100)
    attached_to_id: Optional[str] = Field(None, max_length=64)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approval_status: str = Field(..., description="approved|rejected|under_review", max_length=20)
    reason: Optional[str] = Field(None, max_length=1000)
