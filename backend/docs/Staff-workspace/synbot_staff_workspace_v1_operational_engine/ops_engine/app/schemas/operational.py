from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class OperationalEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(min_length=1, max_length=120)
    entity_id: str = Field(min_length=1, max_length=120)
    company_id: int
    facility_id: int | None = None
    department_id: int | None = None
    team_id: int | None = None
    actor_staff_id: int | None = None
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

class RuleCreate(BaseModel):
    name: str
    event_type: str
    entity_type: str | None = None
    company_id: int | None = None
    title_template: str
    description_template: str | None = None
    source_type: Literal['operational'] = 'operational'
    priority: Literal['low','normal','high','critical'] = 'normal'
    assign_mode: Literal['staff','role','team','department','facility','event_actor'] = 'team'
    assign_value: str | None = None
    due_minutes: int | None = Field(default=None, ge=0)
    enabled: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)

class TaskGenerationResult(BaseModel):
    event_id: str
    matched_rules: int
    created_task_ids: list[str]
    skipped_task_ids: list[str] = Field(default_factory=list)
