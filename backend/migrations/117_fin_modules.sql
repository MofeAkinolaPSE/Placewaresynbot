-- =============================================================================
-- Migration 117 — ACE Books: operational finance modules
-- =============================================================================
-- Subledgers that post through the kernel (migration 116):
--   inventory (products, batches, FIFO cost layers, movements, loans, recalls,
--   counts, adjustments) · sales/AR · purchases/AP · banking & reconciliation
--   · fixed assets · budgets · controls · migration staging.
-- Customer and supplier identity stay in the existing `customers` and
-- `suppliers` tables (source-of-truth rule: one master per party).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Seed the client's legal entity (calendar fiscal year - the client's Sage
-- "Income 12 period" statement runs Jan-Dec).
-- ---------------------------------------------------------------------------
INSERT INTO fin_organizations (code, name) VALUES ('PLACEWARE', 'Placeware Group')
ON CONFLICT (code) DO NOTHING;
INSERT INTO fin_legal_entities (organization_id, code, name, fiscal_year_start_month)
SELECT id, 'PNL', 'Placeware Nigeria Limited', 1 FROM fin_organizations WHERE code='PLACEWARE'
ON CONFLICT (organization_id, code) DO NOTHING;
INSERT INTO fin_settings (legal_entity_id, default_customer_code)
SELECT e.id, 'Sundry' FROM fin_legal_entities e JOIN fin_organizations o ON o.id=e.organization_id
WHERE o.code='PLACEWARE' AND e.code='PNL'
ON CONFLICT (legal_entity_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_products (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id       UUID NOT NULL REFERENCES fin_legal_entities(id),
    sku                   TEXT NOT NULL,
    name                  TEXT NOT NULL,
    product_type          TEXT NOT NULL DEFAULT 'INVENTORY' CHECK (product_type IN ('INVENTORY','SERVICE','NON_INVENTORY')),
    uom                   TEXT DEFAULT 'Each',
    revenue_account_id    UUID REFERENCES fin_accounts(id),
    inventory_account_id  UUID REFERENCES fin_accounts(id),
    cogs_account_id       UUID REFERENCES fin_accounts(id),
    standard_price        NUMERIC(20,2),
    reorder_level         NUMERIC(18,4),
    is_batch_tracked      BOOLEAN NOT NULL DEFAULT TRUE,
    legacy_class          TEXT,
    status                TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, sku)
);

CREATE TABLE IF NOT EXISTS fin_batches (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    sku              TEXT NOT NULL,
    batch_number     TEXT NOT NULL,
    manufacture_date DATE,
    expiry_date      DATE,
    supplier_id      UUID,
    status           TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN (
                        'AVAILABLE','QUARANTINED','RECALLED','EXPIRED','DAMAGED','CLOSED')),
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, sku, batch_number)
);

CREATE TABLE IF NOT EXISTS fin_inventory_transactions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    txn_date         DATE NOT NULL,
    sku              TEXT NOT NULL,
    batch_id         UUID REFERENCES fin_batches(id),
    txn_type         TEXT NOT NULL CHECK (txn_type IN (
                        'OPENING_BALANCE','PURCHASE','SALE','RETURN_IN','RETURN_OUT','ADJUSTMENT','DAMAGE',
                        'EXPIRY','RECALL','LOAN_OUT','LOAN_RETURN','STOCK_COUNT','BATCH_REPLACEMENT',
                        'TRANSFER_IN','TRANSFER_OUT')),
    quantity         NUMERIC(18,4) NOT NULL CHECK (quantity <> 0),
    unit_cost        NUMERIC(20,6) NOT NULL DEFAULT 0,
    total_cost       NUMERIC(20,2) NOT NULL DEFAULT 0,
    source_type      TEXT,
    source_id        TEXT,
    reference        TEXT,
    reason           TEXT,
    customer_id      BIGINT,
    supplier_id      UUID,
    journal_id       UUID REFERENCES fin_journals(id),
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_inv_sku ON fin_inventory_transactions (legal_entity_id, sku, txn_date);
CREATE INDEX IF NOT EXISTS idx_fin_inv_batch ON fin_inventory_transactions (batch_id);
CREATE INDEX IF NOT EXISTS idx_fin_inv_source ON fin_inventory_transactions (source_type, source_id);

