-- 129: Sage 50 full transaction history behind ACE Books (display + lineage only, never posts)
--
-- The client's own Sage reports, loaded line for line so every ACE Books report can go back
-- as far as Sage does (General Ledger from Jan 2017) in Sage's own layouts:
--   fin_sage_gl_lines      every General Ledger transaction line (Account, Date, Reference, Jrnl,
--                          Trans Description, Debit, Credit)
--   fin_sage_gl_balances   Sage's "Beginning Balance" per account per month (the anchors running
--                          balances, trial balances and statements are computed from) plus the
--                          month's "Current Period Change"
--   fin_sage_party_ledger  Customer Ledgers / Vendor Ledgers (Date, Trans No, Type, Debit, Credit, Balance)
--   fin_sage_journal_lines the journals exactly as exported (Sales, Cash Receipts, Cash
--                          Disbursements, Purchase, Cost of Goods Sold, General)
--   fin_sage_loads         what was loaded, from which file, covering which dates
-- Loading a file replaces that kind's rows inside the file's own date range, so later exports
-- (e.g. July to date) never duplicate.
--
-- fin_settings.history_until: the last day Sage is the record. Reports read Sage history up to
-- and including it and ACE Books journals after it.

CREATE TABLE IF NOT EXISTS fin_sage_loads (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES fin_legal_entities(id),
    kind            text NOT NULL,
    file_name       text,
    date_from       date,
    date_to         date,
    row_count       integer NOT NULL DEFAULT 0,
    summary         jsonb NOT NULL DEFAULT '{}'::jsonb,
    loaded_by       text,
    loaded_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_loads_kind ON fin_sage_loads (legal_entity_id, kind, date_from, date_to);

CREATE TABLE IF NOT EXISTS fin_sage_gl_lines (
    id              bigserial PRIMARY KEY,
    legal_entity_id uuid NOT NULL REFERENCES fin_legal_entities(id),
    load_id         uuid,
    account_code    text NOT NULL,
    txn_date        date NOT NULL,
    reference       text,
    jrnl            text,
    description     text,
    debit           numeric(20,2) NOT NULL DEFAULT 0,
    credit          numeric(20,2) NOT NULL DEFAULT 0,
    seq             integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_gl_acct ON fin_sage_gl_lines (legal_entity_id, account_code, txn_date, seq);
CREATE INDEX IF NOT EXISTS idx_fin_sage_gl_txn ON fin_sage_gl_lines (legal_entity_id, txn_date, jrnl, reference);
CREATE INDEX IF NOT EXISTS idx_fin_sage_gl_ref ON fin_sage_gl_lines (legal_entity_id, reference);

CREATE TABLE IF NOT EXISTS fin_sage_gl_balances (
    legal_entity_id   uuid NOT NULL REFERENCES fin_legal_entities(id),
    account_code      text NOT NULL,
    period_start      date NOT NULL,
    beginning_balance numeric(20,2) NOT NULL DEFAULT 0,
    period_debit      numeric(20,2),
    period_credit     numeric(20,2),
    load_id           uuid,
    PRIMARY KEY (legal_entity_id, account_code, period_start)
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_glb_period ON fin_sage_gl_balances (legal_entity_id, period_start);

CREATE TABLE IF NOT EXISTS fin_sage_party_ledger (
    id              bigserial PRIMARY KEY,
    legal_entity_id uuid NOT NULL REFERENCES fin_legal_entities(id),
    load_id         uuid,
    party_kind      text NOT NULL CHECK (party_kind IN ('CUSTOMER', 'VENDOR')),
    party_code      text NOT NULL,
    party_name      text,
    customer_id     bigint,
    supplier_id     uuid,
    txn_date        date,
    trans_no        text,
    jrnl            text,
    paid            text,
    debit           numeric(20,2) NOT NULL DEFAULT 0,
    credit          numeric(20,2) NOT NULL DEFAULT 0,
    balance         numeric(20,2),
    row_kind        text NOT NULL DEFAULT 'TXN' CHECK (row_kind IN ('BALFWD', 'TXN')),
    seq             integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_pl_party ON fin_sage_party_ledger (legal_entity_id, party_kind, party_code, txn_date, seq);
CREATE INDEX IF NOT EXISTS idx_fin_sage_pl_cust ON fin_sage_party_ledger (legal_entity_id, customer_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_fin_sage_pl_supp ON fin_sage_party_ledger (legal_entity_id, supplier_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_fin_sage_pl_trans ON fin_sage_party_ledger (legal_entity_id, trans_no);

CREATE TABLE IF NOT EXISTS fin_sage_journal_lines (
    id                  bigserial PRIMARY KEY,
    legal_entity_id     uuid NOT NULL REFERENCES fin_legal_entities(id),
    load_id             uuid,
    kind                text NOT NULL CHECK (kind IN ('SJ', 'CRJ', 'CDJ', 'PJ', 'COGS', 'GENJ')),
    txn_date            date NOT NULL,
    account_code        text,
    account_description text,
    reference           text,
    description         text,
    qty                 numeric(18,4),
    um                  text,
    debit               numeric(20,2) NOT NULL DEFAULT 0,
    credit              numeric(20,2) NOT NULL DEFAULT 0,
    seq                 integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_jl_kind ON fin_sage_journal_lines (legal_entity_id, kind, txn_date, seq);
CREATE INDEX IF NOT EXISTS idx_fin_sage_jl_ref ON fin_sage_journal_lines (legal_entity_id, kind, reference);
CREATE INDEX IF NOT EXISTS idx_fin_sage_jl_desc ON fin_sage_journal_lines (legal_entity_id, kind, description) WHERE kind = 'CRJ' OR kind = 'CDJ';

-- the last day Sage is the record (reports switch to ACE Books journals the day after)
ALTER TABLE fin_settings ADD COLUMN IF NOT EXISTS history_until date;
UPDATE fin_settings SET history_until = cutover_date - 1 WHERE history_until IS NULL AND cutover_date IS NOT NULL;

-- invoice print layout (company header, bank details, footer notes) - editable in Setup
ALTER TABLE fin_settings ADD COLUMN IF NOT EXISTS invoice_layout jsonb NOT NULL DEFAULT '{}'::jsonb;

-- open items brought forward keep their original Sage amount and what was paid before cut-over
ALTER TABLE fin_sales_invoices ADD COLUMN IF NOT EXISTS original_total numeric(20,2);
ALTER TABLE fin_sales_invoices ADD COLUMN IF NOT EXISTS ship_to text;
ALTER TABLE fin_sales_invoices ADD COLUMN IF NOT EXISTS customer_po text;
ALTER TABLE fin_sales_invoices ADD COLUMN IF NOT EXISTS shipping_method text;
ALTER TABLE fin_sales_invoices ADD COLUMN IF NOT EXISTS sales_rep text;
ALTER TABLE fin_supplier_bills ADD COLUMN IF NOT EXISTS original_total numeric(20,2);

-- returns linked to the exact sale / purchase they reverse, even when that document is Sage history
ALTER TABLE fin_credit_notes ADD COLUMN IF NOT EXISTS sage_invoice_number text;
ALTER TABLE fin_credit_notes ADD COLUMN IF NOT EXISTS recall_id uuid;
ALTER TABLE fin_debit_notes ADD COLUMN IF NOT EXISTS sage_bill_number text;
ALTER TABLE fin_recall_items ADD COLUMN IF NOT EXISTS credit_note_id uuid;
ALTER TABLE fin_recall_items ADD COLUMN IF NOT EXISTS sku text;

-- Sage stocks each lot as its own item (MENACTRA (R)); its expiry is typed in the item record
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS lot_expiry date;
ALTER TABLE fin_products ADD COLUMN IF NOT EXISTS sales_description text;

-- a batch's manufacturer details as printed on the invoice
ALTER TABLE fin_batches ADD COLUMN IF NOT EXISTS lot_code text;
UPDATE fin_batches SET lot_code = batch_number WHERE lot_code IS NULL;

-- migration kinds for the extra Sage files (kept in the same staging pipeline)
ALTER TABLE fin_migration_batches DROP CONSTRAINT IF EXISTS fin_migration_batches_kind_check;
ALTER TABLE fin_migration_batches ADD CONSTRAINT fin_migration_batches_kind_check CHECK (kind = ANY (ARRAY[
    'COA','TRIAL_BALANCE','OPEN_AR','OPEN_AP','INVENTORY','FIXED_ASSETS','SALES_JOURNAL','COGS_JOURNAL',
    'PURCHASE_JOURNAL','ITEM_COSTING','GENERAL_LEDGER','CUSTOMER_LEDGER','VENDOR_LEDGER','CASH_RECEIPTS_JOURNAL',
    'CASH_DISBURSEMENTS_JOURNAL','GENERAL_JOURNAL','ITEM_MASTER','CUSTOMER_LIST','VENDOR_LIST']));
