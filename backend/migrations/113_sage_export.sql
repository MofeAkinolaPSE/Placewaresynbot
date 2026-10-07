-- =============================================================================
-- Migration 113 — ACE → Sage 50 export bridge
-- =============================================================================
-- Sage 50 2013 has no usable write API, so ACE hands the accountant a ZIP of
-- CSVs laid out exactly like Sage's own Import/Export templates (Sales Journal,
-- Cash Receipts Journal, Inventory Adjustments Journal, Customer List). Sage
-- then posts GL / P&L / balance sheet / stock itself. See
-- backend/docs/Latestmods-TB/sage-link/ for the templates and meeting notes.
--
-- 1. sage_item_accounts  — per-item Sales/Inventory/COGS GL accounts, loaded
--    from Sage's ITEM.CSV via the Sage Import page (file_type=item_accounts).
--    Snapshot-style (batch_id/imported_at) because insert_snapshot() is how
--    the import page writes; readers take the latest row per item_id.
-- 2. sage_export_settings — single-row config (cut-over date, GL mapping).
-- 3. sage_export_batches / sage_export_items — every exported source record is
--    recorded once; the UNIQUE(doc_type, source_id) is the exported-once guard.
-- =============================================================================

CREATE TABLE IF NOT EXISTS sage_item_accounts (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        TEXT,
    imported_at     TIMESTAMPTZ DEFAULT now(),
    item_id         TEXT NOT NULL,
    item_description TEXT,
    item_class      TEXT,
    inactive        BOOLEAN DEFAULT FALSE,
    sales_account   TEXT,
    inventory_account TEXT,
    cogs_account    TEXT,
    costing_method  TEXT,
    last_unit_cost  NUMERIC(18,4),
    sales_price_1   NUMERIC(18,4),
    stocking_um     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sage_item_accounts_item
    ON sage_item_accounts (item_id, imported_at DESC);

CREATE OR REPLACE VIEW v_sage_item_accounts AS
SELECT DISTINCT ON (item_id)
    item_id, item_description, item_class, inactive,
    sales_account, inventory_account, cogs_account,
    costing_method, last_unit_cost, sales_price_1, stocking_um, imported_at
FROM sage_item_accounts
ORDER BY item_id, imported_at DESC;

CREATE TABLE IF NOT EXISTS sage_export_settings (
    id                   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    cutover_date         DATE,
    ar_account           TEXT NOT NULL DEFAULT '11000',
    delivery_gl_account  TEXT NOT NULL DEFAULT '40800',
    discount_gl_account  TEXT NOT NULL DEFAULT '49000',
    writeoff_gl_account  TEXT,
    -- Sage "Transaction Period" for a known month; other months are offsets.
    -- From the client's June 2026 export: period 34.
    period_anchor_month  DATE NOT NULL DEFAULT DATE '2026-06-01',
    period_anchor_number INT  NOT NULL DEFAULT 34,
    -- ACE ar_receipts.payment_method -> Sage Payment Method / Cash Account / Reference
    payment_method_map   JSONB NOT NULL DEFAULT '{
        "cash":              {"method": "Cash",  "cash_account": "10100", "reference": "CASH"},
        "cheque":            {"method": "Check", "cash_account": "10290", "reference": "CHEQUE"},
        "bank_transfer":     {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"},
        "pos":               {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"},
        "card":              {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"},
        "mobile_payment":    {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"},
        "corporate_account": {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"},
        "split_payment":     {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"}
    }'::jsonb,
    updated_by           TEXT,
    updated_at           TIMESTAMPTZ DEFAULT now()
);
INSERT INTO sage_export_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS sage_export_batches (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period_from  DATE NOT NULL,
    period_to    DATE NOT NULL,
    counts       JSONB NOT NULL DEFAULT '{}'::jsonb,
    blocked      JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- The generated CSVs, kept so a batch can be re-downloaded byte-identical
    -- (re-building later would change nothing for exported rows anyway, since
    -- they are excluded, so storing is the only way to re-download).
    files        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sage_export_batches_created
    ON sage_export_batches (created_at DESC);

CREATE TABLE IF NOT EXISTS sage_export_items (
    id           BIGSERIAL PRIMARY KEY,
    batch_id     UUID NOT NULL REFERENCES sage_export_batches(id) ON DELETE CASCADE,
    doc_type     TEXT NOT NULL CHECK (doc_type IN ('customer', 'sales', 'receipts', 'adjust')),
    source_table TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    sage_ref     TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_sage_export_items_batch ON sage_export_items (batch_id);
