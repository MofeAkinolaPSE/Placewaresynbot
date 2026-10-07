from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.models.collaboration import StaffTaskActivity
from app.models.workspace import StaffTask

router = APIRouter(prefix='/tasks', tags=['Task Activity'])

@router.get('/{task_id}/activity')
async def task_activity(task_id: UUID, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    task = await db.scalar(select(StaffTask).where(StaffTask.id == task_id, StaffTask.organization_id == user.organization_id, StaffTask.assigned_to == user.id))
    if not task: raise HTTPException(404, 'Task not found')
    rows = await db.scalars(select(StaffTaskActivity).where(StaffTaskActivity.task_id == task_id).order_by(StaffTaskActivity.created_at.desc()))
    return list(rows.all())
