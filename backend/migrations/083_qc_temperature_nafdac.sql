-- =============================================================================
-- Migration 083 — QC: Temperature Logs & NAFDAC Batch Registry
-- =============================================================================
-- Purpose: Add the two tables required by the QC & Inventory Management
--          requirements survey (April 2026) that are not covered by
--          migration 070 (QMS Compliance Schema):
--
--   1. temperature_logs  — Captures the 3×-daily cold-chain readings
--                          (08:00 / 12:00 / 17:00).  Auto-flags deviations
--                          when a reading falls outside the configured min/max
--                          thresholds, and tracks escalation status.
--
--   2. nafdac_batch_registry — Per-batch NAFDAC approval status.  A
--                          dispatch_blocked flag is set automatically on
--                          insert (pending|rejected|suspended → TRUE) and
--                          cleared when the batch is approved.  The
--                          backend enforces this block at point of dispatch.
--
-- Prerequisites:
--   • Migration 070 must be applied (equipment_registry table must exist
--     so that temperature_logs.equipment_id FK is resolvable).
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Temperature Logs
--    Records every cold-chain temperature reading.  Deviations are flagged
--    inline and linked back to the equipment_registry entry.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS temperature_logs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Which cold room / equipment was logged
    equipment_id        UUID        REFERENCES equipment_registry(id) ON DELETE SET NULL,
    location            TEXT        NOT NULL,           -- redundant denorm for fast query / display

    -- The reading
    reading_celsius     NUMERIC(5, 2) NOT NULL,
    min_threshold       NUMERIC(5, 2) NOT NULL DEFAULT 2.0,   -- °C lower bound (default cold-chain: 2–8°C)
    max_threshold       NUMERIC(5, 2) NOT NULL DEFAULT 8.0,   -- °C upper bound

    -- Auto-computed deviation flag (set by application layer on insert)
    is_deviation        BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Session slot: morning | midday | evening
    log_session         TEXT        NOT NULL DEFAULT 'morning'
                        CHECK (log_session IN ('morning', 'midday', 'evening', 'ad_hoc')),

    -- Who recorded it and when
    logged_by           TEXT        NOT NULL,           -- staff name or user UUID
    logged_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Escalation tracking
    deviation_escalated BOOLEAN     NOT NULL DEFAULT FALSE,
    escalated_to        TEXT,                           -- name of person notified
    escalated_at        TIMESTAMPTZ,
    escalation_notes    TEXT,

    -- Link to CAPA if one was raised as a result
    deviation_report_id UUID        REFERENCES deviation_reports(id) ON DELETE SET NULL,

    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookups for the daily 3×-per-day grid view and recent-deviations query