-- Inventory history is append-only like the GL.
CREATE OR REPLACE FUNCTION fin_inventory_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.journal_id IS DISTINCT FROM OLD.journal_id AND OLD.journal_id IS NULL
       AND NEW.quantity = OLD.quantity AND NEW.total_cost = OLD.total_cost THEN
        RETURN NEW;  -- linking the journal created in the same posting is allowed
    END IF;
    RAISE EXCEPTION 'FIN_POSTED_IMMUTABLE: inventory movements cannot be changed; post a correcting movement';
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_fin_inventory_append_only ON fin_inventory_transactions;
CREATE TRIGGER trg_fin_inventory_append_only BEFORE UPDATE OR DELETE ON fin_inventory_transactions
    FOR EACH ROW EXECUTE FUNCTION fin_inventory_append_only();

-- FIFO cost layers: each inbound movement opens a layer; outbound movements
-- consume the oldest (or the named batch's) layers first.
CREATE TABLE IF NOT EXISTS fin_cost_layers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    sku              TEXT NOT NULL,
    batch_id         UUID REFERENCES fin_batches(id),
    inventory_txn_id UUID NOT NULL REFERENCES fin_inventory_transactions(id),
    layer_date       DATE NOT NULL,
    qty_in           NUMERIC(18,4) NOT NULL CHECK (qty_in > 0),
    qty_remaining    NUMERIC(18,4) NOT NULL,
    unit_cost        NUMERIC(20,6) NOT NULL CHECK (unit_cost >= 0),
    CHECK (qty_remaining >= 0 AND qty_remaining <= qty_in)
);
CREATE INDEX IF NOT EXISTS idx_fin_layers_open ON fin_cost_layers (legal_entity_id, sku, layer_date) WHERE qty_remaining > 0;

CREATE TABLE IF NOT EXISTS fin_layer_consumptions (
    id               BIGSERIAL PRIMARY KEY,
    layer_id         UUID NOT NULL REFERENCES fin_cost_layers(id),
    inventory_txn_id UUID NOT NULL REFERENCES fin_inventory_transactions(id),
    quantity         NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    unit_cost        NUMERIC(20,6) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fin_consumption_txn ON fin_layer_consumptions (inventory_txn_id);
CREATE INDEX IF NOT EXISTS idx_fin_consumption_layer ON fin_layer_consumptions (layer_id);

CREATE TABLE IF NOT EXISTS fin_stock_adjustments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    adjustment_number TEXT NOT NULL,
    adjustment_date  DATE NOT NULL,
    reason_code      TEXT NOT NULL CHECK (reason_code IN (
                        'DAMAGE','EXPIRY','SHORTAGE','EXCESS','COUNT_CORRECTION','DATA_CORRECTION','OTHER')),
    notes            TEXT,
    status           TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','POSTED','REJECTED')),
    total_value      NUMERIC(20,2) NOT NULL DEFAULT 0,
    journal_id       UUID REFERENCES fin_journals(id),
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_by        TEXT,
    posted_at        TIMESTAMPTZ,
    UNIQUE (legal_entity_id, adjustment_number)
);
CREATE TABLE IF NOT EXISTS fin_stock_adjustment_lines (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    adjustment_id    UUID NOT NULL REFERENCES fin_stock_adjustments(id) ON DELETE CASCADE,
    line_no          INT NOT NULL,
    sku              TEXT NOT NULL,
    batch_id         UUID REFERENCES fin_batches(id),
    quantity         NUMERIC(18,4) NOT NULL CHECK (quantity <> 0),
    unit_cost        NUMERIC(20,6),
    value            NUMERIC(20,2),
    reason           TEXT,
    inventory_txn_id UUID REFERENCES fin_inventory_transactions(id)
);

