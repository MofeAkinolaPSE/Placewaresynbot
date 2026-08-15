-- Migration 108: Index for the Inventory Workspace's "open requests for
-- this family's members" lookup (replenishment_requests WHERE sku = ANY(...)
-- AND status != 'received').

CREATE INDEX IF NOT EXISTS idx_replenishment_requests_sku_status
    ON replenishment_requests (sku, status);
