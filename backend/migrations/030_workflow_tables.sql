-- Migration: 030_workflow_tables.sql
-- Adds workflow and domain tables required by agent-driven automations

BEGIN;

-- Workflow job bookkeeping
CREATE TABLE IF NOT EXISTS workflow_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  payload JSONB,
  trace_id TEXT,
  owner_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Replenishment requests lifecycle table
CREATE TABLE IF NOT EXISTS replenishment_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku TEXT NOT NULL,
  product_id TEXT,
  requested_qty NUMERIC NOT NULL,
  status TEXT NOT NULL DEFAULT 'recommended',
  created_by TEXT,
  approved_by TEXT,
  po_id TEXT,
  received_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Batch status locks: used for compliance locking and blocking invoice issuance
CREATE TABLE IF NOT EXISTS batch_status_locks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id TEXT NOT NULL,
  locked BOOLEAN NOT NULL DEFAULT true,
  lock_reason TEXT,
  locked_until TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT
);

-- Delivery chain of custody events
CREATE TABLE IF NOT EXISTS chain_of_custody_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id TEXT NOT NULL,
  event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  location TEXT,
  temperature_c NUMERIC,
  recorded_by TEXT,
  notes TEXT
);

-- Credit risk actions ledger
CREATE TABLE IF NOT EXISTS credit_risk_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id TEXT NOT NULL,
  action TEXT NOT NULL,
  details JSONB,
  executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
