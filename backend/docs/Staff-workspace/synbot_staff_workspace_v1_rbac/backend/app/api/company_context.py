from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.rbac.models import StaffCompanyMembershipRBAC
from app.rbac.access import build_access_context

router = APIRouter(prefix='/company-context', tags=['Company Context'])

@router.get('')
async def company_context(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    memberships = list((await db.scalars(
        select(StaffCompanyMembershipRBAC).where(
            StaffCompanyMembershipRBAC.staff_id == user.id,
            StaffCompanyMembershipRBAC.status == 'active',
        ).order_by(StaffCompanyMembershipRBAC.is_primary.desc())
    )).all())
    if not memberships:
        from fastapi import HTTPException
        raise HTTPException(403, 'No active company memberships')
    access = await build_access_context(db, user)
    return {
        'selected_company_id': str(access.company_id) if access.company_id else None,
        'memberships': [
            {
                'company_id': str(m.company_id),
                'subsidiary_id': str(m.subsidiary_id) if m.subsidiary_id else None,
                'facility_id': str(m.facility_id) if m.facility_id else None,
                'department_id': str(m.department_id) if m.department_id else None,
                'role_id': str(m.role_id) if m.role_id else None,
                'is_primary': m.is_primary,
            }
            for m in memberships
        ],
    }
