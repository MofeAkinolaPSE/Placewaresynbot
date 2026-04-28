-- Migration 077: Sales CRM Pipeline Enhancements
-- Adds pharma-specific pipeline stages, follow-up reminders,
-- bulk messaging queue, weekly report cache, and NLQ history.
-- Driven by Sales & Business Development requirements gathering (April 2026).

-- -----------------------------------------------------------------------
-- 1. Extend crm_stage enum: add payment_plan stage
--    (Requested by Regional Manager: deals with agreed terms before payment)
-- -----------------------------------------------------------------------
DO $$ BEGIN
    ALTER TYPE crm_stage ADD VALUE IF NOT EXISTS 'payment_plan';
EXCEPTION WHEN others THEN NULL; END $$;

-- -----------------------------------------------------------------------
-- 2. Pharma-specific columns on customers
-- -----------------------------------------------------------------------
ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS storage_capacity  TEXT,          -- e.g. "cold room 200L"
    ADD COLUMN IF NOT EXISTS facility_type     TEXT,          -- "hospital", "pharmacy", "clinic"
    ADD COLUMN IF NOT EXISTS client_type       TEXT DEFAULT 'hospital',
    ADD COLUMN IF NOT EXISTS payment_terms_days INT DEFAULT 30,
    ADD COLUMN IF NOT EXISTS last_ordered_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS competing_supplier TEXT;          -- previous/current supplier intel

-- -----------------------------------------------------------------------
-- 3. Enriched lead-level fields (field reps requested these for every opp)
-- -----------------------------------------------------------------------
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS company_name      TEXT,
    ADD COLUMN IF NOT EXISTS contact_person    TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone     TEXT,
    ADD COLUMN IF NOT EXISTS product_interest  TEXT[],        -- e.g. {"Lantus","MMR","Flu"}
    ADD COLUMN IF NOT EXISTS payment_terms     TEXT,
    ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_action       TEXT,
    ADD COLUMN IF NOT EXISTS notes             TEXT;

-- -----------------------------------------------------------------------
-- 4. Follow-up reminders table
--    (Reps follow up manually today; this table drives automated reminders)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_follow_up_reminders (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id       BIGINT      REFERENCES leads(id) ON DELETE CASCADE,
    customer_id   BIGINT      REFERENCES customers(id) ON DELETE CASCADE,
    assigned_rep  UUID,
    reminder_type TEXT        NOT NULL DEFAULT 'follow_up',
    due_at        TIMESTAMPTZ NOT NULL,
    note          TEXT,
    status        TEXT        NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'done', 'dismissed', 'snoozed')),
    created_by    UUID,
    created_at    TIMESTAMPTZ DEFAULT now(),
    completed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_crm_followup_rep    ON crm_follow_up_reminders(assigned_rep);
CREATE INDEX IF NOT EXISTS idx_crm_followup_due    ON crm_follow_up_reminders(due_at);
CREATE INDEX IF NOT EXISTS idx_crm_followup_status ON crm_follow_up_reminders(status);

-- -----------------------------------------------------------------------
-- 5. Bulk message jobs table
--    (WhatsApp / SMS / Email broadcast to client segments)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_bulk_message_jobs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by       UUID,
    channel          TEXT        NOT NULL DEFAULT 'whatsapp'
                                 CHECK (channel IN ('whatsapp', 'email', 'sms')),
    message_text     TEXT        NOT NULL,
    subject          TEXT,
    recipient_filter JSONB       DEFAULT '{}'::jsonb,
    recipient_count  INT         DEFAULT 0,
    status           TEXT        NOT NULL DEFAULT 'queued'
                                 CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    sent_count       INT         DEFAULT 0,
    failed_count     INT         DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT now(),
    processed_at     TIMESTAMPTZ,
    metadata         JSONB       DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_status     ON crm_bulk_message_jobs(status);
CREATE INDEX IF NOT EXISTS idx_crm_bulk_created_at ON crm_bulk_message_jobs(created_at DESC);

-- -----------------------------------------------------------------------
-- 6. Weekly sales report cache
--    (Auto-generated Monday; optionally emailed to manager)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_weekly_reports (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start    DATE        NOT NULL,
    week_end      DATE        NOT NULL,
    generated_by  UUID,
    report_data   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    emailed_to    JSONB       DEFAULT '[]'::jsonb,
    generated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (week_start)
);

-- -----------------------------------------------------------------------
-- 7. NLQ (plain-language query) history log
--    ("Which clients have not ordered in 60 days?")
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_nlq_history (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text    TEXT        NOT NULL,
    response_text TEXT,
    queried_by    UUID,
    queried_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_nlq_queried_by ON crm_nlq_history(queried_by);
CREATE INDEX IF NOT EXISTS idx_crm_nlq_queried_at ON crm_nlq_history(queried_at DESC);

-- -----------------------------------------------------------------------
-- 8. Interaction / Activity Log
--    (Gap-fill: survey Q3 — record calls, visits, site visits, demos)
--    Replaces reps using WhatsApp + notepad to document client touchpoints.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_interaction_log (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id           BIGINT      NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    interaction_type  TEXT        NOT NULL
                                  CHECK (interaction_type IN (
                                      'call','visit','site_visit','demo',
                                      'email','whatsapp','meeting')),
    summary           TEXT        NOT NULL,
    outcome           TEXT,
    next_step         TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    logged_by         UUID,
    created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_interaction_lead ON crm_interaction_log(lead_id);
CREATE INDEX IF NOT EXISTS idx_crm_interaction_type ON crm_interaction_log(interaction_type);
CREATE INDEX IF NOT EXISTS idx_crm_interaction_at   ON crm_interaction_log(occurred_at DESC);

-- -----------------------------------------------------------------------
-- 9. Sales Targets
--    (Gap-fill: survey Q6 — weekly/monthly/quarterly targets set by
--     Finance Manager / MD; compared against won deal values in reports)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_sales_targets (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rep_id        UUID,                               -- NULL = team-level target
    period        TEXT        NOT NULL,               -- '2026-04' | '2026-W16' | '2026-Q2'
    period_type   TEXT        NOT NULL DEFAULT 'monthly'
                              CHECK (period_type IN ('weekly','monthly','quarterly')),
    target_value  NUMERIC(14,2) NOT NULL DEFAULT 0,
    target_deals  INT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (rep_id, period)
);

CREATE INDEX IF NOT EXISTS idx_crm_targets_period   ON crm_sales_targets(period);
CREATE INDEX IF NOT EXISTS idx_crm_targets_rep      ON crm_sales_targets(rep_id);
