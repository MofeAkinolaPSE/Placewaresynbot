from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.collaboration import StaffRequest, StaffRequestMessage, StaffRequestActivity
from app.repositories.collaboration import CollaborationRepository
from app.schemas.collaboration import RequestCreate, RequestMessageCreate

ALLOWED = {
    'sent': {'acknowledged','in_progress','cancelled'},
    'acknowledged': {'in_progress','responded','cancelled'},
    'in_progress': {'responded','closed','cancelled'},
    'responded': {'closed','in_progress'},
    'closed': {'in_progress'},
    'cancelled': {'sent'},
    'draft': {'sent','cancelled'},
}

class CollaborationService:
    def __init__(self, db: AsyncSession): self.db = db; self.repo = CollaborationRepository(db)

    async def create(self, actor_id: UUID, org_id: UUID, company_id: UUID | None, payload: RequestCreate):
        if not payload.recipient_id and not payload.team_id: raise HTTPException(422, 'recipient_id or team_id is required')
        row = StaffRequest(id=uuid4(), organization_id=org_id, company_id=company_id, requester_id=actor_id, status='sent', **payload.model_dump())
        self.db.add(row); await self.db.flush()
        self.db.add(StaffRequestActivity(id=uuid4(), request_id=row.id, actor_id=actor_id, activity_type='created'))
        return row

    async def transition(self, request_id: UUID, actor_id: UUID, org_id: UUID, target: str):
        row = await self.repo.get(request_id, actor_id, org_id)
        if not row: raise HTTPException(404, 'Request not found')
        if target not in ALLOWED.get(row.status, set()): raise HTTPException(409, f'Cannot move request from {row.status} to {target}')
        row.status = target
        if target == 'closed': row.completed_at = datetime.now(timezone.utc)
        elif target == 'in_progress': row.completed_at = None
        self.db.add(StaffRequestActivity(id=uuid4(), request_id=row.id, actor_id=actor_id, activity_type=f'status_{target}'))
        await self.db.flush(); return row

    async def add_message(self, request_id: UUID, actor_id: UUID, org_id: UUID, payload: RequestMessageCreate):
        row = await self.repo.get(request_id, actor_id, org_id)
        if not row: raise HTTPException(404, 'Request not found')
        msg = StaffRequestMessage(id=uuid4(), request_id=request_id, sender_id=actor_id, message=payload.message)
        self.db.add(msg)
        self.db.add(StaffRequestActivity(id=uuid4(), request_id=request_id, actor_id=actor_id, activity_type='message_added'))
        if row.status == 'acknowledged': row.status = 'in_progress'
        await self.db.flush(); return msg
