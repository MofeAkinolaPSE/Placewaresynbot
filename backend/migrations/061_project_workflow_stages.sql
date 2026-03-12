begin;

alter table if exists public.placeware_projects
  add column if not exists workflow_stage text,
  add column if not exists po_reference text,
  add column if not exists temperature_profile text,
  add column if not exists nafdac_sampling_status text;

create index if not exists idx_projects_workflow_stage
  on public.placeware_projects(workflow_stage);

commit;
