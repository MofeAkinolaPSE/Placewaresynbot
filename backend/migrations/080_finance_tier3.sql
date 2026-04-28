-- =============================================================================
-- Migration 080 — Finance Tier 3: Budget Targets
-- =============================================================================
-- Purpose: Budget vs. actual variance tracking.
--   • fin_budget_targets — department/category budgets per period
-- Note: Vendor payment requests already exist (fin_vendor_payment_requests,
--       migration 078). Credit risk scoring is computed dynamically from AR data.
-- =============================================================================

-- -------------------------------------------------------------------
-- Table: fin_budget_targets
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_budget_targets (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    department        TEXT        NOT NULL,
    category          TEXT        NOT NULL DEFAULT 'general',
                                               -- e.g. 'opex', 'payroll', 'marketing', 'procurement'
    period            TEXT        NOT NULL,    -- e.g. '2026-04' (YYYY-MM)
    budgeted_amount   NUMERIC(14, 2) NOT NULL CHECK (budgeted_amount >= 0),
    note              TEXT,
    created_by        UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_budget_dept_cat_period UNIQUE (department, category, period)
);

CREATE INDEX IF NOT EXISTS idx_budget_targets_period     ON fin_budget_targets (period);
CREATE INDEX IF NOT EXISTS idx_budget_targets_dept       ON fin_budget_targets (department);

-- Row-level security
-- Auth is enforced at the FastAPI layer (JWT middleware).
-- Permissive policy — no Supabase-specific roles required.
ALTER TABLE fin_budget_targets ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "allow_all_budget_targets"
        ON fin_budget_targets FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TABLE fin_budget_targets IS
    'Department/category budget targets by period (YYYY-MM). '
    'Used for budget vs. actual variance reporting against GL journal entries.';
