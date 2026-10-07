-- Staff Workspace: one home for each team member (their day, tasks, requests, messages,
-- time clock and progress), connected to HR and to the operational modules.
--
-- Identity: a person is their login (placeware_users). The HR profile (placeware_staff)
-- is linked to it by user_id, so everyone registered on User Access appears in HR.
-- Time: the clock runs on the server (staff_time_sessions); clocking out writes the
-- timesheet HR reviews. Previously the clock lived in the browser and the timesheet
-- insert failed, because it sent the login id where a staff id was required.

BEGIN;

-- ---------------------------------------------------------------- HR profile <-> login
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES placeware_users(id) ON DELETE SET NULL;
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS branch text;
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS start_date date;
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS weekly_hours numeric(5,2) NOT NULL DEFAULT 40;
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
UPDATE placeware_staff s SET user_id = u.id FROM placeware_users u
 WHERE s.user_id IS NULL AND lower(u.email) = lower(s.email);
CREATE UNIQUE INDEX IF NOT EXISTS uq_placeware_staff_user ON placeware_staff(user_id) WHERE user_id IS NOT NULL;

ALTER TABLE placeware_staff DROP CONSTRAINT IF EXISTS placeware_staff_department_check;
ALTER TABLE placeware_staff ADD CONSTRAINT placeware_staff_department_check CHECK (department = ANY (ARRAY[
  'Finance','Sales','Operations','Procurement','Logistics','Quality','HR','Management','Admin']));

