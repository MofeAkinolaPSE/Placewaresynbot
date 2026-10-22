-- 22 Oct 2026: access changes take effect at once. When an admin changes someone's access (Edit
-- access), deactivates them or resets their password, this is stamped; any session token issued
-- before it is refused, so the app refreshes it and gets the new roles straight away (before, the
-- old access lasted until the 45-minute token ran out).
ALTER TABLE placeware_users ADD COLUMN IF NOT EXISTS access_changed_at timestamptz;
