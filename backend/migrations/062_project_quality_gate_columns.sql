begin;

alter table if exists public.placeware_projects
  add column if not exists quality_check_status text,
  add column if not exists quality_notes text,
  add column if not exists quality_checked_by text,
  add column if not exists quality_checked_at timestamptz;

create index if not exists idx_projects_quality_check_status
  on public.placeware_projects(quality_check_status);

commit;