-- ---------------------------------------------------------------- time clock
CREATE TABLE IF NOT EXISTS staff_time_sessions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid NOT NULL REFERENCES placeware_users(id) ON DELETE CASCADE,
  staff_id         uuid REFERENCES placeware_staff(staff_id) ON DELETE SET NULL,
  started_at       timestamptz NOT NULL DEFAULT now(),
  ended_at         timestamptz,
  break_seconds    integer NOT NULL DEFAULT 0,
  break_started_at timestamptz,
  breaks           integer NOT NULL DEFAULT 0,
  department       text,
  note             text,
  timesheet_id     bigint,
  created_at       timestamptz NOT NULL DEFAULT now()
);
-- one running clock per person
CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_time_open ON staff_time_sessions(user_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_staff_time_user_start ON staff_time_sessions(user_id, started_at DESC);

ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES placeware_users(id) ON DELETE SET NULL;
ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS session_id uuid REFERENCES staff_time_sessions(id) ON DELETE SET NULL;
ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'manual';
ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'submitted';
ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS approved_by uuid;
ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS approved_at timestamptz;
ALTER TABLE placeware_timesheets ADD COLUMN IF NOT EXISTS review_note text;
ALTER TABLE placeware_timesheets DROP CONSTRAINT IF EXISTS placeware_timesheets_status_check;
ALTER TABLE placeware_timesheets ADD CONSTRAINT placeware_timesheets_status_check CHECK (status IN ('submitted','approved','rejected'));
ALTER TABLE placeware_timesheets DROP CONSTRAINT IF EXISTS placeware_timesheets_source_check;
ALTER TABLE placeware_timesheets ADD CONSTRAINT placeware_timesheets_source_check CHECK (source IN ('clock','manual','hr'));
UPDATE placeware_timesheets t SET user_id = s.user_id FROM placeware_staff s WHERE t.user_id IS NULL AND s.staff_id = t.staff_id;
CREATE INDEX IF NOT EXISTS idx_timesheets_user_date ON placeware_timesheets(user_id, date);

-- ---------------------------------------------------------------- tasks, reminders, notes
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'task';
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS department text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS entity_type text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS entity_id text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS entity_label text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS link text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS checklist jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS waiting_on text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS completed_by uuid;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS request_id uuid;
ALTER TABLE placeware_tasks DROP CONSTRAINT IF EXISTS placeware_tasks_kind_check;
ALTER TABLE placeware_tasks ADD CONSTRAINT placeware_tasks_kind_check CHECK (kind IN ('task','reminder','note'));
ALTER TABLE placeware_tasks DROP CONSTRAINT IF EXISTS placeware_tasks_status_check;
ALTER TABLE placeware_tasks ADD CONSTRAINT placeware_tasks_status_check
  CHECK (status IN ('pending','in_progress','waiting','completed','cancelled','blocked'));
ALTER TABLE placeware_tasks DROP CONSTRAINT IF EXISTS placeware_tasks_source_check;
ALTER TABLE placeware_tasks ADD CONSTRAINT placeware_tasks_source_check
  CHECK (source IN ('manual','chat','agent','workflow','import','operational','request','assigned'));
-- one open task per operational item (the "Take it" button is idempotent)
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_open_operational ON placeware_tasks(source_ref)
  WHERE source = 'operational' AND status NOT IN ('completed','cancelled');
CREATE INDEX IF NOT EXISTS idx_tasks_created_by ON placeware_tasks(created_by);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON placeware_tasks(completed_by, completed_at);

CREATE TABLE IF NOT EXISTS staff_task_activity (
  id         bigserial PRIMARY KEY,
  task_id    uuid NOT NULL REFERENCES placeware_tasks(id) ON DELETE CASCADE,
  actor      uuid,
  kind       text NOT NULL,          -- created, status, comment, checklist, assigned, updated, resolved
  body       text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_task_activity_task ON staff_task_activity(task_id, created_at);

-- ---------------------------------------------------------------- requests between people / teams
CREATE TABLE IF NOT EXISTS staff_requests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_user     uuid NOT NULL REFERENCES placeware_users(id) ON DELETE CASCADE,
  to_user       uuid REFERENCES placeware_users(id) ON DELETE SET NULL,
  to_department text,
  kind          text NOT NULL DEFAULT 'info' CHECK (kind IN ('info','work')),
  subject       text NOT NULL,
  body          text,
  task_id       uuid REFERENCES placeware_tasks(id) ON DELETE SET NULL,   -- the requester's related task
  work_task_id  uuid REFERENCES placeware_tasks(id) ON DELETE SET NULL,   -- the task a work request created
  due_at        timestamptz,
  status        text NOT NULL DEFAULT 'sent'
                CHECK (status IN ('sent','acknowledged','in_progress','responded','closed','declined')),
  response      text,
  responded_by  uuid,
  responded_at  timestamptz,
  closed_at     timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT staff_requests_target_check CHECK (to_user IS NOT NULL OR to_department IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_staff_requests_to ON staff_requests(to_user, status);
CREATE INDEX IF NOT EXISTS idx_staff_requests_from ON staff_requests(from_user, status);

CREATE TABLE IF NOT EXISTS staff_request_messages (
  id         bigserial PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES staff_requests(id) ON DELETE CASCADE,
  author     uuid,
  body       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- inbox + work journal + preferences
CREATE TABLE IF NOT EXISTS staff_notifications (
  id         bigserial PRIMARY KEY,
  user_id    uuid NOT NULL REFERENCES placeware_users(id) ON DELETE CASCADE,
  kind       text NOT NULL,      -- assigned, request, response, mention, comment, completed, reminder
  level      text NOT NULL DEFAULT 'info' CHECK (level IN ('critical','action','info','social')),
  title      text NOT NULL,
  body       text,
  link_type  text,               -- task, request, message, page
  link_id    text,
  actor      uuid,
  read_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_staff_notifications_user ON staff_notifications(user_id, read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS staff_work_events (
  id          bigserial PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES placeware_users(id) ON DELETE CASCADE,
  kind        text NOT NULL,     -- clock_in, break, resume, clock_out, task_created, task_started, task_completed, request_sent, request_answered, message
  summary     text NOT NULL,
  entity_type text,
  entity_id   text,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_staff_work_events_user ON staff_work_events(user_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS staff_preferences (
  user_id    uuid PRIMARY KEY REFERENCES placeware_users(id) ON DELETE CASCADE,
  prefs      jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
