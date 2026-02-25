-- Migration: rename legacy leads table to new Placeware naming
-- Safe pattern: only rename if old table exists and new one does not.

DO $$
BEGIN
    IF to_regclass('public."PSE Leads Table"') IS NOT NULL AND to_regclass('public.placeware_leads') IS NULL THEN
        EXECUTE 'ALTER TABLE "PSE Leads Table" RENAME TO placeware_leads';
    END IF;
END $$;

-- Add created_at if missing
ALTER TABLE placeware_leads
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
