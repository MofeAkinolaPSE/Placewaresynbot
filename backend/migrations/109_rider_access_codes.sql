-- Persistent per-rider sign-in credential (ACE Riders), replacing the
-- disposable per-delivery tracking_token as the rider's own identity. A
-- rider signs in once with this code; the app resolves whichever delivery
-- is currently assigned to them, instead of staff re-issuing a fresh link
-- for every single trip.

ALTER TABLE riders
  ADD COLUMN IF NOT EXISTS access_code TEXT UNIQUE DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_riders_access_code ON riders(access_code);

-- Backfill any existing riders so no row is left without a usable code.
UPDATE riders
SET access_code = upper(substr(md5(random()::text || id::text), 1, 6))
WHERE access_code IS NULL;
