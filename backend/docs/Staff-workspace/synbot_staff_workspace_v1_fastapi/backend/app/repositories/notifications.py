from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import StaffNotification

class NotificationRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def unread(self, staff_id: UUID, limit: int = 20):
        stmt = select(StaffNotification).where(StaffNotification.staff_id == staff_id, StaffNotification.is_read.is_(False)).order_by(StaffNotification.created_at.desc()).limit(limit)
        return list((await self.db.scalars(stmt)).all())
