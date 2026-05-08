-- Compliance retention/version policy baseline for import jobs
begin;

alter table if exists public.placeware_import_jobs
  add column if not exists schema_version text not null default '2026.1',
  add column if not exists policy_version text not null default '2026.1',
  add column if not exists retention_days integer not null default 1825,
  add column if not exists retention_expires_at timestamptz;

create index if not exists idx_import_jobs_retention_expires
  on public.placeware_import_jobs(retention_expires_at);

create table if not exists public.placeware_data_policies (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  domain text not null,
  policy_version text not null,
  schema_version text not null,
  retention_days integer not null check (retention_days > 0),
  effective_from timestamptz not null default now(),
  active boolean not null default true,
  notes text
);

create index if not exists idx_data_policies_domain_effective
  on public.placeware_data_policies(domain, effective_from desc);

create unique index if not exists uq_data_policies_active_domain
  on public.placeware_data_policies(domain)
  where active = true;

insert into public.placeware_data_policies (domain, policy_version, schema_version, retention_days, active, notes)
values
  ('sage', '2026.1', '2026.1', 2555, true, 'Finance/compliance baseline retention policy'),
  ('hr', '2026.1', '2026.1', 2555, true, 'Workforce/payroll baseline retention policy'),
  ('ops', '2026.1', '2026.1', 1825, true, 'Operations baseline retention policy'),
  ('crm', '2026.1', '2026.1', 1825, true, 'CRM baseline retention policy')
on conflict do nothing;

alter table public.placeware_data_policies enable row level security;

drop policy if exists admin_all_data_policies on public.placeware_data_policies;
create policy admin_all_data_policies on public.placeware_data_policies
for all
USING (true)
WITH CHECK (true);

commit;
