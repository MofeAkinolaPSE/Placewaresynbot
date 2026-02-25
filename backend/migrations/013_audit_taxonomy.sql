-- Expanded audit taxonomy for traceability and compliance observability
begin;

alter table if exists public.placeware_audit_logs
  add column if not exists event_class text not null default 'system',
  add column if not exists action text,
  add column if not exists outcome text not null default 'success',
  add column if not exists reason_code text,
  add column if not exists actor_id text,
  add column if not exists actor_role text,
  add column if not exists subject_type text,
  add column if not exists subject_id text,
  add column if not exists trace_id uuid;

alter table if exists public.placeware_audit_logs
  alter column details set default '{}'::jsonb;

update public.placeware_audit_logs
set event_class = case
  when event_type like 'auth_%' then 'security'
  when event_type like 'sage_%' or event_type like '%_import' then 'data_ingestion'
  when event_type like 'user_%' then 'identity'
  when event_type like 'intent_%' or event_type like 'workflow_%' then 'workflow'
  when event_type like 'ops_%' or event_type like 'hr_%' or event_type like 'crm_%' then 'analytics'
  else coalesce(event_class, 'system')
end,
action = coalesce(action, event_type),
outcome = case
  when event_type like '%fail%' or event_type like '%error%' then 'failed'
  else coalesce(outcome, 'success')
end
where true;

create index if not exists idx_audit_logs_created on public.placeware_audit_logs(created_at desc);
create index if not exists idx_audit_logs_class_outcome on public.placeware_audit_logs(event_class, outcome);
create index if not exists idx_audit_logs_actor on public.placeware_audit_logs(actor_id);
create index if not exists idx_audit_logs_trace_id on public.placeware_audit_logs(trace_id);

commit;
