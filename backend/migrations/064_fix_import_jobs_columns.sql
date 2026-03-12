-- Migration 064: Add missing columns to placeware_import_jobs
-- Migration 011 created the table without governance/retention columns.
-- Migration 060 used CREATE TABLE IF NOT EXISTS so column additions were skipped.
-- This migration safely adds the missing columns via ALTER TABLE ADD COLUMN IF NOT EXISTS.

alter table public.placeware_import_jobs
  add column if not exists schema_version    text not null default '2026.1',
  add column if not exists policy_version    text not null default '2026.1',
  add column if not exists retention_days    integer not null default 1825,
  add column if not exists retention_expires_at timestamptz,
  add column if not exists row_count         integer not null default 0;

-- Index to speed up get_latest_successful_import_batch lookups
create index if not exists idx_import_jobs_domain_status
  on public.placeware_import_jobs (domain, status, finished_at desc);

-- Ensure placeware_kpi_promotions exists (needed by get_promoted_kpi_batch)
create table if not exists public.placeware_kpi_promotions (
  domain            text primary key,
  batch_id          uuid not null,
  job_id            uuid references public.placeware_import_jobs(id) on delete set null,
  promoted_at       timestamptz not null default now(),
  quality_score     numeric,
  rejection_rate    numeric,
  promoted_reason   text not null default 'quality_gate_passed'
);
