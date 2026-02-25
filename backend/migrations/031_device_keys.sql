-- Migration: 031_device_keys.sql
-- Stores device keys for IoT ingestion (SHA256 hashed)

BEGIN;

CREATE TABLE IF NOT EXISTS device_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id TEXT NOT NULL,
  key_hash TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_device_keys_hash ON device_keys(key_hash);

COMMIT;
