-- Migration: Supplier Scorecard & Import Tracking
-- Implements supplier reliability tracking per Agent_stack.md

-- Add scorecard columns to suppliers table
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS avg_delay_days NUMERIC DEFAULT 0;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS rejection_count INTEGER DEFAULT 0;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS total_shipments INTEGER DEFAULT 0;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS compliance_issues INTEGER DEFAULT 0;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS last_evaluated_at TIMESTAMP WITH TIME ZONE;

-- Supplier scorecard historical tracking
CREATE TABLE IF NOT EXISTS placeware_supplier_scorecards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  evaluation_period TEXT NOT NULL, -- e.g., '2026-Q1', '2026-02'
  avg_delay_days NUMERIC,
  rejection_rate NUMERIC, -- percentage
  compliance_score NUMERIC, -- 0-100
  total_shipments INTEGER,
  on_time_rate NUMERIC, -- percentage
  cost_variance NUMERIC,
  notes TEXT,
  evaluated_by UUID,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_supplier_scorecards_supplier 
  ON placeware_supplier_scorecards(supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_scorecards_period 
  ON placeware_supplier_scorecards(evaluation_period);

-- Shipment lifecycle states for Import Clearance Agent
CREATE TABLE IF NOT EXISTS placeware_shipments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL,
  shipment_ref TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'in_transit',
    -- Valid states: in_transit, at_port, under_clearance, released, delivered, rejected
  products JSONB, -- list of SKUs/quantities
  estimated_value NUMERIC,
  eta TIMESTAMP WITH TIME ZONE,
  port_arrived_at TIMESTAMP WITH TIME ZONE,
  clearance_started_at TIMESTAMP WITH TIME ZONE,
  clearance_completed_at TIMESTAMP WITH TIME ZONE,
  delivered_at TIMESTAMP WITH TIME ZONE,
  delay_days INTEGER GENERATED ALWAYS AS (
    CASE 
      WHEN clearance_completed_at IS NOT NULL AND clearance_started_at IS NOT NULL 
      THEN EXTRACT(DAY FROM (clearance_completed_at - clearance_started_at))::INTEGER
      ELSE NULL
    END
  ) STORED,
  rejection_reason TEXT,
  regulatory_docs JSONB,
  notes TEXT,
  created_by UUID,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shipments_status ON placeware_shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_supplier ON placeware_shipments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_shipments_eta ON placeware_shipments(eta);

-- Clearance delay alerts
CREATE TABLE IF NOT EXISTS placeware_clearance_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id UUID NOT NULL REFERENCES placeware_shipments(id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL, -- 'delay_threshold', 'cost_impact', 'escalation'
  days_delayed INTEGER,
  estimated_cost_impact NUMERIC,
  escalated_to UUID,
  resolved BOOLEAN DEFAULT FALSE,
  resolved_at TIMESTAMP WITH TIME ZONE,
  notes TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clearance_alerts_shipment 
  ON placeware_clearance_alerts(shipment_id);
CREATE INDEX IF NOT EXISTS idx_clearance_alerts_resolved 
  ON placeware_clearance_alerts(resolved);

-- RPC to calculate supplier scorecard
CREATE OR REPLACE FUNCTION calculate_supplier_scorecard(p_supplier_id UUID, p_period TEXT)
RETURNS JSONB LANGUAGE plpgsql AS $$
DECLARE
  result JSONB;
  v_total INTEGER;
  v_on_time INTEGER;
  v_avg_delay NUMERIC;
  v_rejections INTEGER;
BEGIN
  SELECT 
    COUNT(*),
    COUNT(*) FILTER (WHERE status = 'delivered' AND delay_days <= 0),
    COALESCE(AVG(delay_days) FILTER (WHERE delay_days IS NOT NULL), 0),
    COUNT(*) FILTER (WHERE status = 'rejected')
  INTO v_total, v_on_time, v_avg_delay, v_rejections
  FROM placeware_shipments
  WHERE supplier_id = p_supplier_id
    AND created_at >= (NOW() - INTERVAL '90 days');
  
  result = jsonb_build_object(
    'supplier_id', p_supplier_id,
    'period', p_period,
    'total_shipments', v_total,
    'on_time_rate', CASE WHEN v_total > 0 THEN ROUND((v_on_time::NUMERIC / v_total) * 100, 2) ELSE 0 END,
    'avg_delay_days', ROUND(v_avg_delay, 1),
    'rejection_rate', CASE WHEN v_total > 0 THEN ROUND((v_rejections::NUMERIC / v_total) * 100, 2) ELSE 0 END
  );
  
  RETURN result;
END;
$$;
