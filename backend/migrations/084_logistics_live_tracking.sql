-- =============================================================================
-- Migration 084 — Logistics Live Tracking
-- =============================================================================
-- Adds the real-time GPS layer to the existing logistics schema (migration 036).
--
-- New objects:
--   1. location_pings       — Append-only GPS event log from rider PWA
--   2. deliveries columns   — tracking_token, pickup_address, dest_lat/lng,
--                             picked_up_at, delivered_at, last_ping_at
--   3. riders columns       — last_lat, last_lng, last_seen_at
--   4. v_rider_live_positions — latest position per active rider (fast view)
--   5. v_active_deliveries    — in-transit deliveries with rider snapshot
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. location_pings  (append-only GPS stream)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS location_pings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rider_id        UUID        NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    delivery_id     UUID        REFERENCES deliveries(id) ON DELETE SET NULL,
    lat             NUMERIC(10, 7)  NOT NULL,
    lng             NUMERIC(10, 7)  NOT NULL,
    speed_kmh       NUMERIC(6, 2),          -- NULL when device can't report speed
    accuracy_m      NUMERIC(7, 2),          -- horizontal accuracy metres
    battery_pct     SMALLINT,               -- 0-100, NULL if not reported
    ts              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Fast "latest N pings for a rider" queries
CREATE INDEX IF NOT EXISTS idx_location_pings_rider_ts
    ON location_pings (rider_id, ts DESC);

-- Fast "all pings for a delivery"
CREATE INDEX IF NOT EXISTS idx_location_pings_delivery
    ON location_pings (delivery_id, ts DESC)
    WHERE delivery_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. Extend deliveries  (nullable additions — safe on existing rows)
-- ---------------------------------------------------------------------------

-- Unique token sent to the rider; no password/JWT required on the tracking page
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS tracking_token UUID UNIQUE DEFAULT NULL;

-- Optional: structured pickup address (mirrors address JSONB already present)
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS pickup_address  JSONB DEFAULT NULL;

-- Destination coordinates — pre-geocoded when delivery is created
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS dest_lat    NUMERIC(10, 7) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS dest_lng    NUMERIC(10, 7) DEFAULT NULL;

-- Lifecycle timestamps
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS picked_up_at   TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS delivered_at   TIMESTAMP WITH TIME ZONE DEFAULT NULL;

-- Denorm: when did we last receive a ping for this delivery
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS last_ping_at   TIMESTAMP WITH TIME ZONE DEFAULT NULL;

-- Latest ETA string cached from routing_adapter (e.g. "12 min")
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS eta_text       TEXT DEFAULT NULL;

-- ---------------------------------------------------------------------------
-- 3. Extend riders  (denorm latest position for O(1) dashboard reads)
-- ---------------------------------------------------------------------------
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS last_lat       NUMERIC(10, 7) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS last_lng       NUMERIC(10, 7) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS last_seen_at   TIMESTAMP WITH TIME ZONE DEFAULT NULL;

-- ---------------------------------------------------------------------------
-- 4. Function: update rider denorm on new ping (called by backend, not trigger)
--    We keep this as a helper SQL function so the backend can call it in one
--    round-trip instead of two separate UPDATEs.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_update_rider_position(
    p_rider_id   UUID,
    p_lat        NUMERIC,
    p_lng        NUMERIC,
    p_ts         TIMESTAMP WITH TIME ZONE
) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    UPDATE riders
       SET last_lat     = p_lat,
           last_lng     = p_lng,
           last_seen_at = p_ts
     WHERE id = p_rider_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- 5. View: v_rider_live_positions
--    One row per rider who has at least one location_ping in the last 4 hours.
--    Used by GET /logistics/live-positions (dashboard poll) and the SSE feed.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_rider_live_positions AS
SELECT DISTINCT ON (r.id)
    r.id             AS rider_id,
    r.name           AS rider_name,
    r.phone          AS rider_phone,
    r.vehicle        AS rider_vehicle,
    r.active         AS rider_active,
    r.last_lat       AS lat,
    r.last_lng       AS lng,
    r.last_seen_at   AS last_seen_at,
    lp.speed_kmh,
    lp.accuracy_m,
    lp.battery_pct,
    lp.delivery_id   AS current_delivery_id
FROM riders r
LEFT JOIN location_pings lp
    ON lp.rider_id = r.id
   AND lp.ts > (now() - INTERVAL '4 hours')
WHERE r.active = TRUE
ORDER BY r.id, lp.ts DESC;

-- ---------------------------------------------------------------------------
-- 6. View: v_active_deliveries
--    In-transit deliveries joined with rider snapshot for the map overlay.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_active_deliveries AS
SELECT
    d.id                    AS delivery_id,
    d.reference,
    d.status,
    d.dest_lat,
    d.dest_lng,
    d.eta_text,
    d.last_ping_at,
    d.picked_up_at,
    d.address               AS destination_address,
    r.id                    AS rider_id,
    r.name                  AS rider_name,
    r.last_lat              AS rider_lat,
    r.last_lng              AS rider_lng,
    r.last_seen_at          AS rider_last_seen
FROM deliveries d
JOIN riders r ON r.id = d.assigned_rider
WHERE d.status IN ('assigned', 'in_transit')
  AND r.active = TRUE;

-- ---------------------------------------------------------------------------
-- 7. Index on tracking_token for O(1) token lookups (used on every ping)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_deliveries_tracking_token
    ON deliveries (tracking_token)
    WHERE tracking_token IS NOT NULL;

COMMIT;
