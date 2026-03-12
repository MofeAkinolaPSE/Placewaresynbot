begin;

create table if not exists public.placeware_import_jobs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  domain text not null,
  idempotency_key text,
  batch_id uuid not null,
  imported_at timestamptz not null,
  schema_version text not null default '2026.1',
  policy_version text not null default '2026.1',
  retention_days integer not null default 1825,
  retention_expires_at timestamptz,
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'partial_success')),
  metadata jsonb not null default '{}'::jsonb,
  counts jsonb not null default '{}'::jsonb,
  lineage jsonb not null default '{}'::jsonb,
  quality_score numeric,
  error_message text
);

create table if not exists public.placeware_kpi_promotions (
  domain text primary key,
  batch_id uuid not null,
  job_id uuid references public.placeware_import_jobs(id) on delete set null,
  promoted_at timestamptz not null default now(),
  quality_score numeric,
  rejection_rate numeric,
  promoted_reason text not null default 'quality_gate_passed'
);

create table if not exists public.placeware_projects (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  name text not null,
  description text,
  owner_id text,
  status text not null default 'active' check (status in ('active', 'on_hold', 'completed', 'cancelled')),
  activity_type text,
  supplier_name text,
  assigned_staff_id text
);

create index if not exists idx_import_jobs_created
  on public.placeware_import_jobs(created_at desc);

create index if not exists idx_kpi_promotions_promoted_at
  on public.placeware_kpi_promotions(promoted_at desc);

create index if not exists idx_projects_status
  on public.placeware_projects(status);

commit;
