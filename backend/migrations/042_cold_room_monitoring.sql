-- Migration: Cold Room & Storage Zone Monitoring
-- Implements cold-chain capacity tracking per Agent_stack.md

-- Storage zones (cold rooms, warehouses, etc.)
CREATE TABLE IF NOT EXISTS placeware_storage_zones (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  zone_name TEXT NOT NULL,
  zone_type TEXT NOT NULL DEFAULT 'cold_room', -- cold_room, ambient, freezer, etc.
  location TEXT,
  max_capacity NUMERIC NOT NULL DEFAULT 0, -- in units or cubic meters
  current_load NUMERIC NOT NULL DEFAULT 0,
  temperature_min NUMERIC, -- allowed min temp in C
  temperature_max NUMERIC, -- allowed max temp in C
  current_temperature NUMERIC, -- latest reading
  avg_daily_inflow NUMERIC DEFAULT 0, -- average daily incoming stock
  avg_daily_outflow NUMERIC DEFAULT 0, -- average daily outgoing stock
  last_temp_check TIMESTAMP WITH TIME ZONE,
  status TEXT DEFAULT 'active', -- active, maintenance, offline
  metadata JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_storage_zones_type ON placeware_storage_zones(zone_type);
CREATE INDEX IF NOT EXISTS idx_storage_zones_status ON placeware_storage_zones(status);

-- Temperature log for cold rooms
CREATE TABLE IF NOT EXISTS placeware_temperature_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  zone_id UUID NOT NULL REFERENCES placeware_storage_zones(id) ON DELETE CASCADE,
  temperature_c NUMERIC NOT NULL,
  humidity_pct NUMERIC,
  recorded_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  sensor_id TEXT,
  is_violation BOOLEAN GENERATED ALWAYS AS (
    temperature_c < 2.0 OR temperature_c > 8.0
  ) STORED
);

CREATE INDEX IF NOT EXISTS idx_temp_logs_zone ON placeware_temperature_logs(zone_id);
CREATE INDEX IF NOT EXISTS idx_temp_logs_time ON placeware_temperature_logs(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_temp_logs_violation ON placeware_temperature_logs(is_violation) WHERE is_violation = TRUE;

-- Cold room capacity alerts
CREATE TABLE IF NOT EXISTS placeware_capacity_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  zone_id UUID NOT NULL REFERENCES placeware_storage_zones(id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL, -- 'over_threshold', 'overflow_forecast', 'temperature_violation'
  usage_pct NUMERIC,
  days_to_full INTEGER,
  temperature_c NUMERIC,
  acknowledged BOOLEAN DEFAULT FALSE,
  acknowledged_by UUID,
  acknowledged_at TIMESTAMP WITH TIME ZONE,
  resolved BOOLEAN DEFAULT FALSE,
  resolved_at TIMESTAMP WITH TIME ZONE,
  notes TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_capacity_alerts_zone ON placeware_capacity_alerts(zone_id);
CREATE INDEX IF NOT EXISTS idx_capacity_alerts_resolved ON placeware_capacity_alerts(resolved);

-- Seed sample cold room data
INSERT INTO placeware_storage_zones (zone_name, zone_type, location, max_capacity, current_load, temperature_min, temperature_max, current_temperature, avg_daily_inflow)
VALUES 
  ('Cold Room A', 'cold_room', 'Main Warehouse', 1000, 750, 2.0, 8.0, 4.2, 50),
  ('Cold Room B', 'cold_room', 'Main Warehouse', 800, 680, 2.0, 8.0, 5.1, 40),
  ('Freezer 1', 'freezer', 'Main Warehouse', 500, 200, -25.0, -18.0, -20.5, 20),
  ('Ambient Storage', 'ambient', 'Main Warehouse', 2000, 1100, 15.0, 25.0, 22.0, 100)
ON CONFLICT DO NOTHING;

-- RPC to get capacity summary
CREATE OR REPLACE FUNCTION get_storage_capacity_summary()
RETURNS TABLE (
  zone_id UUID,
  zone_name TEXT,
  zone_type TEXT,
  usage_pct NUMERIC,
  days_to_full NUMERIC,
  temperature_c NUMERIC,
  status TEXT
) LANGUAGE SQL AS $$
  SELECT 
    id AS zone_id,
    zone_name,
    zone_type,
    ROUND((current_load / NULLIF(max_capacity, 0)) * 100, 1) AS usage_pct,
    CASE 
      WHEN avg_daily_inflow > 0 THEN 
        ROUND((max_capacity - current_load) / avg_daily_inflow, 0)
      ELSE NULL
    END AS days_to_full,
    current_temperature AS temperature_c,
    status
  FROM placeware_storage_zones
  WHERE status = 'active'
  ORDER BY usage_pct DESC;
$$;
