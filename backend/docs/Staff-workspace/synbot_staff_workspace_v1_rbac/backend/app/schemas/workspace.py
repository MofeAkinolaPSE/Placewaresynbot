from datetime import datetime
from typing import Optional, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal['inbox','accepted','in_progress','waiting','completed','verified','closed','cancelled']
TaskPriority = Literal['low','normal','high','critical']
TaskSource = Literal['manual','assigned','operational','recurring','request','automation','ai']

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[UUID] = None
    company_id: Optional[UUID] = None
    subsidiary_id: Optional[UUID] = None
    facility_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    priority: TaskPriority = 'normal'
    source_type: TaskSource = 'manual'
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    start_at: Optional[datetime] = None
    due_at: Optional[datetime] = None

class TaskPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[UUID] = None
    priority: Optional[TaskPriority] = None
    due_at: Optional[datetime] = None

class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: Optional[str]
    assigned_to: Optional[UUID]
    status: TaskStatus
    priority: TaskPriority
    source_type: TaskSource
    entity_type: Optional[str]
    entity_id: Optional[str]
    start_at: Optional[datetime]
    due_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

class TimeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    total_seconds: Optional[int]

class WorkspaceRead(BaseModel):
    staff: dict
    summary: dict
    tasks: list[TaskRead]
    notifications: list[dict]
    active_time: Optional[TimeRead]
