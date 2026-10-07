from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import StaffTimeSession
from app.repositories.time import TimeRepository

class TimeService:
    def __init__(self, db: AsyncSession): self.db = db; self.repo = TimeRepository(db)

    async def start(self, staff_id: UUID, company_id: UUID | None = None):
        current = await self.repo.active(staff_id)
        if current: raise HTTPException(409, 'A work session is already active')
        row = StaffTimeSession(id=uuid4(), staff_id=staff_id, company_id=company_id, started_at=datetime.now(timezone.utc), status='active')
        self.db.add(row); await self.db.flush(); return row

    async def pause(self, staff_id: UUID):
        row = await self.repo.active(staff_id)
        if not row or row.status != 'active': raise HTTPException(409, 'No active work session')
        row.status = 'paused'; await self.db.flush(); return row

    async def resume(self, staff_id: UUID):
        row = await self.repo.active(staff_id)
        if not row or row.status != 'paused': raise HTTPException(409, 'No paused work session')
        row.status = 'active'; await self.db.flush(); return row

    async def end(self, staff_id: UUID):
        row = await self.repo.active(staff_id)
        if not row: raise HTTPException(409, 'No active work session')
        now = datetime.now(timezone.utc)
        row.ended_at = now; row.status = 'completed'
        row.total_seconds = max(0, int((now - row.started_at).total_seconds()))
        await self.db.flush(); return row
