-- =============================================================================
-- Migration 076 — Capability Discovery Registry Schema
-- Creates tables for signal ingestion, capability proposals, and status history.
-- Depends on: placeware_touch_updated_at() from migration 074.
-- =============================================================================

-- Raw signals — each detected gap / recurring failure / bottleneck
CREATE TABLE IF NOT EXISTS placeware_capability_signals (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type  VARCHAR(100) NOT NULL,   -- repeated_failure | manual_intervention | bottleneck | user_request | twin_anomaly
    component    VARCHAR(100),
    description  TEXT         NOT NULL,
    frequency    INTEGER      NOT NULL DEFAULT 1,    -- times this pattern has been observed
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata     JSONB        NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Structured capability proposals generated from clustered signals
CREATE TABLE IF NOT EXISTS placeware_capability_proposals (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_name     VARCHAR(200) NOT NULL,
    problem             TEXT         NOT NULL,
    opportunity         TEXT         NOT NULL,
    required_components JSONB        NOT NULL DEFAULT '[]',
    integration_points  JSONB        NOT NULL DEFAULT '[]',
    estimated_impact    TEXT,
    confidence_score    NUMERIC(5,3) DEFAULT 0.0,
    status              VARCHAR(50)  NOT NULL DEFAULT 'proposed',  -- proposed | approved | rejected | implemented | deferred
    signal_ids          JSONB        NOT NULL DEFAULT '[]',        -- array of placeware_capability_signals.id
    reviewer_notes      TEXT,
    reviewed_by         VARCHAR(200),
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Audit trail of status changes for governance
CREATE TABLE IF NOT EXISTS placeware_capability_status_history (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id  UUID        NOT NULL REFERENCES placeware_capability_proposals(id) ON DELETE CASCADE,
    old_status   VARCHAR(50),
    new_status   VARCHAR(50) NOT NULL,
    changed_by   VARCHAR(200),
    notes        TEXT,
    changed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_cap_signals_type
    ON placeware_capability_signals (signal_type, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_cap_signals_component
    ON placeware_capability_signals (component, frequency DESC);
CREATE INDEX IF NOT EXISTS idx_cap_proposals_status
    ON placeware_capability_proposals (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cap_proposals_confidence
    ON placeware_capability_proposals (confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_cap_status_history_proposal
    ON placeware_capability_status_history (proposal_id, changed_at DESC);

-- ── Triggers ──────────────────────────────────────────────────────────────
CREATE OR REPLACE TRIGGER trg_cap_signals_updated_at
    BEFORE UPDATE ON placeware_capability_signals
    FOR EACH ROW EXECUTE FUNCTION placeware_touch_updated_at();

CREATE OR REPLACE TRIGGER trg_cap_proposals_updated_at
    BEFORE UPDATE ON placeware_capability_proposals
    FOR EACH ROW EXECUTE FUNCTION placeware_touch_updated_at();
