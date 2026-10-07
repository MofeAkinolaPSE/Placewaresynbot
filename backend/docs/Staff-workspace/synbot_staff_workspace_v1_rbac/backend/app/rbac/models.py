from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.workspace import Base, workspace_status

class Role(Base):
    __tablename__ = 'roles'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

class Permission(Base):
    __tablename__ = 'permissions'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)

class RolePermission(Base):
    __tablename__ = 'role_permissions'
    role_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
    permission_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)

class StaffCompanyMembershipRBAC(Base):
    __tablename__ = 'staff_company_memberships'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    staff_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    subsidiary_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    facility_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    department_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    role_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey('roles.id'), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(workspace_status, nullable=False, default='active')
