-- 121: stock orders on ACE Books.
--
-- replenishment_requests becomes the stock-order register: requested -> approved
-- -> ordered (supplier, reference, expected date, cost) -> received (linked to
-- the ACE Books supplier bill that added the stock).
--
-- The reorder automation used to raise a request for every catalogue item under
-- 10 units in the retired Sage stock view (753 rows, qty 20 each, on dead items).
-- Those are cancelled here, not deleted; the reorder plan is now computed from
-- ACE Books stock and sales (src/services/stock_orders.py).

ALTER TABLE replenishment_requests
    ADD COLUMN IF NOT EXISTS supplier_id   uuid,
    ADD COLUMN IF NOT EXISTS unit_cost     numeric,
    ADD COLUMN IF NOT EXISTS expected_date date,
    ADD COLUMN IF NOT EXISTS approved_at   timestamptz,
    ADD COLUMN IF NOT EXISTS ordered_at    timestamptz,
    ADD COLUMN IF NOT EXISTS bill_id       uuid,
    ADD COLUMN IF NOT EXISTS received_qty  numeric;

CREATE INDEX IF NOT EXISTS idx_replenishment_requests_bill ON replenishment_requests (bill_id);

UPDATE replenishment_requests
   SET status = 'cancelled', updated_at = now(),
       notes = COALESCE(notes || '; ', '') || 'Superseded: reorder plan is computed from ACE Books stock and sales'
 WHERE status = 'recommended' AND created_by = 'auto_low_stock';
