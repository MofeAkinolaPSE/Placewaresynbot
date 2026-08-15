-- Migration 106: Fold placeware_inventory_events deltas into v_inventory
--
-- v_inventory (086/088) has always been built purely from Sage snapshot
-- tables (sage_items_snapshot + sage_inventory_snapshot's latest batch). It
-- never read placeware_inventory_events at all, so every manual "Add Stock" /
-- "Log Adjustment" action (POST /inventory/event) was permanently invisible
-- to GET /inventory/items and the dashboard KPI counts -- not just until the
-- next Sage import, forever. Meanwhile services/inventory.py's
-- get_realtime_stock()/get_inventory_summary() *did* fold events in,
-- producing a second, disagreeing "current stock" number for the same SKU.
--
-- This rebuild makes v_inventory the single canonical stock read, computing
-- current_stock = latest Sage snapshot baseline + sum of inventory events
-- recorded since that SKU's own baseline import -- the exact semantics
-- get_realtime_stock() already used, now available to every consumer.

CREATE INDEX IF NOT EXISTS idx_inventory_events_sku_created_at
    ON placeware_inventory_events (sku, created_at);

DROP VIEW IF EXISTS v_ar_invoice_lines;
DROP VIEW IF EXISTS v_inventory;
CREATE VIEW v_inventory AS
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
        SUM(s.quantity) AS baseline_qty,
        MAX(s.imported_at) AS baseline_ts,
        TRUE AS has_sage_qty
    FROM sage_inventory_snapshot s
    JOIN latest_inv_batch lb ON s.batch_id = lb.batch_id
    GROUP BY s.sku
),
event_deltas AS (
    -- Mirrors get_realtime_stock()'s exact semantics: sum events recorded
    -- since this SKU's own snapshot baseline. SKUs with no Sage baseline at
    -- all (COALESCE to -infinity) sum every event ever recorded for them.
    SELECT
        e.sku,
        SUM(e.quantity_change) AS delta_qty,
        COUNT(*) AS event_count
    FROM placeware_inventory_events e
    LEFT JOIN stock_agg sa ON sa.sku = e.sku
    WHERE e.created_at > COALESCE(sa.baseline_ts, '-infinity'::timestamptz)
    GROUP BY e.sku
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
    COALESCE(sa.baseline_qty, 0.0) + COALESCE(ed.delta_qty, 0.0) AS current_stock,
    COALESCE(sa.has_sage_qty, FALSE) AS has_sage_qty,
    COALESCE(ed.event_count, 0) AS events_since_baseline
FROM latest_items li
LEFT JOIN stock_agg sa ON sa.sku = li.sku
LEFT JOIN event_deltas ed ON ed.sku = li.sku;

-- Recreate v_ar_invoice_lines now that v_inventory exists again (same
-- dependency chain migration 088 established).
CREATE OR REPLACE VIEW v_ar_invoice_lines AS
WITH latest_batch AS (
    SELECT batch_id
    FROM sage_invoice_lines_snapshot
    ORDER BY imported_at DESC
    LIMIT 1
)
SELECT
    l.invoice_id,
    l.line_id,
    l.item_id,
    i.name          AS item_name,
    l.quantity,
    l.unit_price,
    l.discount,
    l.line_total,
    l.gross_profit
FROM sage_invoice_lines_snapshot l
JOIN latest_batch lb ON l.batch_id = lb.batch_id
LEFT JOIN v_inventory i ON i.sku = l.item_id;
