-- Migration 078: Finance & Accounting Module
-- Adds tables for AR threshold alerts, invoice matching events,
-- vendor payment approvals, and audit-ready export logging.
-- Driven by Finance & Accounting requirements gathering (April 2026).
-- Finance Director respondent: OGUNDOYIN OLUYEMI EMMANUEL
-- -----------------------------------------------------------------------

-- -----------------------------------------------------------------------
-- 1. AR Alert Rules — configurable balance-over-threshold triggers
--    (Requirement: "AR threshold alerts — client balance > configurable
--     threshold for 30+ days")
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_ar_alert_rules (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    threshold_amount NUMERIC    NOT NULL CHECK (threshold_amount > 0),
    days_overdue_min INT        NOT NULL DEFAULT 30 CHECK (days_overdue_min >= 0),
    customer_id     TEXT,          -- NULL = rule applies to ALL customers
    description     TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    notify_emails   TEXT[]      NOT NULL DEFAULT '{}',
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fin_ar_alert_rules_active
    ON fin_ar_alert_rules (is_active);

-- -----------------------------------------------------------------------
-- 2. AR Alert Events — record of each time a rule fired
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_ar_alert_events (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id          UUID        NOT NULL REFERENCES fin_ar_alert_rules(id) ON DELETE CASCADE,
    customer_id      TEXT        NOT NULL,
    customer_name    TEXT,
    outstanding_balance NUMERIC  NOT NULL,
    days_overdue     INT         NOT NULL,
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged     BOOLEAN     NOT NULL DEFAULT FALSE,
    acknowledged_by  UUID,
    acknowledged_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fin_ar_alert_events_rule
    ON fin_ar_alert_events (rule_id);

CREATE INDEX IF NOT EXISTS idx_fin_ar_alert_events_unacked
    ON fin_ar_alert_events (acknowledged) WHERE acknowledged = FALSE;

-- -----------------------------------------------------------------------
-- 3. Vendor Payment Requests — request → MD approval → paid workflow
--    (Requirement: "Vendor payment approval workflow")
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_vendor_payment_requests (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_id       TEXT        NOT NULL,
    vendor_name     TEXT,
    amount          NUMERIC     NOT NULL CHECK (amount > 0),
    currency        TEXT        NOT NULL DEFAULT 'NGN',
    payment_date    DATE,
    reference       TEXT,
    description     TEXT,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'paid', 'cancelled')),
    requested_by    UUID,
    approved_by     UUID,
    approval_note   TEXT,
    approved_at     TIMESTAMPTZ,
    paid_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fin_vendor_payments_status
    ON fin_vendor_payment_requests (status);

CREATE INDEX IF NOT EXISTS idx_fin_vendor_payments_vendor
    ON fin_vendor_payment_requests (vendor_id);

-- -----------------------------------------------------------------------
-- 4. Audit Export Log — stamped record of every report exported
--    (Requirement: "Audit-ready financial exports with digital trail")
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_audit_export_log (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type  TEXT        NOT NULL,  -- 'pl', 'ar_aging', 'ar_match', 'payroll', 'cashflow'
    exported_by  UUID,
    exported_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count    INT,
    period       TEXT,
    file_format  TEXT        NOT NULL DEFAULT 'pdf',
    filters      JSONB       NOT NULL DEFAULT '{}',
    metadata     JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_fin_audit_export_report
    ON fin_audit_export_log (report_type, exported_at DESC);

-- -----------------------------------------------------------------------
-- 5. Row-Level Security
--    Auth is enforced at the FastAPI layer (JWT middleware).
--    Permissive policies are used — no Supabase-specific roles required.
-- -----------------------------------------------------------------------
ALTER TABLE fin_ar_alert_rules          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_ar_alert_events         ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_vendor_payment_requests  ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_audit_export_log         ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "allow_all_fin_ar_alert_rules"
        ON fin_ar_alert_rules FOR ALL USING (TRUE) WITH CHECK (TRUE);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "allow_all_fin_ar_alert_events"
        ON fin_ar_alert_events FOR ALL USING (TRUE) WITH CHECK (TRUE);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "allow_all_fin_vendor_payments"
        ON fin_vendor_payment_requests FOR ALL USING (TRUE) WITH CHECK (TRUE);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "allow_all_fin_audit_export_log"
        ON fin_audit_export_log FOR ALL USING (TRUE) WITH CHECK (TRUE);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
