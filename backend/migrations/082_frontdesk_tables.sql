-- =============================================================================
-- Migration 082 — Frontdesk & Client Reception Module
-- =============================================================================
-- Purpose: Create tables for walk-in client intake, invoice lifecycle, and
--          the frontdesk approval pipeline (QC → Finance → Executive).
--
-- Driven by: Frontdesk & Client Reception requirements gathering (April 2026).
--   Respondents: Receptionist/Admin Officer, Folashade Oyeleye (Inventory Officer)
--
-- Key requirements:
--   • Digital walk-in registration with company, email, appointment flag
--   • Invoice auto-generation with line items; branded PDF download
--   • Approval pipeline: QC → Finance Approved → Completed
--   • Returning client detection and history view
--   • Real-time stock check at point of invoice
--   • Auto-notify QC/Inventory when invoice is raised
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Walk-in Register
--    Captures every client visit including returning client context.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS frontdesk_walk_ins (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_name       TEXT        NOT NULL,
    company_name        TEXT,
    contact_phone       TEXT,
    email               TEXT,
    has_appointment     BOOLEAN     NOT NULL DEFAULT FALSE,
    purpose             TEXT        NOT NULL,
    products_requested  TEXT[]      NOT NULL DEFAULT '{}',
    notes               TEXT,
    status              TEXT        NOT NULL DEFAULT 'arrived'
                        CHECK (status IN (
                            'arrived', 'invoiced', 'qc_pending', 'qc_passed', 'qc_failed',
                            'finance_pending', 'finance_approved', 'finance_rejected',
                            'completed', 'cancelled'
                        )),
    registered_by       UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_created  ON frontdesk_walk_ins (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_status   ON frontdesk_walk_ins (status);
CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_customer ON frontdesk_walk_ins (lower(customer_name));
CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_company  ON frontdesk_walk_ins (lower(company_name));
CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_phone    ON frontdesk_walk_ins (contact_phone);
CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_email    ON frontdesk_walk_ins (lower(email));

-- ---------------------------------------------------------------------------
-- 2. Frontdesk Invoices
--    One invoice per walk-in visit. Tracks full approval lifecycle.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS frontdesk_invoices (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Human-readable invoice reference: INV-YYYYMMDD-XXXXXX
    invoice_number      TEXT        NOT NULL DEFAULT (
                            'INV-' || TO_CHAR(NOW(), 'YYYYMMDD') || '-' ||
                            UPPER(SUBSTRING(gen_random_uuid()::TEXT FROM 1 FOR 6))
                        ),
    walk_in_id          UUID        REFERENCES frontdesk_walk_ins(id) ON DELETE SET NULL,
    customer_name       TEXT        NOT NULL,
    company_name        TEXT,
    -- Line items: [{product, quantity, unit_price, line_total}]
    items               JSONB       NOT NULL DEFAULT '[]',
    total_amount        NUMERIC(14, 2) NOT NULL DEFAULT 0,
    payment_method      TEXT        NOT NULL DEFAULT 'cash'
                        CHECK (payment_method IN ('cash', 'transfer', 'credit', 'pos')),
    notes               TEXT,
    -- Approval status (mirrors walk-in status after invoice is raised)
    status              TEXT        NOT NULL DEFAULT 'draft'
                        CHECK (status IN (
                            'draft', 'qc_pending', 'qc_passed', 'qc_failed',
                            'finance_pending', 'finance_approved', 'finance_rejected',
                            'completed', 'cancelled'
                        )),
    -- QC decision
    qc_passed           BOOLEAN,
    qc_inspector        TEXT,
    qc_notes            TEXT,
    qc_batch_numbers    TEXT[]      NOT NULL DEFAULT '{}',
    qc_checked_at       TIMESTAMPTZ,
    -- Finance decision
    finance_approved    BOOLEAN,
    finance_approver    TEXT,
    finance_reason      TEXT,
    finance_decided_at  TIMESTAMPTZ,
    -- Audit
    created_by          UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fd_invoices_walk_in  ON frontdesk_invoices (walk_in_id);
CREATE INDEX IF NOT EXISTS idx_fd_invoices_status   ON frontdesk_invoices (status);
CREATE INDEX IF NOT EXISTS idx_fd_invoices_created  ON frontdesk_invoices (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fd_invoices_customer ON frontdesk_invoices (lower(customer_name));
CREATE INDEX IF NOT EXISTS idx_fd_invoices_number   ON frontdesk_invoices (invoice_number);

-- ---------------------------------------------------------------------------
-- 3. Row-Level Security
--    Auth is enforced at the FastAPI layer (JWT middleware).
--    Permissive policies — no Supabase-specific roles required.
-- ---------------------------------------------------------------------------
ALTER TABLE frontdesk_walk_ins  ENABLE ROW LEVEL SECURITY;
ALTER TABLE frontdesk_invoices  ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "allow_all_fd_walk_ins"
        ON frontdesk_walk_ins FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "allow_all_fd_invoices"
        ON frontdesk_invoices FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 4. Helper view: today's frontdesk summary
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_frontdesk_today AS
SELECT
    w.id                AS walk_in_id,
    w.customer_name,
    w.company_name,
    w.contact_phone,
    w.email,
    w.has_appointment,
    w.purpose,
    w.products_requested,
    w.status            AS walk_in_status,
    w.created_at,
    i.id                AS invoice_id,
    i.invoice_number,
    i.total_amount,
    i.payment_method,
    i.status            AS invoice_status,
    i.qc_passed,
    i.finance_approved
FROM frontdesk_walk_ins w
LEFT JOIN frontdesk_invoices i ON i.walk_in_id = w.id
WHERE w.created_at >= CURRENT_DATE::TIMESTAMPTZ
  AND w.created_at <  (CURRENT_DATE + 1)::TIMESTAMPTZ;

COMMENT ON TABLE frontdesk_walk_ins IS
    'Records every walk-in client visit. Tracks the full lifecycle from arrival '
    'through invoicing, QC, finance approval, and completion.';

COMMENT ON TABLE frontdesk_invoices IS
    'Frontdesk-generated invoices linked to walk-in visits. Contains line items, '
    'payment details, and the full QC→Finance approval chain.';
