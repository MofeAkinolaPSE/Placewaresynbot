-- =============================================================================
-- Migration 114 — per-document column selection for the Sage export
-- =============================================================================
-- Sage imports a CSV by position against the Fields tab of its import
-- template, so the fields ticked here must match the fields shown in Sage.
-- Stored once, server-side, so every finance user exports the same layout.
-- Shape: {"sales": ["Customer ID", ...], ...}; a missing doc = all columns.
-- =============================================================================

ALTER TABLE sage_export_settings
    ADD COLUMN IF NOT EXISTS column_selection JSONB NOT NULL DEFAULT '{}'::jsonb;
