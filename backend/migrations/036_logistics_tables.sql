-- Migration: Logistics tables (deliveries, riders, routes)
CREATE TABLE IF NOT EXISTS riders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  phone TEXT NULL,
  vehicle TEXT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reference TEXT NULL,
  customer_id UUID NULL,
  address JSONB NULL,
  quantity NUMERIC NULL,
  status TEXT NOT NULL DEFAULT 'unassigned', -- unassigned, assigned, picked_up, en_route, delivered, failed
  assigned_rider UUID NULL REFERENCES riders(id),
  eta TIMESTAMP WITH TIME ZONE NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS routes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id UUID NOT NULL REFERENCES riders(id),
  deliveries JSONB NOT NULL,
  route_meta JSONB NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(status);
