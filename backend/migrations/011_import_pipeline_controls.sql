-- Import Pipeline Controls: job lifecycle + row-level rejection queue
-- Adds observability and replay-ready diagnostics for robust in-app ETL.

begin;

create table if not exists public.placeware_import_jobs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  domain text not null,
  idempotency_key text,
  batch_id uuid not null,
  imported_at timestamptz not null,
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'partial_success')),
  metadata jsonb not null default '{}'::jsonb,
  counts jsonb not null default '{}'::jsonb,
  lineage jsonb not null default '{}'::jsonb,
  quality_score numeric,
  error_message text
);

create index if not exists idx_import_jobs_created on public.placeware_import_jobs(created_at desc);
create index if not exists idx_import_jobs_batch on public.placeware_import_jobs(batch_id);
create index if not exists idx_import_jobs_domain on public.placeware_import_jobs(domain);
create unique index if not exists uq_import_jobs_domain_idem
  on public.placeware_import_jobs(domain, idempotency_key)
  where idempotency_key is not null;

create table if not exists public.placeware_import_rejections (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  job_id uuid not null references public.placeware_import_jobs(id) on delete cascade,
  dataset text not null,
  row_number integer,
  reason text not null,
  raw_row jsonb not null default '{}'::jsonb,
  details jsonb not null default '{}'::jsonb
);

create index if not exists idx_import_rejections_job on public.placeware_import_rejections(job_id);
create index if not exists idx_import_rejections_dataset on public.placeware_import_rejections(dataset);

create table if not exists public.placeware_kpi_promotions (
  domain text primary key,
  batch_id uuid not null,
  job_id uuid references public.placeware_import_jobs(id) on delete set null,
  promoted_at timestamptz not null default now(),
  quality_score numeric,
  rejection_rate numeric,
  promoted_reason text not null default 'quality_gate_passed'
);

create index if not exists idx_kpi_promotions_promoted_at on public.placeware_kpi_promotions(promoted_at desc);

alter table public.placeware_import_jobs enable row level security;
alter table public.placeware_import_rejections enable row level security;
alter table public.placeware_kpi_promotions enable row level security;

drop policy if exists admin_all_import_jobs on public.placeware_import_jobs;
create policy admin_all_import_jobs on public.placeware_import_jobs
for all
using (true)
with check (true);

drop policy if exists admin_all_import_rejections on public.placeware_import_rejections;
create policy admin_all_import_rejections on public.placeware_import_rejections
for all
using (true)
with check (true);

drop policy if exists admin_all_kpi_promotions on public.placeware_kpi_promotions;
create policy admin_all_kpi_promotions on public.placeware_kpi_promotions
for all
using (true)
with check (true);

commit;