CREATE TABLE IF NOT EXISTS fin_stock_counts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    count_number     TEXT NOT NULL,
    count_date       DATE NOT NULL,
    status           TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','POSTED')),
    notes            TEXT,
    adjustment_id    UUID REFERENCES fin_stock_adjustments(id),
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_by        TEXT,
    posted_at        TIMESTAMPTZ,
    UNIQUE (legal_entity_id, count_number)
);
CREATE TABLE IF NOT EXISTS fin_stock_count_lines (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    count_id         UUID NOT NULL REFERENCES fin_stock_counts(id) ON DELETE CASCADE,
    sku              TEXT NOT NULL,
    batch_id         UUID REFERENCES fin_batches(id),
    system_qty       NUMERIC(18,4) NOT NULL,
    counted_qty      NUMERIC(18,4),
    reason           TEXT,
    UNIQUE (count_id, sku, batch_id)
);

CREATE TABLE IF NOT EXISTS fin_stock_loans (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id     UUID NOT NULL REFERENCES fin_legal_entities(id),
    loan_number         TEXT NOT NULL,
    customer_id         BIGINT NOT NULL,
    sku                 TEXT NOT NULL,
    batch_id            UUID REFERENCES fin_batches(id),
    quantity            NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    quantity_returned   NUMERIC(18,4) NOT NULL DEFAULT 0,
    unit_cost           NUMERIC(20,6) NOT NULL DEFAULT 0,
    loan_date           DATE NOT NULL,
    expected_return_date DATE,
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN (
                           'OPEN','PARTIALLY_RETURNED','RETURNED','CONVERTED_TO_SALE','WRITTEN_OFF')),
    notes               TEXT,
    out_txn_id          UUID REFERENCES fin_inventory_transactions(id),
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (quantity_returned <= quantity),
    UNIQUE (legal_entity_id, loan_number)
);
CREATE TABLE IF NOT EXISTS fin_stock_loan_returns (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id       UUID NOT NULL REFERENCES fin_stock_loans(id),
    return_date   DATE NOT NULL,
    quantity      NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    batch_id      UUID REFERENCES fin_batches(id),
    txn_id        UUID REFERENCES fin_inventory_transactions(id),
    notes         TEXT,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin_recalls (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    recall_number    TEXT NOT NULL,
    sku              TEXT NOT NULL,
    batch_id         UUID NOT NULL REFERENCES fin_batches(id),
    reason           TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    notes            TEXT,
    opened_by        TEXT,
    opened_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_by        TEXT,
    closed_at        TIMESTAMPTZ,
    UNIQUE (legal_entity_id, recall_number)
);
CREATE TABLE IF NOT EXISTS fin_recall_items (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recall_id          UUID NOT NULL REFERENCES fin_recalls(id) ON DELETE CASCADE,
    customer_id        BIGINT,
    invoice_id         UUID,
    invoice_number     TEXT,
    quantity_sold      NUMERIC(18,4) NOT NULL DEFAULT 0,
    quantity_returned  NUMERIC(18,4) NOT NULL DEFAULT 0,
    contact_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK (contact_status IN (
                          'PENDING','CONTACTED','RETURNED','NOT_RETURNED')),
    notes              TEXT,
    updated_by         TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Banking (bank + cash accounts are fronts for GL cash accounts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_bank_accounts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    gl_account_id    UUID NOT NULL REFERENCES fin_accounts(id),
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'BANK' CHECK (kind IN ('BANK','CASH','PETTY_CASH')),
    bank_name        TEXT,
    account_number   TEXT,
    currency         CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    status           TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, gl_account_id)
);

CREATE TABLE IF NOT EXISTS fin_cash_vouchers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id     UUID NOT NULL REFERENCES fin_legal_entities(id),
    voucher_number      TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('SPEND','RECEIVE','TRANSFER')),
    voucher_date        DATE NOT NULL,
    bank_account_id     UUID NOT NULL REFERENCES fin_bank_accounts(id),
    to_bank_account_id  UUID REFERENCES fin_bank_accounts(id),
    payee               TEXT,
    reference           TEXT,
    description         TEXT,
    amount              NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    status              TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED','VOID')),
    journal_id          UUID REFERENCES fin_journals(id),
    void_journal_id     UUID REFERENCES fin_journals(id),
    void_reason         TEXT,
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, voucher_number)
);
CREATE TABLE IF NOT EXISTS fin_cash_voucher_lines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voucher_id      UUID NOT NULL REFERENCES fin_cash_vouchers(id),
    line_no         INT NOT NULL,
    account_id      UUID NOT NULL REFERENCES fin_accounts(id),
    description     TEXT,
    amount          NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    department_id   UUID REFERENCES fin_departments(id),
    cost_centre_id  UUID REFERENCES fin_cost_centres(id)
);

