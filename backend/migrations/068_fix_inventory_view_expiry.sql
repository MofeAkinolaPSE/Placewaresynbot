-- Migration 068: Fix placeware_inventory_snapshot view to use real expiry_date
-- Migration 043 hardcoded NULL::DATE AS expiry_date; now the column exists
-- (added by migration 066), so the view should reference it directly.

CREATE OR REPLACE VIEW placeware_inventory_snapshot AS
SELECT
  s.id,
  s.batch_id,
  s.sku,
  s.name AS product_name,
  COALESCE(sl_agg.total_qty, s.quantity) AS current_qty,
  s.unit_cost,
  s.valuation,
  s.updated_at,
  s.imported_at,
  10 AS safety_stock,
  -- Real expiry_date from the snapshot (previously hardcoded NULL)
  s.expiry_date,
  'approved'::TEXT AS nafdac_status
FROM sage_inventory_snapshot s
LEFT JOIN LATERAL (
  SELECT SUM(sl.quantity) AS total_qty
  FROM stock_levels sl
  JOIN inventory_items ii ON sl.item_id = ii.id
  WHERE ii.sku = s.sku
) sl_agg ON TRUE;
