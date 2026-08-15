-- Migration 104: Fix placeware_inventory_snapshot view — missing catalog join
--
-- Since migration 043 (superseded by 068), this view read exclusively from
-- sage_inventory_snapshot, which per db_audit.py / sage_adapter/service.py
-- comments is essentially empty (real stock numbers live in
-- sage_inventory_snapshot only for a couple of rows; the real 50-SKU pharma
-- catalog with real cost_price/expiry_date/batch_number lives in
-- sage_items_snapshot). It never joined sage_items_snapshot at all, so every
-- consumer of this view (AI Report Generator's inventory report, low-stock
-- and expiry automations in workflow/automation.py) saw ~0 real rows and, in
-- the report generator's case, hallucinated a catalog-wide "100% stockout".
--
-- Rebuilt using the same latest-batch-scoped join pattern already used
-- correctly by v_inventory (086/088): dedupe sage_items_snapshot per SKU,
-- LEFT JOIN sage_inventory_snapshot scoped to only its most recent import
-- batch (avoids double-counting the known duplicate same-day re-import
-- batches), compute valuation from qty * cost.

-- DROP + CREATE (not CREATE OR REPLACE): the previous view's safety_stock was a
-- hardcoded integer literal (10 AS safety_stock); this version derives it from
-- reorder_level (numeric), and updated_at's source type also changes — Postgres
-- disallows CREATE OR REPLACE VIEW from changing an existing column's type.
DROP VIEW IF EXISTS placeware_inventory_snapshot;
CREATE VIEW placeware_inventory_snapshot AS
WITH latest_items AS (
  SELECT DISTINCT ON (item_id)
    id,
    batch_id,
    item_id       AS sku,
    item_name     AS product_name,
    cost_price    AS unit_cost,
    expiry_date,
    batch_number,
    reorder_level,
    imported_at
  FROM sage_items_snapshot
  ORDER BY item_id, imported_at DESC
),
latest_inv_batch AS (
  SELECT batch_id
  FROM sage_inventory_snapshot
  ORDER BY imported_at DESC
  LIMIT 1
),
stock_agg AS (
  SELECT
    s.sku,
    s.batch_id,
    SUM(s.quantity) AS current_qty
  FROM sage_inventory_snapshot s
  JOIN latest_inv_batch lb ON s.batch_id = lb.batch_id
  GROUP BY s.sku, s.batch_id
)
SELECT
  li.id,
  COALESCE(sa.batch_id, li.batch_id) AS batch_id,
  li.sku,
  li.product_name,
  COALESCE(sa.current_qty, 0.0) AS current_qty,
  li.unit_cost,
  COALESCE(sa.current_qty, 0.0) * COALESCE(li.unit_cost, 0.0) AS valuation,
  li.imported_at AS updated_at,
  li.imported_at,
  COALESCE(li.reorder_level, 10) AS safety_stock,
  li.expiry_date,
  'approved'::TEXT AS nafdac_status
FROM latest_items li
LEFT JOIN stock_agg sa ON sa.sku = li.sku;
