-- Stage 3 project controls core entities: scope/cost/risk/change
begin;

create table if not exists public.placeware_projects (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  name text not null,
  description text,
  owner_id text,
  status text not null default 'active' check (status in ('active', 'on_hold', 'completed', 'cancelled'))
);

create table if not exists public.placeware_scope_items (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  project_id uuid not null references public.placeware_projects(id) on delete cascade,
  title text not null,
  description text,
  priority text not null default 'medium' check (priority in ('low', 'medium', 'high', 'critical')),
  status text not null default 'planned' check (status in ('planned', 'in_progress', 'done', 'dropped')),
  created_by text
);

create table if not exists public.placeware_cost_items (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  project_id uuid not null references public.placeware_projects(id) on delete cascade,
  cost_type text not null,
  amount numeric not null check (amount >= 0),
  currency text not null default 'NGN',
  status text not null default 'planned' check (status in ('planned', 'approved', 'committed', 'spent', 'cancelled')),
  note text,
  created_by text
);

create table if not exists public.placeware_risk_register (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  project_id uuid not null references public.placeware_projects(id) on delete cascade,
  title text not null,
  description text,
  probability integer not null check (probability between 1 and 5),
  impact integer not null check (impact between 1 and 5),
  mitigation_plan text,
  owner_id text,
  status text not null default 'open' check (status in ('open', 'mitigating', 'accepted', 'closed')),
  created_by text
);

create table if not exists public.placeware_change_requests (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  project_id uuid not null references public.placeware_projects(id) on delete cascade,
  title text not null,
  description text not null,
  requested_by text,
  reason_code text,
  impact_scope text,
  impact_cost numeric,
  impact_schedule_days integer,
  status text not null default 'proposed' check (status in ('proposed', 'under_review', 'approved', 'rejected', 'implemented')),
  approval_note text,
  approval_reason text,
  approved_by text,
  approved_at timestamptz,
  attestation_text text,
  signature_hash_ref text
);

create index if not exists idx_projects_status on public.placeware_projects(status);
create index if not exists idx_scope_project on public.placeware_scope_items(project_id, created_at desc);
create index if not exists idx_cost_project on public.placeware_cost_items(project_id, created_at desc);
create index if not exists idx_risk_project on public.placeware_risk_register(project_id, created_at desc);
create index if not exists idx_change_project on public.placeware_change_requests(project_id, created_at desc);

alter table public.placeware_projects enable row level security;
alter table public.placeware_scope_items enable row level security;
alter table public.placeware_cost_items enable row level security;
alter table public.placeware_risk_register enable row level security;
alter table public.placeware_change_requests enable row level security;

drop policy if exists admin_all_projects on public.placeware_projects;
create policy admin_all_projects on public.placeware_projects for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists admin_all_scope_items on public.placeware_scope_items;
create policy admin_all_scope_items on public.placeware_scope_items for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists admin_all_cost_items on public.placeware_cost_items;
create policy admin_all_cost_items on public.placeware_cost_items for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists admin_all_risk_register on public.placeware_risk_register;
create policy admin_all_risk_register on public.placeware_risk_register for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists admin_all_change_requests on public.placeware_change_requests;
create policy admin_all_change_requests on public.placeware_change_requests for all to authenticated using (public.is_admin()) with check (public.is_admin());

commit;
