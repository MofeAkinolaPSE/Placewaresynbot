-- Migration 040: Calendar Events and Tasks tables for Milestone 6
-- Company calendar, meeting scheduling, and task management

-- Calendar Events Table
CREATE TABLE IF NOT EXISTS placeware_calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    event_type TEXT NOT NULL DEFAULT 'meeting' CHECK (event_type IN ('meeting', 'deadline', 'reminder', 'holiday', 'other')),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    all_day BOOLEAN DEFAULT FALSE,
    location TEXT,
    attendees JSONB DEFAULT '[]'::jsonb,  -- Array of {user_id, name, email, status}
    recurrence TEXT,  -- RRULE string for recurring events
    created_by UUID REFERENCES placeware_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON placeware_calendar_events(start_time);
CREATE INDEX IF NOT EXISTS idx_calendar_events_created_by ON placeware_calendar_events(created_by);
CREATE INDEX IF NOT EXISTS idx_calendar_events_type ON placeware_calendar_events(event_type);

-- Tasks Table
CREATE TABLE IF NOT EXISTS placeware_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled', 'blocked')),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    due_date TIMESTAMPTZ,
    reminder_at TIMESTAMPTZ,
    assigned_to UUID REFERENCES placeware_users(id) ON DELETE SET NULL,
    created_by UUID REFERENCES placeware_users(id) ON DELETE SET NULL,
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'chat', 'agent', 'workflow', 'import')),
    source_ref TEXT,  -- Reference to source (chat_id, workflow_id, etc.)
    tags JSONB DEFAULT '[]'::jsonb,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON placeware_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON placeware_tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON placeware_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON placeware_tasks(priority);

-- Enable RLS
ALTER TABLE placeware_calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE placeware_tasks ENABLE ROW LEVEL SECURITY;

-- RLS Policies for calendar events
DROP POLICY IF EXISTS admin_all_calendar_events ON placeware_calendar_events;
CREATE POLICY admin_all_calendar_events ON placeware_calendar_events 
    FOR ALL 
    USING (true) 
    WITH CHECK (true);

DROP POLICY IF EXISTS user_view_calendar_events ON placeware_calendar_events;
CREATE POLICY user_view_calendar_events ON placeware_calendar_events 
    FOR SELECT 
    USING (TRUE);  -- All authenticated users can view events

DROP POLICY IF EXISTS user_manage_own_calendar_events ON placeware_calendar_events;
CREATE POLICY user_manage_own_calendar_events ON placeware_calendar_events 
    FOR ALL 
    USING (created_by::text = NULL)
    WITH CHECK (created_by::text = NULL);

-- RLS Policies for tasks
DROP POLICY IF EXISTS admin_all_tasks ON placeware_tasks;
CREATE POLICY admin_all_tasks ON placeware_tasks 
    FOR ALL 
    USING (true) 
    WITH CHECK (true);

DROP POLICY IF EXISTS user_view_assigned_tasks ON placeware_tasks;
CREATE POLICY user_view_assigned_tasks ON placeware_tasks 
    FOR SELECT 
    USING (assigned_to::text = NULL OR created_by::text = NULL);

DROP POLICY IF EXISTS user_manage_own_tasks ON placeware_tasks;
CREATE POLICY user_manage_own_tasks ON placeware_tasks 
    FOR ALL 
    USING (created_by::text = NULL OR assigned_to::text = NULL)
    WITH CHECK (created_by::text = NULL);

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_calendar_tasks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_calendar_events_updated_at ON placeware_calendar_events;
CREATE TRIGGER trg_calendar_events_updated_at
    BEFORE UPDATE ON placeware_calendar_events
    FOR EACH ROW
    EXECUTE FUNCTION update_calendar_tasks_updated_at();

DROP TRIGGER IF EXISTS trg_tasks_updated_at ON placeware_tasks;
CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON placeware_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_calendar_tasks_updated_at();
