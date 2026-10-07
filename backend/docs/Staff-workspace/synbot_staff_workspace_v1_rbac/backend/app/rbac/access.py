from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.rbac.models import StaffCompanyMembershipRBAC, RolePermission, Permission

@dataclass(frozen=True)
class AccessContext:
    staff_id: UUID
    organization_id: UUID
    company_id: UUID | None
    subsidiary_id: UUID | None
    facility_id: UUID | None
    department_id: UUID | None
    permissions: frozenset[str]

    def can(self, resource: str, action: str) -> bool:
        return f'{resource}:{action}' in self.permissions

async def build_access_context(db: AsyncSession, user: CurrentStaff) -> AccessContext:
    q = select(StaffCompanyMembershipRBAC).where(
        StaffCompanyMembershipRBAC.staff_id == user.id,
        StaffCompanyMembershipRBAC.status == 'active',
    )
    if user.company_id:
        q = q.where(StaffCompanyMembershipRBAC.company_id == user.company_id)
    memberships = list((await db.scalars(q)).all())
    if user.company_id and not memberships:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='No active membership for selected company')
    if not memberships and not user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='No active company membership')

    role_ids = [m.role_id for m in memberships if m.role_id]
    permissions: set[str] = set()
    if role_ids:
        rows = await db.execute(
            select(Permission.resource, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(role_ids))
        )
        permissions = {f'{resource}:{action}' for resource, action in rows.all()}

    selected = next((m for m in memberships if user.company_id and m.company_id == user.company_id), None) or next((m for m in memberships if m.is_primary), memberships[0])
    return AccessContext(
        staff_id=user.id,
        organization_id=user.organization_id,
        company_id=user.company_id or selected.company_id,
        subsidiary_id=selected.subsidiary_id,
        facility_id=selected.facility_id,
        department_id=selected.department_id,
        permissions=frozenset(permissions),
    )

def require_permission(resource: str, action: str, *, write: bool = False):
    async def dependency(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)) -> AccessContext:
        access = await build_access_context(db, user)
        if write and user.company_id is None:
            raise HTTPException(status_code=400, detail='A company context is required for this action')
        if not access.can(resource, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'Missing permission: {resource}:{action}')
        return access
    return dependency

async def require_company_scope(db: AsyncSession, access: AccessContext, company_id: UUID | None, *, write: bool = False):
    if company_id is None:
        if write:
            raise HTTPException(status_code=400, detail='Company scope is required')
        return
    if access.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Resource is outside your company scope')
