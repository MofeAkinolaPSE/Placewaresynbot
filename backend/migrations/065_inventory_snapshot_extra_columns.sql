-- Migration 065: Add extended columns to sage_inventory_snapshot
-- The stock_on_hand CSV mapper emits warehouse_id, reorder_level,
-- reorder_quantity, batch_number, and storage_condition which were
-- missing from the original table definition.

ALTER TABLE public.sage_inventory_snapshot
  ADD COLUMN IF NOT EXISTS warehouse_id      text,
  ADD COLUMN IF NOT EXISTS reorder_level     numeric,
  ADD COLUMN IF NOT EXISTS reorder_quantity  numeric,
  ADD COLUMN IF NOT EXISTS batch_number      text,
  ADD COLUMN IF NOT EXISTS storage_condition text;

-- Support fast warehouse-level queries
CREATE INDEX IF NOT EXISTS sage_inventory_snapshot_warehouse_id_idx
  ON public.sage_inventory_snapshot (warehouse_id);
