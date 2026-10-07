-- Synbot Staff Workspace v1
-- Generic workspace layer for multi-company Synbot deployments.
-- Safe by design: does not modify existing Royan clinical tables.
-- PostgreSQL 14+

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- ENUMS
-- ============================================================

DO $$ BEGIN
    CREATE TYPE workspace_status AS ENUM ('active', 'inactive', 'archived');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE staff_employment_status AS ENUM ('active', 'on_leave', 'suspended', 'terminated');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE task_status AS ENUM (
        'inbox',
        'accepted',
        'in_progress',
        'waiting',
        'completed',
        'verified',
        'closed',
        'cancelled'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE task_priority AS ENUM ('low', 'normal', 'high', 'critical');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE task_source_type AS ENUM (
        'manual',
        'assigned',
        'operational',
        'recurring',
        'request',
        'automation',
        'ai'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE request_type AS ENUM ('information', 'action', 'approval', 'handoff');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE request_status AS ENUM (
        'draft',
        'sent',
        'acknowledged',
        'in_progress',
        'responded',
        'closed',
        'cancelled'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE time_session_status AS ENUM ('active', 'paused', 'completed');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- ============================================================
-- ORGANISATION HIERARCHY
-- ============================================================

CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, code)
);

CREATE TABLE IF NOT EXISTS subsidiaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS facilities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    subsidiary_id UUID REFERENCES subsidiaries(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    code TEXT,
    address TEXT,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    code TEXT,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, facility_id, name)
);

CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, name)
);

-- ============================================================
-- STAFF
-- ============================================================

CREATE TABLE IF NOT EXISTS staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    company_id UUID REFERENCES companies(id),
    subsidiary_id UUID REFERENCES subsidiaries(id),
    facility_id UUID REFERENCES facilities(id),
    department_id UUID REFERENCES departments(id),
    primary_team_id UUID REFERENCES teams(id),
    staff_number TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    display_name TEXT,
    email TEXT,
    phone TEXT,
    designation TEXT,
    employment_status staff_employment_status NOT NULL DEFAULT 'active',
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_org_staff_number
ON staff (organization_id, staff_number)
WHERE staff_number IS NOT NULL;

CREATE TABLE IF NOT EXISTS staff_company_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    subsidiary_id UUID REFERENCES subsidiaries(id) ON DELETE SET NULL,
    facility_id UUID REFERENCES facilities(id) ON DELETE SET NULL,
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    role_id UUID,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    status workspace_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (staff_id, company_id, subsidiary_id)
);

CREATE TABLE IF NOT EXISTS staff_teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (staff_id, team_id)
);

CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, code)
);

CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource TEXT NOT NULL,
    action TEXT NOT NULL,
    UNIQUE (resource, action)
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS staff_preferences (
    staff_id UUID PRIMARY KEY REFERENCES staff(id) ON DELETE CASCADE,
    default_workspace TEXT NOT NULL DEFAULT 'my_day',
    task_sort TEXT NOT NULL DEFAULT 'due_date',
    timezone TEXT NOT NULL DEFAULT 'Africa/Lagos',
    show_calendar BOOLEAN NOT NULL DEFAULT true,
    show_progress BOOLEAN NOT NULL DEFAULT true,
    show_team BOOLEAN NOT NULL DEFAULT true,
    show_journal BOOLEAN NOT NULL DEFAULT true,
    notify_assignments BOOLEAN NOT NULL DEFAULT true,
    notify_requests BOOLEAN NOT NULL DEFAULT true,
    notify_mentions BOOLEAN NOT NULL DEFAULT true,
    notify_updates BOOLEAN NOT NULL DEFAULT false,
    quiet_hours_start TIME,
    quiet_hours_end TIME,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TASK ENGINE
-- ============================================================

CREATE TABLE IF NOT EXISTS staff_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL REFERENCES organizations(id),
    company_id UUID REFERENCES companies(id),
    subsidiary_id UUID REFERENCES subsidiaries(id),
    facility_id UUID REFERENCES facilities(id),
    department_id UUID REFERENCES departments(id),
    team_id UUID REFERENCES teams(id),

    created_by UUID NOT NULL REFERENCES staff(id),
    assigned_to UUID REFERENCES staff(id),

    title TEXT NOT NULL,
    description TEXT,

    status task_status NOT NULL DEFAULT 'inbox',
    priority task_priority NOT NULL DEFAULT 'normal',
    source_type task_source_type NOT NULL DEFAULT 'manual',

    entity_type TEXT,
    entity_id TEXT,

    start_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,

    is_recurring BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_task_checklists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES staff_tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    is_completed BOOLEAN NOT NULL DEFAULT false,
    completed_by UUID REFERENCES staff(id),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_task_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES staff_tasks(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES staff(id),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_task_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES staff_tasks(id) ON DELETE CASCADE,
    actor_id UUID REFERENCES staff(id),
    activity_type TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    remind_at TIMESTAMPTZ NOT NULL,
    related_task_id UUID REFERENCES staff_tasks(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- COLLABORATION
-- ============================================================

CREATE TABLE IF NOT EXISTS staff_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL REFERENCES organizations(id),
    company_id UUID REFERENCES companies(id),
    subsidiary_id UUID REFERENCES subsidiaries(id),

    requester_id UUID NOT NULL REFERENCES staff(id),
    recipient_id UUID REFERENCES staff(id),
    team_id UUID REFERENCES teams(id),

    request_type request_type NOT NULL,
    title TEXT NOT NULL,
    description TEXT,

    related_task_id UUID REFERENCES staff_tasks(id) ON DELETE SET NULL,

    entity_type TEXT,
    entity_id TEXT,

    priority task_priority NOT NULL DEFAULT 'normal',
    status request_status NOT NULL DEFAULT 'sent',

    due_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS staff_request_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES staff_requests(id) ON DELETE CASCADE,
    sender_id UUID NOT NULL REFERENCES staff(id),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_request_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES staff_requests(id) ON DELETE CASCADE,
    actor_id UUID REFERENCES staff(id),
    activity_type TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- NOTIFICATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS staff_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    notification_type TEXT NOT NULL,
    priority task_priority NOT NULL DEFAULT 'normal',
    title TEXT NOT NULL,
    message TEXT,
    entity_type TEXT,
    entity_id TEXT,
    is_read BOOLEAN NOT NULL DEFAULT false,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TIME & ATTENDANCE
-- ============================================================

CREATE TABLE IF NOT EXISTS staff_time_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id),
    facility_id UUID REFERENCES facilities(id),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status time_session_status NOT NULL DEFAULT 'active',
    total_seconds INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_break_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    time_session_id UUID NOT NULL REFERENCES staff_time_sessions(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    break_type TEXT NOT NULL DEFAULT 'break',
    duration_seconds INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ACTIVITY / EVENT SPINE
-- ============================================================

CREATE TABLE IF NOT EXISTS staff_work_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL REFERENCES organizations(id),
    company_id UUID REFERENCES companies(id),
    subsidiary_id UUID REFERENCES subsidiaries(id),
    facility_id UUID REFERENCES facilities(id),

    staff_id UUID REFERENCES staff(id),

    event_type TEXT NOT NULL,

    entity_type TEXT,
    entity_id TEXT,

    metadata JSONB,

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- OPERATIONAL TASK RULES
-- ============================================================

CREATE TABLE IF NOT EXISTS operational_task_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL REFERENCES organizations(id),
    company_id UUID REFERENCES companies(id),
    subsidiary_id UUID REFERENCES subsidiaries(id),

    event_type TEXT NOT NULL,
    name TEXT NOT NULL,

    condition JSONB,
    task_template JSONB,
    assignment JSONB,

    priority task_priority NOT NULL DEFAULT 'normal',

    is_active BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_staff_company
    ON staff (company_id, employment_status);

CREATE INDEX IF NOT EXISTS idx_staff_department
    ON staff (department_id, employment_status);

CREATE INDEX IF NOT EXISTS idx_staff_tasks_assignee_status
    ON staff_tasks (assigned_to, status);

CREATE INDEX IF NOT EXISTS idx_staff_tasks_assignee_due
    ON staff_tasks (assigned_to, due_at);

CREATE INDEX IF NOT EXISTS idx_staff_tasks_team_status
    ON staff_tasks (team_id, status);

CREATE INDEX IF NOT EXISTS idx_staff_tasks_company_status
    ON staff_tasks (company_id, status);

CREATE INDEX IF NOT EXISTS idx_staff_tasks_entity
    ON staff_tasks (entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_task_activity_task_time
    ON staff_task_activity (task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON staff_notifications (staff_id, is_read, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_requests_recipient_status
    ON staff_requests (recipient_id, status);

CREATE INDEX IF NOT EXISTS idx_requests_requester_status
    ON staff_requests (requester_id, status);

CREATE INDEX IF NOT EXISTS idx_time_staff_started
    ON staff_time_sessions (staff_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_work_events_staff_time
    ON staff_work_events (staff_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_work_events_entity
    ON staff_work_events (entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_reminders_staff_time
    ON staff_reminders (staff_id, status, remind_at);

-- ============================================================
-- UPDATED_AT TRIGGERS
-- ============================================================

DO $$ BEGIN
    CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_subsidiaries_updated_at
    BEFORE UPDATE ON subsidiaries
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_facilities_updated_at
    BEFORE UPDATE ON facilities
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_departments_updated_at
    BEFORE UPDATE ON departments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_teams_updated_at
    BEFORE UPDATE ON teams
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_staff_updated_at
    BEFORE UPDATE ON staff
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_staff_preferences_updated_at
    BEFORE UPDATE ON staff_preferences
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON staff_tasks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_task_comments_updated_at
    BEFORE UPDATE ON staff_task_comments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_requests_updated_at
    BEFORE UPDATE ON staff_requests
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_time_sessions_updated_at
    BEFORE UPDATE ON staff_time_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_operational_rules_updated_at
    BEFORE UPDATE ON operational_task_rules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- SEED PERMISSIONS
-- ============================================================

INSERT INTO permissions (resource, action) VALUES
    ('task', 'view'),
    ('task', 'create'),
    ('task', 'assign'),
    ('task', 'update'),
    ('task', 'complete'),
    ('task', 'verify'),
    ('task', 'close'),
    ('request', 'view'),
    ('request', 'create'),
    ('request', 'respond'),
    ('request', 'close'),
    ('team', 'view'),
    ('team', 'manage'),
    ('time', 'view'),
    ('time', 'start'),
    ('time', 'manage'),
    ('progress', 'view'),
    ('notification', 'manage')
ON CONFLICT (resource, action) DO NOTHING;

COMMIT;