CREATE TABLE IF NOT EXISTS fin_bank_statements (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id   UUID NOT NULL REFERENCES fin_legal_entities(id),
    bank_account_id   UUID NOT NULL REFERENCES fin_bank_accounts(id),
    statement_date    DATE NOT NULL,
    opening_balance   NUMERIC(20,2),
    closing_balance   NUMERIC(20,2) NOT NULL,
    source_file       TEXT,
    status            TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RECONCILED')),
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS fin_bank_statement_lines (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    statement_id             UUID NOT NULL REFERENCES fin_bank_statements(id) ON DELETE CASCADE,
    line_no                  INT NOT NULL,
    line_date                DATE NOT NULL,
    description              TEXT,
    reference                TEXT,
    amount                   NUMERIC(20,2) NOT NULL,
    match_status             TEXT NOT NULL DEFAULT 'UNMATCHED' CHECK (match_status IN (
                                'UNMATCHED','MATCHED','EXCEPTION','IGNORED')),
    matched_journal_line_id  UUID REFERENCES fin_journal_lines(id),
    note                     TEXT
);
CREATE INDEX IF NOT EXISTS idx_fin_stmt_lines ON fin_bank_statement_lines (statement_id, match_status);

CREATE TABLE IF NOT EXISTS fin_reconciliations (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id    UUID NOT NULL REFERENCES fin_legal_entities(id),
    reconciliation_number TEXT NOT NULL,
    bank_account_id    UUID NOT NULL REFERENCES fin_bank_accounts(id),
    statement_id       UUID REFERENCES fin_bank_statements(id),
    as_of              DATE NOT NULL,
    statement_balance  NUMERIC(20,2) NOT NULL,
    book_balance       NUMERIC(20,2),
    cleared_balance    NUMERIC(20,2),
    difference         NUMERIC(20,2),
    status             TEXT NOT NULL DEFAULT 'IN_PROGRESS' CHECK (status IN ('IN_PROGRESS','COMPLETED')),
    created_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_by       TEXT,
    completed_at       TIMESTAMPTZ,
    UNIQUE (legal_entity_id, reconciliation_number)
);
-- Journal lines are immutable, so "cleared in bank rec" lives beside them.
CREATE TABLE IF NOT EXISTS fin_cleared_lines (
    journal_line_id    UUID PRIMARY KEY REFERENCES fin_journal_lines(id),
    bank_account_id    UUID NOT NULL REFERENCES fin_bank_accounts(id),
    reconciliation_id  UUID REFERENCES fin_reconciliations(id),
    statement_line_id  UUID REFERENCES fin_bank_statement_lines(id),
    cleared_date       DATE NOT NULL,
    cleared_by         TEXT,
    cleared_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Sales & Accounts Receivable
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_sales_invoices (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id        UUID NOT NULL REFERENCES fin_legal_entities(id),
    invoice_number         TEXT NOT NULL,
    customer_id            BIGINT NOT NULL,
    invoice_date           DATE NOT NULL,
    due_date               DATE NOT NULL,
    terms_days             INT,
    currency               CHAR(3) NOT NULL DEFAULT 'NGN' REFERENCES fin_currencies(code),
    subtotal               NUMERIC(20,2) NOT NULL DEFAULT 0,
    discount_total         NUMERIC(20,2) NOT NULL DEFAULT 0,
    charge_total           NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_total              NUMERIC(20,2) NOT NULL DEFAULT 0,
    total                  NUMERIC(20,2) NOT NULL DEFAULT 0,
    amount_settled         NUMERIC(20,2) NOT NULL DEFAULT 0,
    status                 TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
                              'DRAFT','POSTED','PARTIALLY_PAID','PAID','VOID')),
    source_type            TEXT NOT NULL DEFAULT 'MANUAL' CHECK (source_type IN ('MANUAL','FRONTDESK','OPENING')),
    source_id              TEXT,
    reference              TEXT,
    notes                  TEXT,
    journal_id             UUID REFERENCES fin_journals(id),
    void_journal_id        UUID REFERENCES fin_journals(id),
    is_opening             BOOLEAN NOT NULL DEFAULT FALSE,
    credit_check           JSONB,
    credit_override_by     TEXT,
    credit_override_reason TEXT,
    created_by             TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_by              TEXT,
    posted_at              TIMESTAMPTZ,
    voided_by              TEXT,
    voided_at              TIMESTAMPTZ,
    void_reason            TEXT,
    CHECK (amount_settled >= 0 AND amount_settled <= total),
    UNIQUE (legal_entity_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS idx_fin_si_customer ON fin_sales_invoices (legal_entity_id, customer_id, status);
CREATE INDEX IF NOT EXISTS idx_fin_si_date ON fin_sales_invoices (legal_entity_id, invoice_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fin_si_source ON fin_sales_invoices (legal_entity_id, source_type, source_id)
    WHERE source_id IS NOT NULL AND status <> 'VOID';

CREATE TABLE IF NOT EXISTS fin_sales_invoice_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id        UUID NOT NULL REFERENCES fin_sales_invoices(id) ON DELETE CASCADE,
    line_no           INT NOT NULL,
    line_type         TEXT NOT NULL DEFAULT 'ITEM' CHECK (line_type IN ('ITEM','SERVICE','CHARGE','DISCOUNT')),
    sku               TEXT,
    batch_id          UUID REFERENCES fin_batches(id),
    description       TEXT,
    quantity          NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit_price        NUMERIC(20,2) NOT NULL DEFAULT 0,
    discount_amount   NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total        NUMERIC(20,2) NOT NULL,
    account_id        UUID REFERENCES fin_accounts(id),
    cost_amount       NUMERIC(20,2),
    inventory_txn_id  UUID REFERENCES fin_inventory_transactions(id)
);

CREATE TABLE IF NOT EXISTS fin_credit_notes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id    UUID NOT NULL REFERENCES fin_legal_entities(id),
    credit_note_number TEXT NOT NULL,
    customer_id        BIGINT NOT NULL,
    invoice_id         UUID REFERENCES fin_sales_invoices(id),
    note_date          DATE NOT NULL,
    reason             TEXT NOT NULL,
    return_to_stock    BOOLEAN NOT NULL DEFAULT FALSE,
    total              NUMERIC(20,2) NOT NULL DEFAULT 0,
    amount_settled     NUMERIC(20,2) NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED','VOID')),
    journal_id         UUID REFERENCES fin_journals(id),
    created_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (amount_settled >= 0 AND amount_settled <= total),
    UNIQUE (legal_entity_id, credit_note_number)
);
CREATE TABLE IF NOT EXISTS fin_credit_note_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credit_note_id    UUID NOT NULL REFERENCES fin_credit_notes(id) ON DELETE CASCADE,
    line_no           INT NOT NULL,
    line_type         TEXT NOT NULL DEFAULT 'ITEM' CHECK (line_type IN ('ITEM','SERVICE','CHARGE','DISCOUNT')),
    sku               TEXT,
    batch_id          UUID REFERENCES fin_batches(id),
    description       TEXT,
    quantity          NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit_price        NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total        NUMERIC(20,2) NOT NULL,
    account_id        UUID REFERENCES fin_accounts(id),
    cost_amount       NUMERIC(20,2),
    inventory_txn_id  UUID REFERENCES fin_inventory_transactions(id)
);

