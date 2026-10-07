from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import StaffTimeSession

class TimeRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def active(self, staff_id: UUID):
        stmt = select(StaffTimeSession).where(StaffTimeSession.staff_id == staff_id, StaffTimeSession.status.in_(['active','paused'])).order_by(StaffTimeSession.started_at.desc())
        return await self.db.scalar(stmt)
