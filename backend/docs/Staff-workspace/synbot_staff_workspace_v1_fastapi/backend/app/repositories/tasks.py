from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import StaffTask

class TaskRepository:
    def __init__(self, db: AsyncSession): self.db = db

    async def list_for_staff(self, staff_id: UUID, organization_id: UUID, company_id: UUID | None = None, limit: int = 50):
        stmt = select(StaffTask).where(
            StaffTask.organization_id == organization_id,
            (StaffTask.assigned_to == staff_id) | (StaffTask.created_by == staff_id),
        )
        if company_id:
            stmt = stmt.where((StaffTask.company_id == company_id) | (StaffTask.company_id.is_(None)))
        stmt = stmt.order_by(StaffTask.due_at.asc().nullslast(), StaffTask.created_at.desc()).limit(limit)
        return list((await self.db.scalars(stmt)).all())

    async def get_for_staff(self, task_id: UUID, staff_id: UUID, organization_id: UUID):
        stmt = select(StaffTask).where(
            StaffTask.id == task_id,
            StaffTask.organization_id == organization_id,
            (StaffTask.assigned_to == staff_id) | (StaffTask.created_by == staff_id),
        )
        return await self.db.scalar(stmt)

    async def counts(self, staff_id: UUID, organization_id: UUID):
        stmt = select(StaffTask.status, func.count(StaffTask.id)).where(
            StaffTask.organization_id == organization_id,
            StaffTask.assigned_to == staff_id,
        ).group_by(StaffTask.status)
        return {status: count for status, count in (await self.db.execute(stmt)).all()}
