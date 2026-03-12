-- Migration: Create placeware_inventory_snapshot view
-- Unifies sage_inventory_snapshot + stock_levels + inventory_items
-- so agents and workflows have a single source of truth.

-- Promotions table (for expiry-promotion workflow)
CREATE TABLE IF NOT EXISTS promotions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku TEXT NOT NULL,
  batch_id TEXT,
  product_name TEXT,
  discount_pct NUMERIC DEFAULT 0,
  reason TEXT,
  quantity NUMERIC DEFAULT 0,
  status TEXT DEFAULT 'active',  -- active, expired, cancelled
  created_by TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_promotions_sku ON promotions(sku);
CREATE INDEX IF NOT EXISTS idx_promotions_status ON promotions(status);

-- Unified inventory snapshot view
-- Combines sage import data with live stock levels
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
  -- Safety stock defaults to 10 if unknown
  10 AS safety_stock,
  -- Expiry date placeholder (no native expiry in current schema)
  NULL::DATE AS expiry_date,
  -- NAFDAC status placeholder
  'approved'::TEXT AS nafdac_status
FROM sage_inventory_snapshot s
LEFT JOIN LATERAL (
  SELECT SUM(sl.quantity) AS total_qty
  FROM stock_levels sl
  JOIN inventory_items ii ON sl.item_id = ii.id
  WHERE ii.sku = s.sku
) sl_agg ON TRUE;

-- AR view with customer name joined in
CREATE OR REPLACE VIEW placeware_ar_ledger AS
SELECT
  ar.id,
  ar.batch_id,
  ar.customer_id,
  COALESCE(c.name, ar.customer_id) AS customer_name,
  ar.invoice_id,
  ar.date AS invoice_date,
  ar.due_date,
  ar.amount,
  ar.balance,
  ar.status,
  ar.imported_at,
  c.risk_score AS customer_risk_score
FROM sage_ar_snapshot ar
LEFT JOIN customers c ON c.customer_code = ar.customer_id
                      OR c.id::TEXT = ar.customer_id;