CREATE TABLE IF NOT EXISTS fin_customer_receipts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    receipt_number   TEXT NOT NULL,
    customer_id      BIGINT NOT NULL,
    receipt_date     DATE NOT NULL,
    method           TEXT NOT NULL CHECK (method IN ('CASH','TRANSFER','CHEQUE','POS','OTHER')),
    bank_account_id  UUID NOT NULL REFERENCES fin_bank_accounts(id),
    amount           NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    wht_amount       NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (wht_amount >= 0),
    amount_allocated NUMERIC(20,2) NOT NULL DEFAULT 0,
    reference        TEXT,
    notes            TEXT,
    status           TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED','VOID')),
    journal_id       UUID REFERENCES fin_journals(id),
    void_journal_id  UUID REFERENCES fin_journals(id),
    void_reason      TEXT,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (amount_allocated >= 0 AND amount_allocated <= amount + wht_amount),
    UNIQUE (legal_entity_id, receipt_number)
);
CREATE INDEX IF NOT EXISTS idx_fin_rcpt_customer ON fin_customer_receipts (legal_entity_id, customer_id);
CREATE INDEX IF NOT EXISTS idx_fin_rcpt_ref ON fin_customer_receipts (legal_entity_id, lower(reference));

-- One settlement ledger for AR: receipts and credit notes applied to invoices.
CREATE TABLE IF NOT EXISTS fin_ar_allocations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    source_type      TEXT NOT NULL CHECK (source_type IN ('RECEIPT','CREDIT_NOTE')),
    source_id        UUID NOT NULL,
    invoice_id       UUID NOT NULL REFERENCES fin_sales_invoices(id),
    amount           NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    allocation_date  DATE NOT NULL,
    reversed         BOOLEAN NOT NULL DEFAULT FALSE,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_ar_alloc_invoice ON fin_ar_allocations (invoice_id);
