-- Stage 4 Pass C: domain-aware control scoring policy configuration
begin;

alter table if exists public.placeware_data_policies
  add column if not exists controls_config jsonb not null default '{}'::jsonb;

update public.placeware_data_policies
set controls_config = jsonb_build_object(
  'severity_weights', jsonb_build_object('info', 1, 'warning', 2, 'error', 4, 'critical', 6),
  'density_penalty_cap', 65,
  'severity_penalty_cap', 35,
  'rejection_penalty_cap', 20,
  'severity_penalty_multiplier', 11
)
where domain = 'sage' and active = true and (controls_config is null or controls_config = '{}'::jsonb);

update public.placeware_data_policies
set controls_config = jsonb_build_object(
  'severity_weights', jsonb_build_object('info', 1, 'warning', 2, 'error', 4, 'critical', 6),
  'density_penalty_cap', 55,
  'severity_penalty_cap', 45,
  'rejection_penalty_cap', 20,
  'severity_penalty_multiplier', 9
)
where domain = 'hr' and active = true and (controls_config is null or controls_config = '{}'::jsonb);

update public.placeware_data_policies
set controls_config = jsonb_build_object(
  'severity_weights', jsonb_build_object('info', 1, 'warning', 2, 'error', 4, 'critical', 6),
  'density_penalty_cap', 60,
  'severity_penalty_cap', 40,
  'rejection_penalty_cap', 20,
  'severity_penalty_multiplier', 10
)
where domain in ('ops', 'crm') and active = true and (controls_config is null or controls_config = '{}'::jsonb);

commit;
