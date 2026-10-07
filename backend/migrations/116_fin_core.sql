-- =============================================================================
-- Migration 116 — ACE Books: accounting kernel
-- =============================================================================
-- ACE replaces Sage 50 as the client's system of record. This migration
-- creates the double-entry kernel every financial module posts through:
--   organization -> legal entity -> branch / department / cost centre
--   currencies, fiscal years, periods
--   chart of accounts
--   accounting events -> journals -> journal lines (the only financial truth)
--   append-only audit trail
-- Design: backend/docs/Financial-engine/financial-study/ (Foundation
-- Implementation Pack + Database Specification).
--
-- Integrity is enforced IN THE DATABASE, not only in Python:
--   * a journal cannot become POSTED unless debits = credits, every line
--     hits an active postable account of the same entity, and its period is
--     OPEN;
--   * posted journals and their lines are immutable (corrections = reversal);
--   * audit events are append-only.
-- Tables are prefixed fin_ to stay clear of the existing CRM/ops tables.
-- =============================================================================

CREATE TABLE IF NOT EXISTS fin_currencies (
    code        CHAR(3) PRIMARY KEY,
    name        TEXT NOT NULL,
    symbol      TEXT,
    decimals    SMALLINT NOT NULL DEFAULT 2,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO fin_currencies (code, name, symbol) VALUES
    ('NGN', 'Nigerian Naira', '₦'),
    ('USD', 'US Dollar', '$'),
    ('GBP', 'Pound Sterling', '£'),
    ('EUR', 'Euro', '€')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS fin_organizations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin_legal_entities (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id      UUID NOT NULL REFERENCES fin_organizations(id),
    code                 TEXT NOT NULL,
    name                 TEXT NOT NULL,
    registration_number  TEXT,
    tax_identifier       TEXT,
    base_currency        CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    fiscal_year_start_month SMALLINT NOT NULL DEFAULT 1 CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    status               TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, code)
);

