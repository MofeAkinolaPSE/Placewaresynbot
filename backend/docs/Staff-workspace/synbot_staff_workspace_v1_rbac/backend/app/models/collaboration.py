from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID, ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .workspace import Base

request_type = ENUM('information','action','approval','handoff', name='request_type', create_type=False)
request_status = ENUM('draft','sent','acknowledged','in_progress','responded','closed','cancelled', name='request_status', create_type=False)
task_priority = ENUM('low','normal','high','critical', name='task_priority', create_type=False)

class StaffRequest(Base):
    __tablename__ = 'staff_requests'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    company_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    subsidiary_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    requester_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    recipient_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'), index=True)
    team_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    request_type: Mapped[str] = mapped_column(request_type, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    related_task_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff_tasks.id', ondelete='SET NULL'))
    entity_type: Mapped[Optional[str]] = mapped_column(Text)
    entity_id: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(task_priority, nullable=False, default='normal')
    status: Mapped[str] = mapped_column(request_status, nullable=False, default='sent', index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class StaffRequestMessage(Base):
    __tablename__ = 'staff_request_messages'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff_requests.id', ondelete='CASCADE'), index=True)
    sender_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class StaffRequestActivity(Base):
    __tablename__ = 'staff_request_activity'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff_requests.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'))
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    activity_metadata: Mapped[Optional[dict]] = mapped_column('metadata', JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class StaffTaskActivity(Base):
    __tablename__ = 'staff_task_activity'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff_tasks.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey('staff.id'))
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_value: Mapped[Optional[dict]] = mapped_column(JSONB)
    activity_metadata: Mapped[Optional[dict]] = mapped_column('metadata', JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
