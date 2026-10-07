-- =============================================================================
-- Migration 115 — Sage open-period guard for the Sage export
-- =============================================================================
-- Sage 50 only accepts transactions dated inside its open fiscal years and
-- refuses anything later at the Date field ("Line Number: n, Field Name:
-- Date ... The process cannot continue"). The accountant records the last
-- open date here; ACE holds later records back instead of exporting them.
-- NULL = no limit known (nothing held back on this ground).
-- =============================================================================

ALTER TABLE sage_export_settings
    ADD COLUMN IF NOT EXISTS sage_open_until DATE;