CREATE INDEX IF NOT EXISTS idx_fin_ar_alloc_source ON fin_ar_allocations (source_type, source_id);

-- ---------------------------------------------------------------------------
-- Purchases & Accounts Payable
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_supplier_bills (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id          UUID NOT NULL REFERENCES fin_legal_entities(id),
    bill_number              TEXT NOT NULL,
    supplier_id              UUID NOT NULL,
    supplier_invoice_number  TEXT NOT NULL,
    bill_date                DATE NOT NULL,
    due_date                 DATE NOT NULL,
    subtotal                 NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_total                NUMERIC(20,2) NOT NULL DEFAULT 0,
    total                    NUMERIC(20,2) NOT NULL DEFAULT 0,
    amount_settled           NUMERIC(20,2) NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED','PARTIALLY_PAID','PAID','VOID')),
    journal_id               UUID REFERENCES fin_journals(id),
    void_journal_id          UUID REFERENCES fin_journals(id),
    is_opening               BOOLEAN NOT NULL DEFAULT FALSE,
    notes                    TEXT,
    void_reason              TEXT,
    created_by               TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (amount_settled >= 0 AND amount_settled <= total),
    UNIQUE (legal_entity_id, bill_number)
);
-- Duplicate supplier invoice detection is a hard database rule.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fin_bill_supplier_invoice
    ON fin_supplier_bills (legal_entity_id, supplier_id, lower(regexp_replace(supplier_invoice_number, '\s', '', 'g')))
    WHERE status <> 'VOID';

CREATE TABLE IF NOT EXISTS fin_supplier_bill_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bill_id           UUID NOT NULL REFERENCES fin_supplier_bills(id) ON DELETE CASCADE,
    line_no           INT NOT NULL,
    line_type         TEXT NOT NULL CHECK (line_type IN ('ITEM','EXPENSE','ASSET')),
    sku               TEXT,
    batch_id          UUID REFERENCES fin_batches(id),
    description       TEXT,
    quantity          NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit_cost         NUMERIC(20,6) NOT NULL DEFAULT 0,
    line_total        NUMERIC(20,2) NOT NULL,
    account_id        UUID REFERENCES fin_accounts(id),
    inventory_txn_id  UUID REFERENCES fin_inventory_transactions(id),
    asset_id          UUID
);

