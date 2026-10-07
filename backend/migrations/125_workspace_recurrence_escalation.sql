-- Staff Workspace: recurring tasks and escalation chains.
--
-- Recurring: a task carries its rule (daily, weekdays, weekly[:MO,FR], monthly[:15|last],
-- every:N:days|weeks). Finishing (or skipping) one schedules the next in the same series.
-- Escalation: when a task, reminder or request passes its due time, the chain for its
-- priority fires step by step - the person doing it, then whoever gave it, then management.
-- The step reached is stored on the record, so each step fires once even with several workers.

BEGIN;

ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS recurrence text;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS recurrence_until date;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS series_id uuid;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS escalation_level integer NOT NULL DEFAULT 0;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS escalated_at timestamptz;
ALTER TABLE placeware_tasks ADD COLUMN IF NOT EXISTS escalated_to text;
CREATE INDEX IF NOT EXISTS idx_tasks_series ON placeware_tasks(series_id) WHERE series_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_escalation ON placeware_tasks(status, due_date, reminder_at);

ALTER TABLE staff_requests ADD COLUMN IF NOT EXISTS escalation_level integer NOT NULL DEFAULT 0;
ALTER TABLE staff_requests ADD COLUMN IF NOT EXISTS escalated_at timestamptz;
ALTER TABLE staff_requests ADD COLUMN IF NOT EXISTS escalated_to text;

-- one chain per (subject, priority); steps = [{"after_hours": n, "to": "assignee|giver|management|recipient|requester"}]
CREATE TABLE IF NOT EXISTS staff_escalation_policy (
  subject    text NOT NULL CHECK (subject IN ('task','request')),
  priority   text NOT NULL,
  steps      jsonb NOT NULL,
  updated_by uuid,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (subject, priority)
);
INSERT INTO staff_escalation_policy (subject, priority, steps) VALUES
  ('task', 'critical', '[{"after_hours":0,"to":"assignee"},{"after_hours":2,"to":"giver"},{"after_hours":8,"to":"management"}]'),
  ('task', 'high',     '[{"after_hours":0,"to":"assignee"},{"after_hours":24,"to":"giver"},{"after_hours":72,"to":"management"}]'),
  ('task', 'medium',   '[{"after_hours":0,"to":"assignee"},{"after_hours":48,"to":"giver"}]'),
  ('task', 'low',      '[{"after_hours":0,"to":"assignee"}]'),
  ('request', 'all',   '[{"after_hours":0,"to":"recipient"},{"after_hours":24,"to":"requester"},{"after_hours":72,"to":"management"}]')
ON CONFLICT (subject, priority) DO NOTHING;

COMMIT;
