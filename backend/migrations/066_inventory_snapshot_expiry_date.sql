-- Migration 066: Add expiry_date column to sage_inventory_snapshot
-- The _map_stock_on_hand mapper emits expiry_date but the column was
-- missing from the original table definition, causing all stock_on_hand
-- imports to fail with a PostgreSQL column-not-found error.

ALTER TABLE public.sage_inventory_snapshot
  ADD COLUMN IF NOT EXISTS expiry_date date;
