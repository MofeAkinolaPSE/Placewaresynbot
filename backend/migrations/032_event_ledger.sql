-- Migration: Create EventLedger table (immutable event ledger)
CREATE TABLE IF NOT EXISTS event_ledger (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department TEXT NOT NULL,
    event_type TEXT NOT NULL,
    linked_project_id UUID NULL,
    linked_customer_id UUID NULL,
    linked_supplier_id UUID NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    approval_status TEXT NULL,
    risk_score NUMERIC NULL,
    version_hash TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_event_ledger_event_type ON event_ledger(event_type);
CREATE INDEX IF NOT EXISTS idx_event_ledger_department ON event_ledger(department);
CREATE INDEX IF NOT EXISTS idx_event_ledger_created_at ON event_ledger(created_at);

-- Notify trigger: publish to Postgres NOTIFY channel 'event_bus' with payload
CREATE OR REPLACE FUNCTION notify_event_bus()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    payload TEXT;
BEGIN
    payload := json_build_object(
        'event_type', NEW.event_type,
        'department', NEW.department,
        'event_id', NEW.event_id,
        'linked_project_id', NEW.linked_project_id,
        'linked_customer_id', NEW.linked_customer_id,
        'linked_supplier_id', NEW.linked_supplier_id,
        'payload', NEW.payload
    )::text;
    PERFORM pg_notify('event_bus', payload);
    RETURN NEW;
END; $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'event_ledger_notify_event_bus') THEN
        CREATE TRIGGER event_ledger_notify_event_bus AFTER INSERT ON event_ledger FOR EACH ROW EXECUTE FUNCTION notify_event_bus();
    END IF;
END $$;
