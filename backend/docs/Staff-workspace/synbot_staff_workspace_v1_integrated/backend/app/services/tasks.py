from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import StaffTask
from app.repositories.tasks import TaskRepository
from app.schemas.workspace import TaskCreate, TaskPatch

ALLOWED = {
    'inbox': {'accepted','cancelled'},
    'accepted': {'in_progress','cancelled'},
    'in_progress': {'waiting','completed','cancelled'},
    'waiting': {'in_progress','cancelled'},
    'completed': {'verified','reopened'},
    'verified': {'closed','reopened'},
    'closed': {'reopened'},
    'cancelled': {'reopened'},
}

class TaskService:
    def __init__(self, db: AsyncSession): self.db = db; self.repo = TaskRepository(db)

    async def create(self, actor_id: UUID, org_id: UUID, payload: TaskCreate):
        task = StaffTask(id=uuid4(), organization_id=org_id, created_by=actor_id, status='inbox', **payload.model_dump())
        self.db.add(task); await self.db.flush(); return task

    async def update(self, task_id: UUID, actor_id: UUID, org_id: UUID, payload: TaskPatch):
        task = await self.repo.get_for_staff(task_id, actor_id, org_id)
        if not task: raise HTTPException(404, 'Task not found')
        for key, value in payload.model_dump(exclude_unset=True).items(): setattr(task, key, value)
        await self.db.flush(); return task

    async def transition(self, task_id: UUID, actor_id: UUID, org_id: UUID, target: str):
        task = await self.repo.get_for_staff(task_id, actor_id, org_id)
        if not task: raise HTTPException(404, 'Task not found')
        if target == 'reopened': target = 'in_progress'
        if target not in ALLOWED.get(task.status, set()): raise HTTPException(409, f'Cannot move task from {task.status} to {target}')
        task.status = target
        now = datetime.now(timezone.utc)
        if target == 'completed': task.completed_at = now
        elif target == 'verified': task.verified_at = now
        elif target == 'closed': task.closed_at = now
        elif target == 'in_progress' and task.completed_at: task.completed_at = None
        await self.db.flush(); return task
