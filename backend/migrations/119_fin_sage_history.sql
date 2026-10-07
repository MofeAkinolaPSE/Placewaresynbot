-- =============================================================================
-- Migration 119 — ACE Books: Sage transaction history (display + lineage only)
-- =============================================================================
-- The cut-over loads Sage as balances (opening journal, open items, stock on
-- hand). These tables add Sage's line-level history behind those balances so a
-- user can still see WHAT was sold / bought, in what quantity, to or from whom,
-- and how each item moved - from the Sage Sales Journal, COGS Journal,
-- Purchase Journal and Item Costing report. They never post to the ledger and
-- no balance is derived from them.
-- =============================================================================

CREATE TABLE IF NOT EXISTS fin_sage_sales_lines (
    id              BIGSERIAL PRIMARY KEY,
    legal_entity_id UUID NOT NULL REFERENCES fin_legal_entities(id),
    batch_id        UUID,
    invoice_number  TEXT NOT NULL,
    invoice_date    DATE NOT NULL,
    customer_id     BIGINT,
    customer_name   TEXT,
    line_no         INT NOT NULL,
    description     TEXT,
    account_code    TEXT,
    sku             TEXT,
    quantity        NUMERIC(18,4),
    amount          NUMERIC(20,2) NOT NULL,      -- revenue (negative on credit memos)
    cost            NUMERIC(20,2)                -- cost of sales from the COGS journal
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_sales_inv ON fin_sage_sales_lines (legal_entity_id, invoice_number);
CREATE INDEX IF NOT EXISTS idx_fin_sage_sales_sku ON fin_sage_sales_lines (legal_entity_id, sku, invoice_date);
CREATE INDEX IF NOT EXISTS idx_fin_sage_sales_cust ON fin_sage_sales_lines (legal_entity_id, customer_id, invoice_date);
CREATE INDEX IF NOT EXISTS idx_fin_sage_sales_date ON fin_sage_sales_lines (legal_entity_id, invoice_date);

CREATE TABLE IF NOT EXISTS fin_sage_purchase_lines (
    id              BIGSERIAL PRIMARY KEY,
    legal_entity_id UUID NOT NULL REFERENCES fin_legal_entities(id),
    batch_id        UUID,
    bill_number     TEXT NOT NULL,               -- the supplier's invoice number, as keyed in Sage
    bill_date       DATE NOT NULL,
    supplier_id     UUID,
    supplier_name   TEXT,
    line_no         INT NOT NULL,
    description     TEXT,
    account_code    TEXT,
    sku             TEXT,
    quantity        NUMERIC(18,4),
    amount          NUMERIC(20,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_purch_bill ON fin_sage_purchase_lines (legal_entity_id, bill_number);
CREATE INDEX IF NOT EXISTS idx_fin_sage_purch_sku ON fin_sage_purchase_lines (legal_entity_id, sku, bill_date);
CREATE INDEX IF NOT EXISTS idx_fin_sage_purch_date ON fin_sage_purchase_lines (legal_entity_id, bill_date);

-- Sage "Item Costing Report": every receipt, sale and adjustment per item at cost.
CREATE TABLE IF NOT EXISTS fin_sage_item_costing (
    id              BIGSERIAL PRIMARY KEY,
    legal_entity_id UUID NOT NULL REFERENCES fin_legal_entities(id),
    batch_id        UUID,
    sku             TEXT NOT NULL,
    description     TEXT,
    txn_date        DATE NOT NULL,
    qty_received    NUMERIC(18,4),
    received_cost   NUMERIC(20,2),
    qty_adjusted    NUMERIC(18,4),
    adjusted_cost   NUMERIC(20,2),
    qty_sold        NUMERIC(18,4),
    cost_of_sales   NUMERIC(20,2),
    remaining_qty   NUMERIC(18,4),
    remaining_value NUMERIC(20,2)
);
CREATE INDEX IF NOT EXISTS idx_fin_sage_ic_sku ON fin_sage_item_costing (legal_entity_id, sku, txn_date);

-- History files go through the same stage -> review -> load pipeline.
ALTER TABLE fin_migration_batches DROP CONSTRAINT IF EXISTS fin_migration_batches_kind_check;
ALTER TABLE fin_migration_batches ADD CONSTRAINT fin_migration_batches_kind_check CHECK (kind IN (
    'COA','TRIAL_BALANCE','OPEN_AR','OPEN_AP','INVENTORY','FIXED_ASSETS',
    'SALES_JOURNAL','COGS_JOURNAL','PURCHASE_JOURNAL','ITEM_COSTING'));

-- Opening stock is loaded from Sage's valuation before batches are known; the
-- batch (Sage item = one lettered lot, with its expiry) may be attached to an
-- OPENING_BALANCE movement once, without changing quantity or cost.
CREATE OR REPLACE FUNCTION fin_inventory_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.journal_id IS DISTINCT FROM OLD.journal_id AND OLD.journal_id IS NULL
       AND NEW.quantity = OLD.quantity AND NEW.total_cost = OLD.total_cost THEN
        RETURN NEW;  -- linking the journal created in the same posting is allowed
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.txn_type = 'OPENING_BALANCE' AND OLD.batch_id IS NULL AND NEW.batch_id IS NOT NULL
       AND NEW.quantity = OLD.quantity AND NEW.total_cost = OLD.total_cost AND NEW.sku = OLD.sku
       AND NEW.txn_date = OLD.txn_date AND NEW.journal_id IS NOT DISTINCT FROM OLD.journal_id THEN
        RETURN NEW;  -- attaching the Sage lot to migrated opening stock
    END IF;
    RAISE EXCEPTION 'FIN_POSTED_IMMUTABLE: inventory movements cannot be changed; post a correcting movement';
END $$ LANGUAGE plpgsql;