CREATE TABLE IF NOT EXISTS fin_debit_notes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id   UUID NOT NULL REFERENCES fin_legal_entities(id),
    debit_note_number TEXT NOT NULL,
    supplier_id       UUID NOT NULL,
    bill_id           UUID REFERENCES fin_supplier_bills(id),
    note_date         DATE NOT NULL,
    reason            TEXT NOT NULL,
    total             NUMERIC(20,2) NOT NULL DEFAULT 0,
    amount_settled    NUMERIC(20,2) NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED','VOID')),
    journal_id        UUID REFERENCES fin_journals(id),
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (amount_settled >= 0 AND amount_settled <= total),
    UNIQUE (legal_entity_id, debit_note_number)
);
CREATE TABLE IF NOT EXISTS fin_debit_note_lines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    debit_note_id     UUID NOT NULL REFERENCES fin_debit_notes(id) ON DELETE CASCADE,
    line_no           INT NOT NULL,
    line_type         TEXT NOT NULL DEFAULT 'ITEM' CHECK (line_type IN ('ITEM','EXPENSE')),
    sku               TEXT,
    batch_id          UUID REFERENCES fin_batches(id),
    description       TEXT,
    quantity          NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit_cost         NUMERIC(20,6) NOT NULL DEFAULT 0,
    line_total        NUMERIC(20,2) NOT NULL,
    account_id        UUID REFERENCES fin_accounts(id),
    inventory_txn_id  UUID REFERENCES fin_inventory_transactions(id)
);

CREATE TABLE IF NOT EXISTS fin_supplier_payments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    payment_number   TEXT NOT NULL,
    supplier_id      UUID NOT NULL,
    payment_date     DATE NOT NULL,
    method           TEXT NOT NULL CHECK (method IN ('CASH','TRANSFER','CHEQUE','OTHER')),
    bank_account_id  UUID NOT NULL REFERENCES fin_bank_accounts(id),
    amount           NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    wht_amount       NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (wht_amount >= 0),
    amount_allocated NUMERIC(20,2) NOT NULL DEFAULT 0,
    reference        TEXT,
    notes            TEXT,
    status           TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED','VOID')),
    journal_id       UUID REFERENCES fin_journals(id),
    void_journal_id  UUID REFERENCES fin_journals(id),
    void_reason      TEXT,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (amount_allocated >= 0 AND amount_allocated <= amount + wht_amount),
    UNIQUE (legal_entity_id, payment_number)
);
CREATE INDEX IF NOT EXISTS idx_fin_spay_ref ON fin_supplier_payments (legal_entity_id, lower(reference));

CREATE TABLE IF NOT EXISTS fin_ap_allocations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    source_type      TEXT NOT NULL CHECK (source_type IN ('PAYMENT','DEBIT_NOTE')),
    source_id        UUID NOT NULL,
    bill_id          UUID NOT NULL REFERENCES fin_supplier_bills(id),
    amount           NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    allocation_date  DATE NOT NULL,
    reversed         BOOLEAN NOT NULL DEFAULT FALSE,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_ap_alloc_bill ON fin_ap_allocations (bill_id);
CREATE INDEX IF NOT EXISTS idx_fin_ap_alloc_source ON fin_ap_allocations (source_type, source_id);

-- ---------------------------------------------------------------------------
-- Fixed assets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_asset_categories (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id           UUID NOT NULL REFERENCES fin_legal_entities(id),
    code                      TEXT NOT NULL,
    name                      TEXT NOT NULL,
    asset_account_id          UUID NOT NULL REFERENCES fin_accounts(id),
    accum_dep_account_id      UUID REFERENCES fin_accounts(id),
    dep_expense_account_id    UUID REFERENCES fin_accounts(id),
    disposal_account_id       UUID REFERENCES fin_accounts(id),
    default_life_months       INT CHECK (default_life_months > 0),
    depreciable               BOOLEAN NOT NULL DEFAULT TRUE,
    status                    TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE IF NOT EXISTS fin_fixed_assets (
    id                               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id                  UUID NOT NULL REFERENCES fin_legal_entities(id),
    asset_code                       TEXT NOT NULL,
    name                             TEXT NOT NULL,
    category_id                      UUID NOT NULL REFERENCES fin_asset_categories(id),
    serial_number                    TEXT,
    location                         TEXT,
    department_id                    UUID REFERENCES fin_departments(id),
    acquisition_date                 DATE NOT NULL,
    depreciation_start               DATE NOT NULL,
    cost                             NUMERIC(20,2) NOT NULL CHECK (cost > 0),
    residual_value                   NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (residual_value >= 0),
    useful_life_months               INT CHECK (useful_life_months > 0),
    opening_accumulated_depreciation NUMERIC(20,2) NOT NULL DEFAULT 0,
    status                           TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN (
                                        'ACTIVE','FULLY_DEPRECIATED','DISPOSED')),
    disposal_date                    DATE,
    disposal_proceeds                NUMERIC(20,2),
    acquisition_journal_id           UUID REFERENCES fin_journals(id),
    disposal_journal_id              UUID REFERENCES fin_journals(id),
    is_opening                       BOOLEAN NOT NULL DEFAULT FALSE,
    notes                            TEXT,
    created_by                       TEXT,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (residual_value < cost),
    UNIQUE (legal_entity_id, asset_code)
);

