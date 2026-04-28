-- Migration 081: Extend calendar event types for pharma logistics
-- Adds logistics-specific event types to placeware_calendar_events

-- 1. Drop the old CHECK constraint (named by PostgreSQL convention)
ALTER TABLE placeware_calendar_events
  DROP CONSTRAINT IF EXISTS placeware_calendar_events_event_type_check;

-- 2. Add updated constraint that includes logistics event types
ALTER TABLE placeware_calendar_events
  ADD CONSTRAINT placeware_calendar_events_event_type_check
  CHECK (event_type IN (
    'meeting', 'deadline', 'reminder', 'holiday', 'other',
    'inbound_inventory', 'regional_dispatch', 'warehouse_audit', 'qc_inspection'
  ));

-- 3. Composite index for logistics-type calendar queries (fast monthly range scans)
CREATE INDEX IF NOT EXISTS idx_calendar_events_logistics_type
  ON placeware_calendar_events(event_type, start_time)
  WHERE event_type IN ('inbound_inventory', 'regional_dispatch', 'warehouse_audit', 'qc_inspection');

-- 4. GIN index on metadata so cold-chain / NAFDAC filter queries can use indexes
CREATE INDEX IF NOT EXISTS idx_calendar_events_metadata_gin
  ON placeware_calendar_events USING GIN (metadata);

-- 5. Expose a helper view for quick logistics event reporting
CREATE OR REPLACE VIEW v_logistics_calendar AS
SELECT
  id,
  title,
  event_type,
  start_time,
  end_time,
  all_day,
  location,
  metadata,
  (metadata ->> 'batch_id')         AS batch_id,
  (metadata ->> 'product_name')     AS product_name,
  (metadata ->> 'quantity')::NUMERIC AS quantity,
  (metadata ->> 'supplier')         AS supplier,
  (metadata ->> 'dispatch_zone')    AS dispatch_zone,
  (metadata ->> 'status')           AS logistics_status,
  (metadata ->> 'batch_expiry')     AS batch_expiry,
  (metadata ->> 'is_cold_chain')::BOOLEAN    AS is_cold_chain,
  (metadata ->> 'is_nafdac_regulated')::BOOLEAN AS is_nafdac_regulated,
  created_at,
  updated_at
FROM placeware_calendar_events
WHERE event_type IN (
  'inbound_inventory', 'regional_dispatch', 'warehouse_audit', 'qc_inspection'
);
