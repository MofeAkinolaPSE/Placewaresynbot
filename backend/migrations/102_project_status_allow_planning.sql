-- 102_project_status_allow_planning.sql
--
-- Fixes a real, pre-existing bug found via live verification of the
-- Operations retrofit: ProjectControls.tsx's "New Project" form has always
-- offered a "Planning" status option, and its statusBadge() has a dedicated
-- render case for "planning" -- the UI clearly expected it to be a valid
-- value. Every attempt to create a project with status="planning" 500's,
-- because placeware_projects_status_check (015_project_controls_core.sql)
-- only ever allowed ('active', 'on_hold', 'completed', 'cancelled').
--
-- backend/src/constants.py's PROJECT_STATUS_ALLOWED was already corrected to
-- include "planning" in this same retrofit round, but that Python-level set
-- turned out not to be the actual gate on POST /controls/projects -- this
-- database CHECK constraint is, and it was never updated to match.
--
-- Idempotent: drops the constraint only if present, then recreates it with
-- the corrected allowed set.

ALTER TABLE public.placeware_projects
  DROP CONSTRAINT IF EXISTS placeware_projects_status_check;

ALTER TABLE public.placeware_projects
  ADD CONSTRAINT placeware_projects_status_check
  CHECK (status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled'));
