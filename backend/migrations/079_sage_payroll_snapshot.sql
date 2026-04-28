-- =============================================================================
-- Migration 079 — sage_payroll_snapshot
-- =============================================================================
-- Purpose: Add payroll snapshot table to support Finance Tier-2 payroll summary
--          and period-over-period variance endpoints.
-- Seeded via: Sage CSV export (file_type = "hr_payroll") through sage_csv_import
-- =============================================================================

-- -------------------------------------------------------------------
-- Table: sage_payroll_snapshot
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sage_payroll_snapshot (
    id                UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    employee_id       TEXT        NOT NULL,
    department        TEXT,
    period            TEXT,                              -- e.g. "2025-04" or "April 2025"
    salary            NUMERIC(14, 2) NOT NULL DEFAULT 0,
    overtime_hours    NUMERIC(10, 2) DEFAULT 0,
    overtime_rate     NUMERIC(14, 2) DEFAULT 0,
    total_gross       NUMERIC(14, 2) DEFAULT 0,
    deductions        NUMERIC(14, 2) DEFAULT 0,
    net_pay           NUMERIC(14, 2) DEFAULT 0,
    batch_id          TEXT        NOT NULL,
    imported_at       TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Indexes for finance queries
CREATE INDEX IF NOT EXISTS idx_payroll_snapshot_batch   ON sage_payroll_snapshot (batch_id);
CREATE INDEX IF NOT EXISTS idx_payroll_snapshot_emp     ON sage_payroll_snapshot (employee_id);
CREATE INDEX IF NOT EXISTS idx_payroll_snapshot_period  ON sage_payroll_snapshot (period);
CREATE INDEX IF NOT EXISTS idx_payroll_snapshot_dept    ON sage_payroll_snapshot (department);

-- Row-level security
-- Auth is enforced at the FastAPI layer (JWT middleware).
-- Permissive policy — no Supabase-specific roles required.
ALTER TABLE sage_payroll_snapshot ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "allow_all_payroll_snapshot"
        ON sage_payroll_snapshot FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TABLE sage_payroll_snapshot IS
    'Rolling payroll import snapshots from Sage HR export. '
    'Each import batch tagged with batch_id. Latest batch used for current summary.';
