from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ActivityItem(BaseModel):
    event_id: Optional[str]
    timestamp: str
    department: str
    event_type: str
    summary: str
    payload: Dict[str, Any]


class PendingApproval(BaseModel):
    event_id: Optional[str]
    event_type: str
    created_by: Optional[str]
    timestamp: str
    reason: Optional[str]


class TaskItem(BaseModel):
    task_id: str
    title: str
    description: Optional[str]
    assigned_to: Optional[str]
    status: str
    priority: Optional[str] = None
    due_date: Optional[str]


class KPIWidget(BaseModel):
    key: str
    label: str
    value: Any

class AssignedProjectItem(BaseModel):
    project_id: str
    name: str
    status: str
    workflow_stage: Optional[str]
    activity_type: Optional[str]
    supplier_name: Optional[str]
    quality_check_status: Optional[str]
    nafdac_sampling_status: Optional[str]
    updated_at: Optional[str]


class Badge(BaseModel):
    id: str
    name: str
    description: Optional[str]


class StaffIdentity(BaseModel):
    email: str
    display_name: str
    staff_id: Optional[str]
    department: Optional[str]
    linked: bool
    hours_this_week: float


class StaffDashboard(BaseModel):
    user_id: str
    identity: StaffIdentity
    activities: List[ActivityItem] = []
    pending_approvals: List[PendingApproval] = []
    tasks: List[TaskItem] = []
    assigned_projects: List[AssignedProjectItem] = []
    kpis: List[KPIWidget] = []
    badges: List[Badge] = []
