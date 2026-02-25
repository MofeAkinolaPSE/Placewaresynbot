from pydantic import BaseModel, Field
from typing import Optional


class DocumentCreate(BaseModel):
    title: str
    description: Optional[str] = None


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
    attached_to_table: Optional[str] = None
    attached_to_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    approval_status: str = Field(..., description="approved|rejected|under_review")
    reason: Optional[str] = None
