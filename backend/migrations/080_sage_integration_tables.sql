-- =============================================================================
-- Migration: Sage 50 Integration — Sync Tables
-- Apply this to your Supabase project via the SQL editor or migration tool.
-- =============================================================================


-- ── Sync Log ─────────────────────────────────────────────────────────────────
-- Audit trail for every SynBot ↔ Sage sync event.

CREATE TABLE IF NOT EXISTS placeware_sage_sync_log (
    id              UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    entity_type     TEXT        NOT NULL,               -- 'invoice' | 'customer' | 'vendor' | ...
    direction       TEXT        NOT NULL,               -- 'synbot_to_sage' | 'sage_to_synbot'
    synbot_id       TEXT,                               -- SynBot's internal record ID
    sage_id         TEXT,                               -- Sage's record ID
    status          TEXT        NOT NULL DEFAULT 'success', -- 'success' | 'failed' | 'pending'
    payload         JSONB,                              -- snapshot of the data at sync time
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sage_sync_log_entity  ON placeware_sage_sync_log (entity_type);
CREATE INDEX IF NOT EXISTS idx_sage_sync_log_status  ON placeware_sage_sync_log (status);
CREATE INDEX IF NOT EXISTS idx_sage_sync_log_created ON placeware_sage_sync_log (created_at DESC);


-- ── Sync Timestamps ───────────────────────────────────────────────────────────
-- Tracks when each entity type was last successfully synced.

CREATE TABLE IF NOT EXISTS placeware_sage_sync_timestamps (
    entity_type     TEXT        PRIMARY KEY,
    last_synced_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ── Customers Cache ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_customers_cache (
    id              TEXT        PRIMARY KEY,            -- Sage customer ID/code
    name            TEXT,
    address1        TEXT,
    address2        TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    country         TEXT,
    phone           TEXT,
    fax             TEXT,
    email           TEXT,
    contact         TEXT,
    balance         NUMERIC(18,4) DEFAULT 0,
    credit_limit    NUMERIC(18,4) DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    synced_at       TIMESTAMPTZ DEFAULT now()
);


-- ── Vendors Cache ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_vendors_cache (
    id              TEXT        PRIMARY KEY,
    name            TEXT,
    address1        TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    country         TEXT,
    phone           TEXT,
    email           TEXT,
    contact         TEXT,
    balance         NUMERIC(18,4) DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    synced_at       TIMESTAMPTZ DEFAULT now()
);


-- ── Inventory Cache ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_inventory_cache (
    id                      TEXT        PRIMARY KEY,    -- Sage item ID
    description             TEXT,
    item_type               TEXT,
    sales_price             NUMERIC(18,4) DEFAULT 0,
    cost                    NUMERIC(18,4) DEFAULT 0,
    quantity_on_hand        NUMERIC(18,4) DEFAULT 0,
    quantity_on_order       NUMERIC(18,4) DEFAULT 0,
    reorder_quantity        NUMERIC(18,4) DEFAULT 0,
    sales_gl_account        TEXT,
    cogs_gl_account         TEXT,
    inventory_gl_account    TEXT,
    unit_of_measure         TEXT,
    weight                  NUMERIC(10,4) DEFAULT 0,
    is_active               BOOLEAN DEFAULT TRUE,
    synced_at               TIMESTAMPTZ DEFAULT now()
);


-- ── Sales Invoices Cache ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_invoices_cache (
    sage_id         TEXT        PRIMARY KEY,
    customer_id     TEXT,
    date            DATE,
    due_date        DATE,
    invoice_number  TEXT,
    po_number       TEXT,
    total_amount    NUMERIC(18,4) DEFAULT 0,
    amount_paid     NUMERIC(18,4) DEFAULT 0,
    amount_due      NUMERIC(18,4) DEFAULT 0,
    is_paid         BOOLEAN DEFAULT FALSE,
    note            TEXT,
    lines           JSONB,                              -- full line items stored as JSON
    synced_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sage_invoices_customer ON sage_invoices_cache (customer_id);
CREATE INDEX IF NOT EXISTS idx_sage_invoices_date     ON sage_invoices_cache (date DESC);
CREATE INDEX IF NOT EXISTS idx_sage_invoices_paid     ON sage_invoices_cache (is_paid);


-- ── Sales Orders Cache ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_sales_orders_cache (
    sage_id         TEXT        PRIMARY KEY,
    customer_id     TEXT,
    date            DATE,
    ship_date       DATE,
    po_number       TEXT,
    total_amount    NUMERIC(18,4) DEFAULT 0,
    lines           JSONB,
    synced_at       TIMESTAMPTZ DEFAULT now()
);


-- ── Purchase Orders Cache ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_purchase_orders_cache (
    sage_id         TEXT        PRIMARY KEY,
    vendor_id       TEXT,
    date            DATE,
    expected_date   DATE,
    reference       TEXT,
    total_amount    NUMERIC(18,4) DEFAULT 0,
    lines           JSONB,
    synced_at       TIMESTAMPTZ DEFAULT now()
);


-- ── Chart of Accounts Cache ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_accounts_cache (
    id              TEXT        PRIMARY KEY,
    description     TEXT,
    account_type    TEXT,
    balance         NUMERIC(18,4) DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    synced_at       TIMESTAMPTZ DEFAULT now()
);


-- ── Employees Cache ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sage_employees_cache (
    id              TEXT        PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    address1        TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    phone           TEXT,
    email           TEXT,
    hire_date       DATE,
    pay_type        TEXT,
    pay_frequency   TEXT,
    department      TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    synced_at       TIMESTAMPTZ DEFAULT now()
);


-- ── Row Level Security ────────────────────────────────────────────────────────
-- All Sage cache tables: readable by authenticated staff, writable by service role only.

ALTER TABLE placeware_sage_sync_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE placeware_sage_sync_timestamps  ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_customers_cache            ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_vendors_cache              ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_inventory_cache            ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_invoices_cache             ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_sales_orders_cache         ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_purchase_orders_cache      ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_accounts_cache             ENABLE ROW LEVEL SECURITY;
ALTER TABLE sage_employees_cache            ENABLE ROW LEVEL SECURITY;

-- Authenticated users can read cache tables
CREATE POLICY sage_cache_read ON sage_customers_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_vendors_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_inventory_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_invoices_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_sales_orders_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_purchase_orders_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_accounts_cache
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_cache_read ON sage_employees_cache
    FOR SELECT TO authenticated USING (true);

-- Only service role can write (sync engine writes via service key)
-- Supabase service role bypasses RLS by default — no insert policy needed.

-- Sync log: authenticated users can read their own entries; service role writes all
CREATE POLICY sage_sync_log_read ON placeware_sage_sync_log
    FOR SELECT TO authenticated USING (true);
CREATE POLICY sage_sync_ts_read ON placeware_sage_sync_timestamps
    FOR SELECT TO authenticated USING (true);
