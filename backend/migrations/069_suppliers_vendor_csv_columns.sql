-- Migration 069: Add vendor CSV columns to suppliers table
-- Enables vendors.csv import (via /sage/import/csv) to fully populate
-- the Suppliers dashboard with every column from the Sage export.

ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS external_vendor_id TEXT UNIQUE;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_name TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_email TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS payment_terms TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS tax_id TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS bank_details TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS current_balance NUMERIC DEFAULT 0;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';

-- Index for fast upsert lookups on re-upload
CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_external_vendor_id
    ON suppliers (external_vendor_id)
    WHERE external_vendor_id IS NOT NULL;