CREATE INDEX IF NOT EXISTS idx_temp_logs_equipment   ON temperature_logs (equipment_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_temp_logs_logged_at   ON temperature_logs (logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_temp_logs_deviation   ON temperature_logs (is_deviation) WHERE is_deviation = TRUE;
CREATE INDEX IF NOT EXISTS idx_temp_logs_escalation  ON temperature_logs (deviation_escalated) WHERE is_deviation = TRUE;
CREATE INDEX IF NOT EXISTS idx_temp_logs_location    ON temperature_logs (location, logged_at DESC);

COMMENT ON TABLE temperature_logs IS
    'Records 3×-daily (morning/midday/evening) cold-chain temperature readings '
    'per equipment unit. Deviations (readings outside min/max range) are flagged '
    'at insert time and can be escalated and linked to CAPA deviation reports.';

-- ---------------------------------------------------------------------------
-- 2. NAFDAC Batch Registry
--    Tracks per-batch regulatory approval status.  dispatch_blocked is the
--    authoritative gate checked by the dispatch / invoice workflow.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nafdac_batch_registry (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Batch identification
    batch_number        TEXT        NOT NULL,
    product_name        TEXT        NOT NULL,
    nafdac_reg_number   TEXT,                           -- e.g. "A7-1234"  (populated when known)
    supplier            TEXT,

    -- Regulatory status
    status              TEXT        NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'suspended')),

    -- Approval window
    valid_from          DATE,
    valid_to            DATE,                           -- NULL = no expiry recorded

    -- Dispatch gate — TRUE = block; automatically maintained:
    --   pending / rejected / suspended  →  TRUE
    --   approved                        →  FALSE
    dispatch_blocked    BOOLEAN     NOT NULL DEFAULT TRUE,

    -- Supporting documentation
    certificate_ref     TEXT,                           -- NAFDAC certificate number / reference
    document_archive_id UUID        REFERENCES document_archive(id) ON DELETE SET NULL,

    -- Audit
    registered_by       TEXT        NOT NULL,           -- user UUID or name
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    rejection_reason    TEXT,
    notes               TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique batch per product to prevent duplicate entries
CREATE UNIQUE INDEX IF NOT EXISTS uidx_nafdac_batch_product
    ON nafdac_batch_registry (batch_number, product_name);

CREATE INDEX IF NOT EXISTS idx_nafdac_status         ON nafdac_batch_registry (status);
CREATE INDEX IF NOT EXISTS idx_nafdac_dispatch_block ON nafdac_batch_registry (dispatch_blocked) WHERE dispatch_blocked = TRUE;
CREATE INDEX IF NOT EXISTS idx_nafdac_batch_number   ON nafdac_batch_registry (batch_number);
CREATE INDEX IF NOT EXISTS idx_nafdac_product        ON nafdac_batch_registry (lower(product_name));
CREATE INDEX IF NOT EXISTS idx_nafdac_valid_to       ON nafdac_batch_registry (valid_to)
    WHERE valid_to IS NOT NULL;

COMMENT ON TABLE nafdac_batch_registry IS
    'Per-batch NAFDAC regulatory approval register. dispatch_blocked is the '
    'authoritative flag checked at point of dispatch / invoice finalization. '
    'It is set TRUE automatically for any non-approved status and cleared only '
    'when status transitions to approved.';

-- ---------------------------------------------------------------------------
-- 3. Auto-update trigger for nafdac_batch_registry
--    Reuses the tg_qms_set_updated_at() function created in migration 070.
--    Also enforces the dispatch_blocked business rule on every UPDATE.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION tg_nafdac_sync_dispatch_block()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Keep dispatch_blocked in sync with status automatically
    NEW.dispatch_blocked := (NEW.status <> 'approved');
    NEW.updated_at       := NOW();
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'nafdac_batch_registry_sync_block'
    ) THEN
        CREATE TRIGGER nafdac_batch_registry_sync_block
            BEFORE INSERT OR UPDATE ON nafdac_batch_registry
            FOR EACH ROW EXECUTE FUNCTION tg_nafdac_sync_dispatch_block();
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 4. Row-Level Security
--    Auth enforced at FastAPI layer (JWT middleware).
--    Permissive policies — no Supabase-specific roles required.
-- ---------------------------------------------------------------------------
ALTER TABLE temperature_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE nafdac_batch_registry   ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "allow_all_temperature_logs"
        ON temperature_logs FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "allow_all_nafdac_batch_registry"
        ON nafdac_batch_registry FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 5. Helper views
-- ---------------------------------------------------------------------------

-- Active temperature deviations not yet escalated
CREATE OR REPLACE VIEW v_temp_deviations_pending AS
SELECT
    tl.id,
    tl.location,
    tl.equipment_id,
    er.equipment_name,
    tl.reading_celsius,
    tl.min_threshold,
    tl.max_threshold,
    tl.log_session,
    tl.logged_by,
    tl.logged_at,
    tl.escalation_notes,
    tl.deviation_report_id
FROM temperature_logs tl
LEFT JOIN equipment_registry er ON er.id = tl.equipment_id
WHERE tl.is_deviation = TRUE
  AND tl.deviation_escalated = FALSE
ORDER BY tl.logged_at DESC;

-- NAFDAC batches currently blocking dispatch
CREATE OR REPLACE VIEW v_nafdac_dispatch_blocks AS
SELECT
    id,
    batch_number,
    product_name,
    nafdac_reg_number,
    supplier,
    status,
    valid_from,
    valid_to,
    certificate_ref,
    registered_by,
    notes,
    created_at
FROM nafdac_batch_registry
WHERE dispatch_blocked = TRUE
ORDER BY created_at DESC;

COMMIT;