CREATE TABLE IF NOT EXISTS fin_depreciation_runs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    period_id        UUID NOT NULL REFERENCES fin_periods(id),
    run_number       TEXT NOT NULL,
    total            NUMERIC(20,2) NOT NULL DEFAULT 0,
    journal_id       UUID REFERENCES fin_journals(id),
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, period_id)
);
CREATE TABLE IF NOT EXISTS fin_depreciation_lines (
    run_id    UUID NOT NULL REFERENCES fin_depreciation_runs(id) ON DELETE CASCADE,
    asset_id  UUID NOT NULL REFERENCES fin_fixed_assets(id),
    amount    NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    PRIMARY KEY (run_id, asset_id)
);

-- ---------------------------------------------------------------------------
-- Budgets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_budgets (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    fiscal_year_id   UUID NOT NULL REFERENCES fin_fiscal_years(id),
    name             TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','APPROVED')),
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by      TEXT,
    approved_at      TIMESTAMPTZ,
    UNIQUE (legal_entity_id, fiscal_year_id, name)
);
CREATE TABLE IF NOT EXISTS fin_budget_lines (
    budget_id   UUID NOT NULL REFERENCES fin_budgets(id) ON DELETE CASCADE,
    account_id  UUID NOT NULL REFERENCES fin_accounts(id),
    period_id   UUID NOT NULL REFERENCES fin_periods(id),
    amount      NUMERIC(20,2) NOT NULL,
    PRIMARY KEY (budget_id, account_id, period_id)
);

-- ---------------------------------------------------------------------------
-- Controls, integrations, migration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_control_runs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    as_of            DATE NOT NULL,
    results          JSONB NOT NULL,
    fail_count       INT NOT NULL,
    run_by           TEXT,
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Warnings people chose to override (credit limit, possible duplicates ...).
CREATE TABLE IF NOT EXISTS fin_validation_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    entity_type      TEXT NOT NULL,
    entity_id        TEXT,
    entity_ref       TEXT,
    check_code       TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (severity IN ('INFO','WARNING','ERROR','CRITICAL')),
    message          TEXT NOT NULL,
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ACCEPTED','RESOLVED')),
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by      TEXT,
    resolved_at      TIMESTAMPTZ,
    resolution_note  TEXT
);
CREATE INDEX IF NOT EXISTS idx_fin_validation_open ON fin_validation_events (legal_entity_id, status);

-- Postings triggered by other ACE modules (Frontdesk approval ...): one row
-- per source document, so a failure is visible and retryable, never lost.
CREATE TABLE IF NOT EXISTS fin_source_postings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    source_type      TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    source_ref       TEXT,
    status           TEXT NOT NULL CHECK (status IN ('POSTED','FAILED','SKIPPED')),
    document_type    TEXT,
    document_id      UUID,
    message          TEXT,
    attempts         INT NOT NULL DEFAULT 1,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS fin_migration_batches (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id  UUID NOT NULL REFERENCES fin_legal_entities(id),
    kind             TEXT NOT NULL CHECK (kind IN ('COA','TRIAL_BALANCE','OPEN_AR','OPEN_AP','INVENTORY','FIXED_ASSETS')),
    file_name        TEXT,
    as_of_date       DATE,
    status           TEXT NOT NULL DEFAULT 'STAGED' CHECK (status IN ('STAGED','LOADED','DISCARDED')),
    row_count        INT NOT NULL DEFAULT 0,
    summary          JSONB NOT NULL DEFAULT '{}'::jsonb,
    issues           JSONB NOT NULL DEFAULT '[]'::jsonb,
    rows             JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    loaded_by        TEXT,
    loaded_at        TIMESTAMPTZ
);
