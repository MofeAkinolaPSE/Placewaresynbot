Migration 085: Extend crm_prospects for Google Places enrichment
-- Non-breaking ALTERs + deduplication index + query cache table
-- Depends on: 045_collab_lead_finder.sql

BEGIN;

-- ── Add Places API columns to crm_prospects (all idempotent) ─────────────────
ALTER TABLE crm_prospects
  ADD COLUMN IF NOT EXISTS place_id           TEXT,
  ADD COLUMN IF NOT EXISTS lat                NUMERIC(10,7),
  ADD COLUMN IF NOT EXISTS lng                NUMERIC(10,7),
  ADD COLUMN IF NOT EXISTS rating             NUMERIC(3,1),
  ADD COLUMN IF NOT EXISTS user_ratings_total INT,
  ADD COLUMN IF NOT EXISTS website            TEXT,
  ADD COLUMN IF NOT EXISTS phone_number       TEXT,
  ADD COLUMN IF NOT EXISTS formatted_address  TEXT,
  ADD COLUMN IF NOT EXISTS places_score       NUMERIC(5,2) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS search_query       TEXT;    -- tracks which search produced this prospect

-- Unique deduplication index on place_id (NULLs excluded per SQL standard)
CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_prospects_place_id
  ON crm_prospects(place_id) WHERE place_id IS NOT NULL;

-- Geo index for future spatial queries / map bounding-box filters
CREATE INDEX IF NOT EXISTS idx_crm_prospects_geo
  ON crm_prospects(lat, lng) WHERE lat IS NOT NULL AND lng IS NOT NULL;

-- ── Query result cache ────────────────────────────────────────────────────────
-- Tracks which search queries were recently run to avoid duplicate API calls.
CREATE TABLE IF NOT EXISTS prospect_search_cache (
  query_key       TEXT PRIMARY KEY,   -- SHA-256 of (location|business_type|radius_m)
  search_location TEXT NOT NULL,
  business_type   TEXT NOT NULL,
  radius_m        INT  NOT NULL DEFAULT 5000,
  result_count    INT  NOT NULL DEFAULT 0,
  cached_at       TIMESTAMPTZ DEFAULT now()
);

COMMIT;
