-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 086: Silver Layer Views + Performance Indexes + Dead Table Archive
-- Medallion Architecture: Bronze (raw snapshots) → Silver (clean joined views)
-- Replaces Python-level dedup/join loops in inventory.py, finance.py,
-- suppliers.py with single DB-level view queries.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Performance indexes on Bronze snapshot tables ────────────────────────────

CREATE INDEX IF NOT EXISTS idx_sage_items_item_id_ts
    ON sage_items_snapshot (item_id, imported_at DESC);

CREATE INDEX IF NOT EXISTS idx_sage_inv_sku_batch_ts
    ON sage_inventory_snapshot (sku, batch_id, imported_at DESC);

CREATE INDEX IF NOT EXISTS idx_sage_coa_code_ts
    ON sage_coa_snapshot (account_code, imported_at DESC);

CREATE INDEX IF NOT EXISTS idx_sage_cust_cid_ts
    ON sage_customers_snapshot (customer_id, imported_at DESC);

CREATE INDEX IF NOT EXISTS idx_sage_vend_vid_ts
    ON sage_vendors_snapshot (vendor_id, imported_at DESC);

-- ── v_inventory ───────────────────────────────────────────────────────────────
-- Silver view: deduplicates sage_items_snapshot (catalog) and joins with
-- sage_inventory_snapshot (stock qty, summed across warehouses for latest batch).
-- Returns one row per SKU with full catalog fields + current_stock + has_sage_qty.
CREATE OR REPLACE VIEW v_inventory AS
WITH latest_items AS (
    SELECT DISTINCT ON (item_id)
        item_id        AS sku,
        item_name      AS name,
        category,
        unit,
        cost_price,
        selling_price,
        vat_category,
        reorder_level,
        is_active,
        expiry_date,
        batch_number
    FROM sage_items_snapshot
    ORDER BY item_id, imported_at DESC
),
latest_inv_batch AS (
    -- Identify the most recent import batch to avoid double-counting re-imports
    SELECT batch_id
    FROM sage_inventory_snapshot
    ORDER BY imported_at DESC
    LIMIT 1
),
stock_agg AS (
    -- Sum warehouse-level rows into one total per SKU for the latest batch
    SELECT
        s.sku,
        SUM(s.quantity)          AS current_stock,
        true                     AS has_sage_qty
    FROM sage_inventory_snapshot s
    JOIN latest_inv_batch lb ON s.batch_id = lb.batch_id
    GROUP BY s.sku
)
SELECT
    li.sku,
    li.name,
    li.category,
    li.unit,
    li.cost_price,
    li.selling_price,
    li.vat_category,
    li.reorder_level,
    li.is_active,
    li.expiry_date,
    li.batch_number,
    COALESCE(sa.current_stock, 0.0)  AS current_stock,
    COALESCE(sa.has_sage_qty, false) AS has_sage_qty
FROM latest_items li
LEFT JOIN stock_agg sa ON sa.sku = li.sku;

-- ── v_chart_of_accounts ───────────────────────────────────────────────────────
-- Silver view: deduplicated COA (latest import per account_code).
CREATE OR REPLACE VIEW v_chart_of_accounts AS
SELECT DISTINCT ON (account_code)
    id,
    account_code,
    account_name,
    account_type,
    parent_account_id,
    description,
    is_active
FROM sage_coa_snapshot
ORDER BY account_code, imported_at DESC;

-- ── v_customers ───────────────────────────────────────────────────────────────
-- Silver view: deduplicated Sage customer master (latest import per customer_id).
CREATE OR REPLACE VIEW v_customers AS
SELECT DISTINCT ON (customer_id)
    id,
    customer_id,
    name,
    email,
    phone,
    status
FROM sage_customers_snapshot
ORDER BY customer_id, imported_at DESC;

-- ── v_vendors ─────────────────────────────────────────────────────────────────
-- Silver view: deduplicated Sage vendor master (latest import per vendor_id).
CREATE OR REPLACE VIEW v_vendors AS
SELECT DISTINCT ON (vendor_id)
    id,
    vendor_id,
    vendor_name,
    contact_name,
    email,
    phone,
    address,
    city,
    payment_terms
FROM sage_vendors_snapshot
ORDER BY vendor_id, imported_at DESC;

-- ── DB Cleanup: archive dead tables ───────────────────────────────────────────
-- Tables confirmed unused (created in migrations, zero Python router references).
-- Moved to _archive schema — reversible with: ALTER TABLE _archive.X SET SCHEMA public;
CREATE SCHEMA IF NOT EXISTS _archive;

ALTER TABLE IF EXISTS invoice               SET SCHEMA _archive;
ALTER TABLE IF EXISTS invoice_items         SET SCHEMA _archive;
ALTER TABLE IF EXISTS journal_entries       SET SCHEMA _archive;
ALTER TABLE IF EXISTS budget_heads          SET SCHEMA _archive;
ALTER TABLE IF EXISTS payment_terms         SET SCHEMA _archive;
ALTER TABLE IF EXISTS material_requisition  SET SCHEMA _archive;
ALTER TABLE IF EXISTS stock_allocation      SET SCHEMA _archive;
ALTER TABLE IF EXISTS warehouse_transfers   SET SCHEMA _archive;
ALTER TABLE IF EXISTS purchase_orders       SET SCHEMA _archive;
ALTER TABLE IF EXISTS vendor_invoices       SET SCHEMA _archive;
ALTER TABLE IF EXISTS prospect_search_cache SET SCHEMA _archive;
