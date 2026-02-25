-- Migration: Suppliers table and supplier metrics
CREATE TABLE IF NOT EXISTS suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  category TEXT NULL,
  contact JSONB NULL,
  reliability_score NUMERIC NULL,
  avg_delivery_time NUMERIC NULL,
  price_variance_index NUMERIC NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS supplier_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  scheduled_at TIMESTAMP WITH TIME ZONE NULL,
  delivered_at TIMESTAMP WITH TIME ZONE NULL,
  on_time BOOLEAN NULL,
  price NUMERIC NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_supplier_deliveries_supplier ON supplier_deliveries(supplier_id);
