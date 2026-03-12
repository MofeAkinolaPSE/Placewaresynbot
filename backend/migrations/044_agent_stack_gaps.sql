-- Migration: 044_agent_stack_gaps.sql
-- Consolidated schema updates for Agent Stack gap closure.

BEGIN;

-- ------------------------------------------------------------
-- Revenue planning tables
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS revenue_goals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  target_pct NUMERIC(6,2) NOT NULL,
  timeframe_months INT NOT NULL DEFAULT 6,
  baseline_revenue NUMERIC(14,2) NOT NULL DEFAULT 0,
  strategy_type TEXT NOT NULL DEFAULT 'blended',
  notes TEXT,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS revenue_scenarios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  goal_id UUID REFERENCES revenue_goals(id) ON DELETE CASCADE,
  scenario_name TEXT NOT NULL,
  projected_revenue NUMERIC(14,2) NOT NULL DEFAULT 0,
  assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_revenue_scenarios_goal_id ON revenue_scenarios(goal_id);

-- ------------------------------------------------------------
-- Finance / credit controls
-- ------------------------------------------------------------
ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14,2) NOT NULL DEFAULT 0;

-- ------------------------------------------------------------
-- Logistics & SLA enrichment
-- ------------------------------------------------------------
ALTER TABLE deliveries
  ADD COLUMN IF NOT EXISTS sla_minutes INT,
  ADD COLUMN IF NOT EXISTS actual_minutes INT,
  ADD COLUMN IF NOT EXISTS breach BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE supplier_deliveries
  ADD COLUMN IF NOT EXISTS delay_minutes NUMERIC,
  ADD COLUMN IF NOT EXISTS sla_minutes NUMERIC,
  ADD COLUMN IF NOT EXISTS fuel_cost NUMERIC,
  ADD COLUMN IF NOT EXISTS route TEXT,
  ADD COLUMN IF NOT EXISTS origin_to_dest TEXT,
  ADD COLUMN IF NOT EXISTS customer_id TEXT;

CREATE INDEX IF NOT EXISTS idx_supplier_deliveries_route ON supplier_deliveries(route);

-- ------------------------------------------------------------
-- Process optimization metrics
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS process_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_type TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  duration_minutes NUMERIC,
  reference_id TEXT,
  measured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_process_metrics_stage_time ON process_metrics(stage_name, measured_at DESC);

-- ------------------------------------------------------------
-- Chain-of-custody signature support
-- ------------------------------------------------------------
ALTER TABLE chain_of_custody_events
  ADD COLUMN IF NOT EXISTS event_type TEXT,
  ADD COLUMN IF NOT EXISTS signature_name TEXT,
  ADD COLUMN IF NOT EXISTS signature_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS signed_by TEXT;

-- ------------------------------------------------------------
-- Risk heatmap persistence
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_heatmap_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain TEXT NOT NULL,
  category TEXT,
  severity INT NOT NULL CHECK (severity BETWEEN 1 AND 5),
  likelihood INT NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
  impact_value NUMERIC(14,2) NOT NULL DEFAULT 0,
  trend TEXT,
  snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_heatmap_snapshots_date ON risk_heatmap_snapshots(snapshot_date DESC);

-- ------------------------------------------------------------
-- Delivery vehicle temperature logs
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS delivery_vehicle_temps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id TEXT NOT NULL,
  shipment_id TEXT,
  temperature_c NUMERIC NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_compliant BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_delivery_vehicle_temps_vehicle_time ON delivery_vehicle_temps(vehicle_id, recorded_at DESC);

COMMIT;
