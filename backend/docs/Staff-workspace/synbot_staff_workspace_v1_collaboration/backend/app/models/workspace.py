from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID, ENUM
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


task_status = ENUM('inbox','accepted','in_progress','waiting','completed','verified','closed','cancelled', name='task_status', create_type=False)
task_priority = ENUM('low','normal','high','critical', name='task_priority', create_type=False)
task_source_type = ENUM('manual','assigned','operational','recurring','request','automation','ai', name='task_source_type', create_type=False)
time_session_status = ENUM('active','paused','completed', name='time_session_status', create_type=False)
workspace_status = ENUM('active','inactive','archived', name='workspace_status', create_type=False)

class Base(DeclarativeBase):
    pass

class Staff(Base):
    __tablename__ = 'staff'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    company_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    subsidiary_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    facility_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    department_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    primary_team_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text, index=True)
    designation: Mapped[Optional[str]] = mapped_column(Text)

class StaffCompanyMembership(Base):
    __tablename__ = 'staff_company_memberships'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    staff_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    subsidiary_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    facility_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    department_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(workspace_status, nullable=False, default='active')

class StaffTask(Base):
    __tablename__ = 'staff_tasks'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    company_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    subsidiary_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    facility_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    department_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    team_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'))
    assigned_to: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(task_status, nullable=False, default='inbox', index=True)
    priority: Mapped[str] = mapped_column(task_priority, nullable=False, default='normal')
    source_type: Mapped[str] = mapped_column(task_source_type, nullable=False, default='manual')
    entity_type: Mapped[Optional[str]] = mapped_column(Text)
    entity_id: Mapped[Optional[str]] = mapped_column(Text)
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class StaffNotification(Base):
    __tablename__ = 'staff_notifications'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    staff_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(task_priority, nullable=False, default='normal')
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
    entity_type: Mapped[Optional[str]] = mapped_column(Text)
    entity_id: Mapped[Optional[str]] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

class StaffTimeSession(Base):
    __tablename__ = 'staff_time_sessions'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    staff_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    company_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    facility_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(time_session_status, nullable=False, default='active', index=True)
    total_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
