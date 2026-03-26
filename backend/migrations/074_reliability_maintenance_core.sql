-- ============================================================
-- Migration 074: Reliability Maintenance Core
-- Creates foundational tables for the maintenance reliability stack:
--   placeware_maintenance_assets
--   placeware_maintenance_tasks
--   placeware_incident_log
--   placeware_remediation_actions
--   placeware_failure_pattern_library
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS placeware_maintenance_assets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_code          TEXT NOT NULL UNIQUE,
    asset_name          TEXT NOT NULL,
    asset_type          TEXT,
    location            TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    pm_frequency_days   INTEGER NOT NULL DEFAULT 30,
    last_pm_at          TIMESTAMPTZ,
    next_pm_due_at      TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_maint_assets_status
    ON placeware_maintenance_assets (status);

CREATE INDEX IF NOT EXISTS idx_maint_assets_next_pm_due
    ON placeware_maintenance_assets (next_pm_due_at);


CREATE TABLE IF NOT EXISTS placeware_maintenance_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id            UUID REFERENCES placeware_maintenance_assets(id) ON DELETE SET NULL,
    task_type           TEXT NOT NULL DEFAULT 'preventive_maintenance',
    title               TEXT NOT NULL,
    description         TEXT,
    status              TEXT NOT NULL DEFAULT 'scheduled',
    severity            TEXT NOT NULL DEFAULT 'medium',
    due_at              TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    assigned_to         TEXT,
    completion_notes    TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_maint_tasks_status
    ON placeware_maintenance_tasks (status);

CREATE INDEX IF NOT EXISTS idx_maint_tasks_due_at
    ON placeware_maintenance_tasks (due_at);

CREATE INDEX IF NOT EXISTS idx_maint_tasks_asset
    ON placeware_maintenance_tasks (asset_id);


CREATE TABLE IF NOT EXISTS placeware_incident_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_key        TEXT,
    component           TEXT NOT NULL,
    severity            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    summary             TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id      TEXT,
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_status
    ON placeware_incident_log (status);

CREATE INDEX IF NOT EXISTS idx_incident_severity
    ON placeware_incident_log (severity);

CREATE INDEX IF NOT EXISTS idx_incident_component
    ON placeware_incident_log (component);

CREATE INDEX IF NOT EXISTS idx_incident_detected
    ON placeware_incident_log (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_incident_correlation
    ON placeware_incident_log (correlation_id);


CREATE TABLE IF NOT EXISTS placeware_remediation_actions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id         UUID REFERENCES placeware_incident_log(id) ON DELETE CASCADE,
    action_name         TEXT NOT NULL,
    action_type         TEXT NOT NULL DEFAULT 'auto_fix',
    outcome             TEXT NOT NULL,
    notes               TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    executed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_remediation_incident
    ON placeware_remediation_actions (incident_id);

CREATE INDEX IF NOT EXISTS idx_remediation_executed
    ON placeware_remediation_actions (executed_at DESC);


CREATE TABLE IF NOT EXISTS placeware_failure_pattern_library (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_type          TEXT NOT NULL,
    component           TEXT NOT NULL,
    pattern_signature   TEXT,
    root_cause          TEXT,
    fix_method          TEXT,
    confidence_score    NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    hit_count           INTEGER NOT NULL DEFAULT 0,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (issue_type, component, pattern_signature)
);

CREATE INDEX IF NOT EXISTS idx_failure_pattern_component
    ON placeware_failure_pattern_library (component);

CREATE INDEX IF NOT EXISTS idx_failure_pattern_issue_type
    ON placeware_failure_pattern_library (issue_type);

CREATE INDEX IF NOT EXISTS idx_failure_pattern_confidence
    ON placeware_failure_pattern_library (confidence_score DESC);


CREATE OR REPLACE FUNCTION placeware_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_maint_assets_updated_at ON placeware_maintenance_assets;
CREATE TRIGGER trg_maint_assets_updated_at
    BEFORE UPDATE ON placeware_maintenance_assets
    FOR EACH ROW
    EXECUTE FUNCTION placeware_touch_updated_at();

DROP TRIGGER IF EXISTS trg_maint_tasks_updated_at ON placeware_maintenance_tasks;
CREATE TRIGGER trg_maint_tasks_updated_at
    BEFORE UPDATE ON placeware_maintenance_tasks
    FOR EACH ROW
    EXECUTE FUNCTION placeware_touch_updated_at();

DROP TRIGGER IF EXISTS trg_incident_log_updated_at ON placeware_incident_log;
CREATE TRIGGER trg_incident_log_updated_at
    BEFORE UPDATE ON placeware_incident_log
    FOR EACH ROW
    EXECUTE FUNCTION placeware_touch_updated_at();

DROP TRIGGER IF EXISTS trg_failure_pattern_updated_at ON placeware_failure_pattern_library;
CREATE TRIGGER trg_failure_pattern_updated_at
    BEFORE UPDATE ON placeware_failure_pattern_library
    FOR EACH ROW
    EXECUTE FUNCTION placeware_touch_updated_at();
