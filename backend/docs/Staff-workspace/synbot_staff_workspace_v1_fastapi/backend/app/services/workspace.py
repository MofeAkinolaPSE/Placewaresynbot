from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import Staff
from app.repositories.tasks import TaskRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.time import TimeRepository

class WorkspaceService:
    def __init__(self, db: AsyncSession):
        self.db = db; self.tasks = TaskRepository(db); self.notifications = NotificationRepository(db); self.time = TimeRepository(db)

    async def get(self, staff_id: UUID, org_id: UUID, company_id: UUID | None):
        staff = await self.db.scalar(select(Staff).where(Staff.id == staff_id, Staff.organization_id == org_id))
        if not staff: return None
        tasks = await self.tasks.list_for_staff(staff_id, org_id, company_id, limit=20)
        counts = await self.tasks.counts(staff_id, org_id)
        notifications = await self.notifications.unread(staff_id)
        active = await self.time.active(staff_id)
        return {
            'staff': {'id': str(staff.id), 'name': staff.display_name or f'{staff.first_name} {staff.last_name}', 'designation': staff.designation, 'company_id': str(company_id) if company_id else None},
            'summary': {'inbox': counts.get('inbox',0), 'accepted': counts.get('accepted',0), 'in_progress': counts.get('in_progress',0), 'waiting': counts.get('waiting',0), 'completed': counts.get('completed',0), 'unread_notifications': len(notifications)},
            'tasks': tasks,
            'notifications': [{'id': str(n.id), 'type': n.notification_type, 'priority': n.priority, 'title': n.title, 'message': n.message, 'entity_type': n.entity_type, 'entity_id': n.entity_id, 'created_at': n.created_at} for n in notifications],
            'active_time': active,
        }
