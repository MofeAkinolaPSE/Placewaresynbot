from uuid import UUID
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.collaboration import StaffRequest, StaffRequestMessage, StaffRequestActivity

class CollaborationRepository:
    def __init__(self, db: AsyncSession): self.db = db

    async def list_for_staff(self, staff_id: UUID, org_id: UUID, company_id: UUID | None = None):
        q = select(StaffRequest).where(StaffRequest.organization_id == org_id, or_(StaffRequest.requester_id == staff_id, StaffRequest.recipient_id == staff_id))
        if company_id: q = q.where(or_(StaffRequest.company_id == company_id, StaffRequest.company_id.is_(None)))
        return list((await self.db.scalars(q.order_by(StaffRequest.updated_at.desc()))).all())

    async def get(self, request_id: UUID, staff_id: UUID, org_id: UUID):
        q = select(StaffRequest).where(StaffRequest.id == request_id, StaffRequest.organization_id == org_id, or_(StaffRequest.requester_id == staff_id, StaffRequest.recipient_id == staff_id))
        return await self.db.scalar(q)

    async def messages(self, request_id: UUID):
        q = select(StaffRequestMessage).where(StaffRequestMessage.request_id == request_id).order_by(StaffRequestMessage.created_at.asc())
        return list((await self.db.scalars(q)).all())

    async def activity(self, request_id: UUID):
        q = select(StaffRequestActivity).where(StaffRequestActivity.request_id == request_id).order_by(StaffRequestActivity.created_at.desc())
        return list((await self.db.scalars(q)).all())
