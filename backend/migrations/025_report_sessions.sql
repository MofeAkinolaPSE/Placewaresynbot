-- ============================================================================
-- Migration 025: Report Sessions + Enhanced Report Memory
-- ============================================================================
-- Creates placeware_report_sessions table to track multi-step report
-- generation workflows. Adds session linkage and approval columns to the
-- existing placeware_report_memory table.
--
-- Run order: After 020_agent_intelligence_tables.sql
-- ============================================================================

-- ── 1. Report Sessions ────────────────────────────────────────────────────────
-- Tracks a single report generation "job" from wizard start to final approval.
-- session_status lifecycle: draft → scoping → generating → complete → approved
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS placeware_report_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type     TEXT NOT NULL,
    session_status  TEXT NOT NULL DEFAULT 'draft'
                    CHECK (session_status IN ('draft','scoping','generating','complete','approved','failed')),
    -- JSONB bag: date_from, date_to, department, entity_filter, sku_filter,
    --            customer_filter, currency, custom_notes, line_items, etc.
    scope_params    JSONB NOT NULL DEFAULT '{}'::JSONB,
    evidence_notes  TEXT,
    -- Who triggered this session (JWT sub / user id)
    created_by      TEXT,
    -- Set when generation completes
    report_id       UUID REFERENCES placeware_report_memory(id) ON DELETE SET NULL,
    -- Set when a manager approves
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    -- Soft-delete / expiry tracking
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_report_sessions_type
    ON placeware_report_sessions (report_type);

CREATE INDEX IF NOT EXISTS idx_report_sessions_status
    ON placeware_report_sessions (session_status);

CREATE INDEX IF NOT EXISTS idx_report_sessions_user
    ON placeware_report_sessions (created_by);

CREATE INDEX IF NOT EXISTS idx_report_sessions_created
    ON placeware_report_sessions (created_at DESC);

-- ── 2. Enhanced placeware_report_memory ──────────────────────────────────────
-- Adds optional FK back to the session that generated this report, plus
-- approval metadata, template version, and per-section JSONB data.
-- ─────────────────────────────────────────────────────────────────────────────

-- Link back to the session (nullable so existing rows are unaffected)
ALTER TABLE placeware_report_memory
    ADD COLUMN IF NOT EXISTS session_id UUID
        REFERENCES placeware_report_sessions(id) ON DELETE SET NULL;

-- Template version string (e.g. "2025-05-09")
ALTER TABLE placeware_report_memory
    ADD COLUMN IF NOT EXISTS template_version TEXT;

-- Structured per-section data produced by the agent
-- [{ section_id, title, content, confidence_score, data_rows, rag_hits, status }]
ALTER TABLE placeware_report_memory
    ADD COLUMN IF NOT EXISTS section_data JSONB;

-- Approval workflow
ALTER TABLE placeware_report_memory
    ADD COLUMN IF NOT EXISTS approved_by TEXT;

ALTER TABLE placeware_report_memory
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

-- Approval status column for quick filtering
ALTER TABLE placeware_report_memory
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (approval_status IN ('draft','complete','approved'));

-- ── 3. Auto-update trigger for updated_at ────────────────────────────────────

CREATE OR REPLACE FUNCTION placeware_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_report_sessions_updated_at ON placeware_report_sessions;
CREATE TRIGGER trg_report_sessions_updated_at
    BEFORE UPDATE ON placeware_report_sessions
    FOR EACH ROW EXECUTE FUNCTION placeware_set_updated_at();

-- ── 4. Row-Level Security (keep data isolated per user) ──────────────────────
-- Only enable if your Supabase project uses RLS.
-- Adjust the auth.uid() comparison to match your JWT claim.

-- ALTER TABLE placeware_report_sessions ENABLE ROW LEVEL SECURITY;
--
-- CREATE POLICY "users_own_sessions" ON placeware_report_sessions
--     USING (created_by = auth.uid()::text OR auth.jwt() ->> 'role' IN ('admin','management'));
