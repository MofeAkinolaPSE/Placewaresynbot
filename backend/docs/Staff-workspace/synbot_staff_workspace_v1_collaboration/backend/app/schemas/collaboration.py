from datetime import datetime
from typing import Optional, Literal
from uuid import UUID
from pydantic import BaseModel, Field

RequestType = Literal['information','action','approval','handoff']
RequestStatus = Literal['draft','sent','acknowledged','in_progress','responded','closed','cancelled']
Priority = Literal['low','normal','high','critical']

class RequestCreate(BaseModel):
    recipient_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    request_type: RequestType = 'information'
    title: str = Field(min_length=1, max_length=240)
    description: Optional[str] = None
    related_task_id: Optional[UUID] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    priority: Priority = 'normal'
    due_at: Optional[datetime] = None

class RequestRead(BaseModel):
    id: UUID
    organization_id: UUID
    company_id: Optional[UUID]
    subsidiary_id: Optional[UUID]
    requester_id: UUID
    recipient_id: Optional[UUID]
    team_id: Optional[UUID]
    request_type: str
    title: str
    description: Optional[str]
    related_task_id: Optional[UUID]
    entity_type: Optional[str]
    entity_id: Optional[str]
    priority: str
    status: str
    due_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    model_config = {'from_attributes': True}

class RequestMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=5000)

class RequestMessageRead(BaseModel):
    id: UUID
    request_id: UUID
    sender_id: UUID
    message: str
    created_at: datetime
    model_config = {'from_attributes': True}

class ActivityRead(BaseModel):
    id: UUID
    request_id: UUID
    actor_id: Optional[UUID]
    activity_type: str
    metadata: Optional[dict]
    created_at: datetime
    model_config = {'from_attributes': True}
