from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.models.workspace import StaffNotification

router = APIRouter(prefix='/notifications', tags=['Notifications'])

@router.get('')
async def notifications(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    rows = list((await db.scalars(select(StaffNotification).where(StaffNotification.staff_id == user.id).order_by(StaffNotification.created_at.desc()).limit(50))).all())
    return rows

@router.post('/{notification_id}/read')
async def mark_read(notification_id: UUID, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    row = await db.scalar(select(StaffNotification).where(StaffNotification.id == notification_id, StaffNotification.staff_id == user.id))
    if not row: raise HTTPException(404, 'Notification not found')
    row.is_read = True; row.read_at = datetime.now(timezone.utc); await db.commit()
    return {'ok': True}
