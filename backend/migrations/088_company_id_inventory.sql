-- Migration 088: Add company_id to inventory snapshot tables
-- Enables multi-company filtering (PlacewareNig vs PlacewarePha) in the inventory UI.
-- Existing rows are tagged PlacewareNig (the 57 items from planigli extraction).

ALTER TABLE sage_items_snapshot
    ADD COLUMN IF NOT EXISTS company_id text;

ALTER TABLE sage_inventory_snapshot
    ADD COLUMN IF NOT EXISTS company_id text;

CREATE INDEX IF NOT EXISTS idx_sage_items_company
    ON sage_items_snapshot (company_id);

CREATE INDEX IF NOT EXISTS idx_sage_inventory_company
    ON sage_inventory_snapshot (company_id);

-- Tag all existing items as PlacewareNig (extracted from planigli/LINEITEM.DAT)
UPDATE sage_items_snapshot SET company_id = 'PlacewareNig' WHERE company_id IS NULL;
UPDATE sage_inventory_snapshot SET company_id = 'PlacewareNig' WHERE company_id IS NULL;

-- Re-create v_inventory to include company_id (supersedes migration 086 version)
CREATE OR REPLACE VIEW v_inventory AS
WITH latest_items AS (
    SELECT DISTINCT ON (item_id, COALESCE(company_id, 'default'))
        item_id AS sku,
        item_name AS name,
        category,
        unit,
        cost_price,
        selling_price,
        vat_category,
        reorder_level,
        is_active,
        expiry_date,
        batch_number,
        company_id
    FROM sage_items_snapshot
    ORDER BY item_id, COALESCE(company_id, 'default'), imported_at DESC
),
latest_inv_batch AS (
    SELECT batch_id FROM sage_inventory_snapshot
    ORDER BY imported_at DESC LIMIT 1
),
stock_agg AS (
    SELECT
        s.sku,
        SUM(s.quantity) AS current_stock,
        TRUE AS has_sage_qty
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
    li.company_id,
    COALESCE(sa.current_stock, 0.0) AS current_stock,
    COALESCE(sa.has_sage_qty, FALSE) AS has_sage_qty
FROM latest_items li
LEFT JOIN stock_agg sa ON sa.sku = li.sku;
