from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.rbac.access import AccessContext, build_access_context

router = APIRouter(prefix='/access', tags=['Access'])

@router.get('/me')
async def access_me(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    access: AccessContext = await build_access_context(db, user)
    return {
        'staff_id': str(access.staff_id),
        'organization_id': str(access.organization_id),
        'company_id': str(access.company_id) if access.company_id else None,
        'subsidiary_id': str(access.subsidiary_id) if access.subsidiary_id else None,
        'facility_id': str(access.facility_id) if access.facility_id else None,
        'department_id': str(access.department_id) if access.department_id else None,
        'permissions': sorted(access.permissions),
    }