CREATE TABLE IF NOT EXISTS fin_branches (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    code             TEXT NOT NULL,
    name             TEXT NOT NULL,
    address          TEXT,
    status           TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE IF NOT EXISTS fin_departments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    branch_id        UUID REFERENCES fin_branches(id),
    code             TEXT NOT NULL,
    name             TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE IF NOT EXISTS fin_cost_centres (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    department_id    UUID REFERENCES fin_departments(id),
    code             TEXT NOT NULL,
    name             TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    UNIQUE (legal_entity_id, code)
);

-- ---------------------------------------------------------------------------
-- Fiscal calendar
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_fiscal_years (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id    UUID NOT NULL REFERENCES fin_legal_entities(id),
    name               TEXT NOT NULL,
    start_date         DATE NOT NULL,
    end_date           DATE NOT NULL,
    status             TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    closing_journal_id UUID,
    closed_at          TIMESTAMPTZ,
    closed_by          TEXT,
    CHECK (end_date > start_date),
    UNIQUE (legal_entity_id, start_date)
);

CREATE TABLE IF NOT EXISTS fin_periods (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    fiscal_year_id   UUID NOT NULL REFERENCES fin_fiscal_years(id),
    period_number    SMALLINT NOT NULL,
    name             TEXT NOT NULL,
    start_date       DATE NOT NULL,
    end_date         DATE NOT NULL,
    status           TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED','LOCKED')),
    closed_at        TIMESTAMPTZ,
    closed_by        TEXT,
    CHECK (end_date >= start_date),
    UNIQUE (legal_entity_id, start_date),
    UNIQUE (fiscal_year_id, period_number)
);
CREATE INDEX IF NOT EXISTS idx_fin_periods_range ON fin_periods (legal_entity_id, start_date, end_date);

-- ---------------------------------------------------------------------------
-- Chart of accounts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_accounts (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id      UUID NOT NULL REFERENCES fin_legal_entities(id),
    code                 TEXT NOT NULL,
    name                 TEXT NOT NULL,
    account_type         TEXT NOT NULL CHECK (account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')),
    -- Drives statement placement and cash-flow classification.
    subtype              TEXT NOT NULL CHECK (subtype IN (
                            'CASH','RECEIVABLE','INVENTORY','OTHER_CURRENT_ASSET','FIXED_ASSET',
                            'ACCUMULATED_DEPRECIATION','OTHER_ASSET',
                            'PAYABLE','OTHER_CURRENT_LIABILITY','LONG_TERM_LIABILITY',
                            'EQUITY','RETAINED_EARNINGS','EQUITY_CLOSING',
                            'SALES','OTHER_INCOME','COST_OF_SALES','OPERATING_EXPENSE','OTHER_EXPENSE')),
    normal_balance       TEXT NOT NULL CHECK (normal_balance IN ('DEBIT','CREDIT')),
    parent_id            UUID REFERENCES fin_accounts(id),
    is_postable          BOOLEAN NOT NULL DEFAULT TRUE,
    -- Control accounts (AR, AP, inventory) are fed by their subledgers; manual
    -- journals to them need the accounting.journal.control permission.
    is_control           BOOLEAN NOT NULL DEFAULT FALSE,
    currency             CHAR(3) REFERENCES fin_currencies(code),
    description          TEXT,
    legacy_code          TEXT,
    legacy_type          TEXT,
    status               TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    created_by           TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);
CREATE INDEX IF NOT EXISTS idx_fin_accounts_entity ON fin_accounts (legal_entity_id, account_type, subtype);

-- ---------------------------------------------------------------------------
-- Document numbering (gap-free per entity + document type)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_number_sequences (
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    doc_type         TEXT NOT NULL,
    prefix           TEXT NOT NULL,
    next_value       BIGINT NOT NULL DEFAULT 1,
    pad              SMALLINT NOT NULL DEFAULT 6,
    PRIMARY KEY (legal_entity_id, doc_type)
);

-- ---------------------------------------------------------------------------
-- Accounting events -> journals -> lines
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_accounting_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    event_type       TEXT NOT NULL,
    source_type      TEXT,
    source_id        TEXT,
    event_date       DATE NOT NULL,
    period_id        UUID REFERENCES fin_periods(id),
    currency         CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    amount           NUMERIC(20,2),
    status           TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','POSTED','FAILED')),
    idempotency_key  TEXT,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_at        TIMESTAMPTZ,
    UNIQUE (legal_entity_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_fin_events_source ON fin_accounting_events (source_type, source_id);

CREATE TABLE IF NOT EXISTS fin_journals (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    journal_number   TEXT NOT NULL,
    journal_date     DATE NOT NULL,
    period_id        UUID NOT NULL REFERENCES fin_periods(id),
    event_id         UUID REFERENCES fin_accounting_events(id),
    journal_type     TEXT NOT NULL DEFAULT 'MANUAL' CHECK (journal_type IN (
                        'MANUAL','SYSTEM','OPENING','REVERSAL','CLOSING','ADJUSTMENT')),
    source_type      TEXT,
    source_id        TEXT,
    source_ref       TEXT,
    description      TEXT,
    currency         CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    status           TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
                        'DRAFT','SUBMITTED','APPROVED','REJECTED','POSTED','REVERSED')),
    total_debit      NUMERIC(20,2) NOT NULL DEFAULT 0,
    total_credit     NUMERIC(20,2) NOT NULL DEFAULT 0,
    reversal_of_id   UUID REFERENCES fin_journals(id),
    reversed_by_id   UUID REFERENCES fin_journals(id),
    idempotency_key  TEXT,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_by     TEXT,
    submitted_at     TIMESTAMPTZ,
    approved_by      TEXT,
    approved_at      TIMESTAMPTZ,
    rejected_reason  TEXT,
    posted_by        TEXT,
    posted_at        TIMESTAMPTZ,
    UNIQUE (legal_entity_id, journal_number),
    UNIQUE (legal_entity_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_fin_journals_entity_date ON fin_journals (legal_entity_id, journal_date);
CREATE INDEX IF NOT EXISTS idx_fin_journals_status ON fin_journals (legal_entity_id, status);
CREATE INDEX IF NOT EXISTS idx_fin_journals_source ON fin_journals (source_type, source_id);

CREATE TABLE IF NOT EXISTS fin_journal_lines (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_id       UUID NOT NULL REFERENCES fin_journals(id) ON DELETE RESTRICT,
    line_no          INT NOT NULL,
    account_id       UUID NOT NULL REFERENCES fin_accounts(id),
    description      TEXT,
    debit            NUMERIC(20,2) NOT NULL DEFAULT 0,
    credit           NUMERIC(20,2) NOT NULL DEFAULT 0,
    currency         CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    exchange_rate    NUMERIC(20,8) NOT NULL DEFAULT 1,
    base_debit       NUMERIC(20,2) NOT NULL DEFAULT 0,
    base_credit      NUMERIC(20,2) NOT NULL DEFAULT 0,
    branch_id        UUID REFERENCES fin_branches(id),
    department_id    UUID REFERENCES fin_departments(id),
    cost_centre_id   UUID REFERENCES fin_cost_centres(id),
    -- Subledger dimensions: who / what this line is about.
    customer_id      BIGINT,
    supplier_id      UUID,
    product_sku      TEXT,
    CHECK (debit >= 0 AND credit >= 0 AND base_debit >= 0 AND base_credit >= 0),
    CHECK (NOT (debit > 0 AND credit > 0)),
    UNIQUE (journal_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_fin_lines_journal ON fin_journal_lines (journal_id);
CREATE INDEX IF NOT EXISTS idx_fin_lines_account ON fin_journal_lines (account_id);
CREATE INDEX IF NOT EXISTS idx_fin_lines_customer ON fin_journal_lines (customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fin_lines_supplier ON fin_journal_lines (supplier_id) WHERE supplier_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Append-only audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_audit_events (
    id               BIGSERIAL PRIMARY KEY,
    legal_entity_id  UUID REFERENCES fin_legal_entities(id),
    actor_id         TEXT,
    actor_name       TEXT,
    action           TEXT NOT NULL,
    entity_type      TEXT,
    entity_id        TEXT,
    entity_ref       TEXT,
    before_state     JSONB,
    after_state      JSONB,
    reason           TEXT,
    request_id       TEXT,
    ip_address       TEXT,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_fin_audit_entity ON fin_audit_events (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_fin_audit_time ON fin_audit_events (legal_entity_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Integrity triggers
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fin_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'FIN_AUDIT_IMMUTABLE: audit events cannot be modified or deleted';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fin_audit_append_only ON fin_audit_events;
CREATE TRIGGER trg_fin_audit_append_only
    BEFORE UPDATE OR DELETE ON fin_audit_events
    FOR EACH ROW EXECUTE FUNCTION fin_audit_append_only();

-- A journal may only become POSTED if it is balanced, non-empty, every line
-- hits an ACTIVE + postable account of the same entity, and its period is OPEN.
CREATE OR REPLACE FUNCTION fin_journal_guard() RETURNS trigger AS $$
DECLARE
    v_dr NUMERIC(20,2);
    v_cr NUMERIC(20,2);
    v_n  INT;
    v_bad INT;
    v_period_status TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('POSTED','REVERSED') THEN
            RAISE EXCEPTION 'FIN_POSTED_IMMUTABLE: posted journal % cannot be deleted', OLD.journal_number;
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status IN ('POSTED','REVERSED') THEN
        -- The only permitted change to a posted journal is being reversed.
        IF NOT (OLD.status = 'POSTED' AND NEW.status = 'REVERSED'
                AND NEW.reversed_by_id IS NOT NULL
                AND NEW.total_debit = OLD.total_debit AND NEW.total_credit = OLD.total_credit
                AND NEW.journal_date = OLD.journal_date AND NEW.period_id = OLD.period_id) THEN
            RAISE EXCEPTION 'FIN_POSTED_IMMUTABLE: posted journal % cannot be modified; reverse it instead', OLD.journal_number;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status = 'POSTED' THEN
        SELECT COALESCE(SUM(base_debit),0), COALESCE(SUM(base_credit),0), COUNT(*)
          INTO v_dr, v_cr, v_n
          FROM fin_journal_lines WHERE journal_id = NEW.id;
        IF v_n < 2 THEN
            RAISE EXCEPTION 'FIN_UNBALANCED_JOURNAL: journal % has fewer than two lines', NEW.journal_number;
        END IF;
        IF v_dr <> v_cr OR v_dr = 0 THEN
            RAISE EXCEPTION 'FIN_UNBALANCED_JOURNAL: journal % debits % <> credits %', NEW.journal_number, v_dr, v_cr;
        END IF;
        SELECT COUNT(*) INTO v_bad
          FROM fin_journal_lines l JOIN fin_accounts a ON a.id = l.account_id
         WHERE l.journal_id = NEW.id
           AND (a.status <> 'ACTIVE' OR NOT a.is_postable OR a.legal_entity_id <> NEW.legal_entity_id);
        IF v_bad > 0 THEN
            RAISE EXCEPTION 'FIN_ACCOUNT_NOT_POSTABLE: journal % references inactive, non-postable or foreign accounts', NEW.journal_number;
        END IF;
        SELECT status INTO v_period_status FROM fin_periods
         WHERE id = NEW.period_id AND legal_entity_id = NEW.legal_entity_id
           AND NEW.journal_date BETWEEN start_date AND end_date;
        IF v_period_status IS NULL THEN
            RAISE EXCEPTION 'FIN_PERIOD_MISMATCH: journal % date is outside its period', NEW.journal_number;
        END IF;
        IF v_period_status <> 'OPEN' THEN
            RAISE EXCEPTION 'FIN_PERIOD_CLOSED: period for journal % is %', NEW.journal_number, v_period_status;
        END IF;
        NEW.total_debit := v_dr;
        NEW.total_credit := v_cr;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fin_journal_guard ON fin_journals;
CREATE TRIGGER trg_fin_journal_guard
    BEFORE UPDATE OR DELETE ON fin_journals
    FOR EACH ROW EXECUTE FUNCTION fin_journal_guard();

-- Inserting a journal directly as POSTED is routed through the same checks
-- by a deferred constraint trigger (lines are inserted after the header).
CREATE OR REPLACE FUNCTION fin_journal_insert_posted_guard() RETURNS trigger AS $$
DECLARE
    v_dr NUMERIC(20,2);
    v_cr NUMERIC(20,2);
    v_n  INT;
BEGIN
    IF NEW.status = 'POSTED' THEN
        SELECT COALESCE(SUM(base_debit),0), COALESCE(SUM(base_credit),0), COUNT(*)
          INTO v_dr, v_cr, v_n FROM fin_journal_lines WHERE journal_id = NEW.id;
        IF v_n < 2 OR v_dr <> v_cr OR v_dr = 0 THEN
            RAISE EXCEPTION 'FIN_UNBALANCED_JOURNAL: journal % inserted as POSTED is not balanced', NEW.journal_number;
        END IF;
    END IF;
    RETURN NULL;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fin_journal_insert_posted ON fin_journals;
CREATE CONSTRAINT TRIGGER trg_fin_journal_insert_posted
    AFTER INSERT ON fin_journals DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION fin_journal_insert_posted_guard();

-- Lines of a posted journal are frozen.
CREATE OR REPLACE FUNCTION fin_line_guard() RETURNS trigger AS $$
DECLARE
    v_status TEXT;
BEGIN
    SELECT status INTO v_status FROM fin_journals
     WHERE id = COALESCE(NEW.journal_id, OLD.journal_id);
    IF v_status IN ('POSTED','REVERSED') THEN
        RAISE EXCEPTION 'FIN_POSTED_IMMUTABLE: lines of a posted journal cannot be changed';
    END IF;
    RETURN COALESCE(NEW, OLD);
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fin_line_guard ON fin_journal_lines;
CREATE TRIGGER trg_fin_line_guard
    BEFORE INSERT OR UPDATE OR DELETE ON fin_journal_lines
    FOR EACH ROW EXECUTE FUNCTION fin_line_guard();

-- ---------------------------------------------------------------------------
-- The General Ledger is a view over posted lines - never a second table.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW fin_v_general_ledger AS
SELECT
    l.id              AS line_id,
    j.legal_entity_id,
    j.id              AS journal_id,
    j.journal_number,
    j.journal_date,
    j.period_id,
    j.journal_type,
    j.source_type,
    j.source_id,
    j.source_ref,
    j.description     AS journal_description,
    l.line_no,
    l.account_id,
    a.code            AS account_code,
    a.name            AS account_name,
    a.account_type,
    a.subtype,
    a.normal_balance,
    l.description,
    l.base_debit      AS debit,
    l.base_credit     AS credit,
    l.customer_id,
    l.supplier_id,
    l.product_sku,
    l.branch_id,
    l.department_id,
    l.cost_centre_id,
    j.posted_at,
    j.posted_by
FROM fin_journal_lines l
JOIN fin_journals j ON j.id = l.journal_id
JOIN fin_accounts a ON a.id = l.account_id
WHERE j.status IN ('POSTED','REVERSED');

-- ---------------------------------------------------------------------------
-- Entity policy settings + posting-rule account mappings
-- ---------------------------------------------------------------------------
-- Policy that the accountant owns lives here as configuration, never in
-- code (Development Engine spec Rule I).
CREATE TABLE IF NOT EXISTS fin_settings (
    legal_entity_id            UUID PRIMARY KEY REFERENCES fin_legal_entities(id),
    journal_approval_required  BOOLEAN NOT NULL DEFAULT FALSE,
    allow_self_approval        BOOLEAN NOT NULL DEFAULT FALSE,
    credit_limit_mode          TEXT NOT NULL DEFAULT 'WARN' CHECK (credit_limit_mode IN ('OFF','WARN','BLOCK')),
    negative_stock_policy      TEXT NOT NULL DEFAULT 'BLOCK' CHECK (negative_stock_policy IN ('BLOCK','ALLOW')),
    costing_method             TEXT NOT NULL DEFAULT 'FIFO' CHECK (costing_method IN ('FIFO')),
    aging_buckets              INT[] NOT NULL DEFAULT '{30,60,90,120}',
    cutover_date               DATE,
    auto_post_frontdesk        BOOLEAN NOT NULL DEFAULT TRUE,
    default_customer_code      TEXT,
    updated_by                 TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Named roles in posting rules ("where does a delivery charge go?") mapped
-- to real accounts per entity. The rules engine only ever asks for a key.
CREATE TABLE IF NOT EXISTS fin_account_mappings (
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    mapping_key      TEXT NOT NULL,
    account_id       UUID NOT NULL REFERENCES fin_accounts(id),
    note             TEXT,
    updated_by       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (legal_entity_id, mapping_key)
);
