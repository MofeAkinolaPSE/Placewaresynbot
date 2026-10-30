-- 28 Oct 2026: guided onboarding (docs/ACE-Guided-Onboarding-Engineering-Guide.md). The welcome tour runs once,
-- on a person's first sign-in; this records where they are in it, or that they finished or skipped it.
-- Kept on the login (placeware_users) rather than the HR profile so every account created on User Access has it
-- without an HR row being made for it. Shape: {"completed": bool, "skipped": bool, "current_step": int}.
ALTER TABLE placeware_users ADD COLUMN IF NOT EXISTS tour_state jsonb;
