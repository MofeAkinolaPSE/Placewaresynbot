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
