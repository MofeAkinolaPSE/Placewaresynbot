begin;

alter table if exists public.placeware_projects
  add column if not exists activity_type text,
  add column if not exists supplier_name text,
  add column if not exists assigned_staff_id text;

create index if not exists idx_projects_activity_type
  on public.placeware_projects(activity_type);

create index if not exists idx_projects_assigned_staff
  on public.placeware_projects(assigned_staff_id);

commit;
