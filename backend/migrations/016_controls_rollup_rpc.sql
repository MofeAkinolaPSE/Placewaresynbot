-- Stage 3 Pass E: DB-level controls rollup aggregation RPC
begin;

create or replace function public.placeware_controls_rollup(p_project_id uuid default null)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with
scope_counts as (
  select coalesce(jsonb_object_agg(status, cnt), '{}'::jsonb) as counts, coalesce(sum(cnt), 0) as total
  from (
    select status, count(*)::int as cnt
    from public.placeware_scope_items
    where p_project_id is null or project_id = p_project_id
    group by status
  ) x
),
cost_counts as (
  select coalesce(jsonb_object_agg(status, cnt), '{}'::jsonb) as counts, coalesce(sum(cnt), 0) as total
  from (
    select status, count(*)::int as cnt
    from public.placeware_cost_items
    where p_project_id is null or project_id = p_project_id
    group by status
  ) x
),
risk_counts as (
  select coalesce(jsonb_object_agg(status, cnt), '{}'::jsonb) as counts, coalesce(sum(cnt), 0) as total
  from (
    select status, count(*)::int as cnt
    from public.placeware_risk_register
    where p_project_id is null or project_id = p_project_id
    group by status
  ) x
),
risk_open_high as (
  select count(*)::int as high_risk_open_count
  from public.placeware_risk_register
  where (p_project_id is null or project_id = p_project_id)
    and coalesce(status, '') <> 'closed'
    and (coalesce(probability, 0) * coalesce(impact, 0)) >= 15
),
change_counts as (
  select coalesce(jsonb_object_agg(status, cnt), '{}'::jsonb) as counts, coalesce(sum(cnt), 0) as total
  from (
    select status, count(*)::int as cnt
    from public.placeware_change_requests
    where p_project_id is null or project_id = p_project_id
    group by status
  ) x
),
pending_changes as (
  select count(*)::int as pending_approvals
  from public.placeware_change_requests
  where (p_project_id is null or project_id = p_project_id)
    and status in ('proposed', 'under_review')
)
select jsonb_build_object(
  'project_id', p_project_id,
  'scope', jsonb_build_object('status_counts', scope_counts.counts, 'total', scope_counts.total),
  'cost', jsonb_build_object('status_counts', cost_counts.counts, 'total', cost_counts.total),
  'risk', jsonb_build_object('status_counts', risk_counts.counts, 'total', risk_counts.total, 'high_risk_open_count', risk_open_high.high_risk_open_count),
  'change', jsonb_build_object('status_counts', change_counts.counts, 'total', change_counts.total, 'pending_approvals', pending_changes.pending_approvals)
)
from scope_counts, cost_counts, risk_counts, risk_open_high, change_counts, pending_changes;
$$;

grant execute on function public.placeware_controls_rollup(uuid) to authenticated, anon;

commit;
