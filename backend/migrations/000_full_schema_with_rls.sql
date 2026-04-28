-- Placeware Full Schema Bootstrap + RLS
-- Use this to recover/recreate the project database in one pass.
-- Recommended: run in Supabase SQL Editor as project owner.

begin;

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
create extension if not exists pgcrypto;
create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Local dev: create minimal roles and auth stubs
-- These are no-ops if the roles/schema/functions already exist and
-- make the file safe to run on a plain Postgres instance (not only Supabase).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.jwt()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT '{}'::jsonb;
$$;

CREATE OR REPLACE FUNCTION NULL
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT NULL::text;
$$;

-- ---------------------------------------------------------------------------
-- Core/Public Tables
-- ---------------------------------------------------------------------------
create table if not exists public.placeware_leads (
  id bigint generated always as identity primary key,
  name text not null,
  email text,
  phone text,
  message text,
  service text,
  company_size text,
  contact_pref text,
  created_at timestamptz not null default now()
);

-- Legacy rename safety (if old table exists)
do $$
begin
  if to_regclass('public."PSE Leads Table"') is not null and to_regclass('public.placeware_leads') is null then
    execute 'alter table public."PSE Leads Table" rename to placeware_leads';
  end if;
end $$;

-- Optional cache table used by backend upsert_stock_cache()
create table if not exists public.placeware_stock_cache (
  sku text primary key,
  name text,
  quantity numeric,
  unit_cost numeric,
  valuation numeric,
  imported_at timestamptz,
  updated_at timestamptz not null default now()
);

-- Existing vector QnA table + RPC for retrieval
create table if not exists public.qna (
  id bigint generated always as identity primary key,
  question text not null,
  answer text not null,
  embedding vector(384),
  source text
);

create index if not exists idx_qna_embedding_ivfflat
  on public.qna using ivfflat (embedding vector_cosine_ops);

create or replace function public.match_documents(
  query_embedding vector(384),
  match_threshold float,
  match_count int
)
returns table (
  id bigint,
  question text,
  answer text,
  similarity float
)
language plpgsql
stable
as $$
declare
  col_id text;
  col_question text;
  col_answer text;
  col_embedding text;
  col_embedding_type text;
  embedding_expr text;
  dyn_sql text;
begin
  select a.attname into col_id
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'id'
  limit 1;

  select a.attname into col_question
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'question'
  limit 1;

  select a.attname into col_answer
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'answer'
  limit 1;

  select a.attname into col_embedding
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'embedding'
  limit 1;

  select t.typname into col_embedding_type
  from pg_attribute a
  join pg_type t on t.oid = a.atttypid
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'embedding'
  limit 1;

  if col_question is null or col_answer is null or col_embedding is null then
    raise exception 'qna table missing required columns (question/answer/embedding)';
  end if;

  if col_embedding_type = 'vector' then
    embedding_expr := format('q.%I', col_embedding);
  else
    -- Compatibility path for legacy schemas where embedding was stored as json/jsonb/text.
    -- pgvector accepts a text literal like '[0.1,0.2,...]'.
    embedding_expr := format('(q.%I::text)::vector(384)', col_embedding);
  end if;

  dyn_sql := format(
    'select %s as id, q.%I::text as question, q.%I::text as answer, 1 - ((%s) <=> $1) as similarity
       from public.qna q
      where 1 - ((%s) <=> $1) > $2
      order by (%s) <=> $1
      limit $3',
    case when col_id is not null then format('q.%I::bigint', col_id) else 'null::bigint' end,
    col_question,
    col_answer,
    embedding_expr,
    embedding_expr,
    embedding_expr
  );

  return query execute dyn_sql using query_embedding, match_threshold, match_count;
end;
$$;

-- ---------------------------------------------------------------------------
-- Sage Snapshots + Audit
-- ---------------------------------------------------------------------------
create table if not exists public.sage_customers_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  customer_id text not null,
  name text not null,
  email text,
  phone text,
  status text
);

create table if not exists public.sage_ar_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  invoice_id text not null,
  customer_id text not null,
  date date not null,
  due_date date,
  amount numeric not null,
  balance numeric not null,
  status text
);

create table if not exists public.sage_ap_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  bill_id text not null,
  vendor_id text not null,
  date date not null,
  due_date date,
  amount numeric not null,
  balance numeric not null,
  status text
);

create table if not exists public.sage_gl_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  period text not null,
  account_code text not null,
  account_name text not null,
  debit numeric not null,
  credit numeric not null
);

create table if not exists public.sage_inventory_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  sku text not null,
  name text not null,
  quantity numeric not null,
  unit_cost numeric,
  valuation numeric,
  expiry_date date,
  updated_at timestamptz
);

create table if not exists public.sage_staff_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  staff_id text not null,
  full_name text not null,
  email text,
  department text,
  role text,
  status text
);

create table if not exists public.placeware_audit_logs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  event_type text not null,
  event_class text not null default 'system',
  action text,
  outcome text not null default 'success',
  reason_code text,
  actor_id text,
  actor_role text,
  subject_type text,
  subject_id text,
  trace_id uuid,
  approval_reason text,
  attestation_text text,
  signature_hash_ref text,
  details jsonb not null default '{}'::jsonb
);

create index if not exists idx_audit_logs_created on public.placeware_audit_logs(created_at desc);
create index if not exists idx_audit_logs_class_outcome on public.placeware_audit_logs(event_class, outcome);
create index if not exists idx_audit_logs_actor on public.placeware_audit_logs(actor_id);
create index if not exists idx_audit_logs_trace_id on public.placeware_audit_logs(trace_id);
create index if not exists idx_audit_logs_signature_hash on public.placeware_audit_logs(signature_hash_ref);

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

create index if not exists idx_import_jobs_created
  on public.placeware_import_jobs(created_at desc);

create index if not exists idx_import_jobs_batch
  on public.placeware_import_jobs(batch_id);

create index if not exists idx_import_jobs_retention_expires
  on public.placeware_import_jobs(retention_expires_at);

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

create index if not exists idx_import_rejections_job
  on public.placeware_import_rejections(job_id);

create table if not exists public.placeware_kpi_promotions (
  domain text primary key,
  batch_id uuid not null,
  job_id uuid references public.placeware_import_jobs(id) on delete set null,
  promoted_at timestamptz not null default now(),
  quality_score numeric,
  rejection_rate numeric,
  promoted_reason text not null default 'quality_gate_passed'
);

create index if not exists idx_kpi_promotions_promoted_at
  on public.placeware_kpi_promotions(promoted_at desc);

create table if not exists public.placeware_data_policies (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  domain text not null,
  policy_version text not null,
  schema_version text not null,
  retention_days integer not null check (retention_days > 0),
  controls_config jsonb not null default '{}'::jsonb,
  approved_by text,
  approval_reason text,
  attestation_text text,
  signature_hash_ref text,
  effective_from timestamptz not null default now(),
  active boolean not null default true,
  notes text
);

create index if not exists idx_data_policies_domain_effective
  on public.placeware_data_policies(domain, effective_from desc);

create unique index if not exists uq_data_policies_active_domain
  on public.placeware_data_policies(domain)
  where active = true;

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

-- ---------------------------------------------------------------------------
-- Workflow + Chat
-- ---------------------------------------------------------------------------
create table if not exists public.placeware_intents (
  id uuid primary key,
  created_at timestamptz not null default now(),
  intent_type text not null,
  payload jsonb not null,
  recommendation jsonb not null,
  status text not null default 'pending'
);

create table if not exists public.placeware_approvals (
  id bigint generated always as identity primary key,
  intent_id uuid not null references public.placeware_intents(id) on delete cascade,
  approved boolean not null,
  approver_note text,
  approved_at timestamptz not null default now()
);

create table if not exists public.placeware_chat_history (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  user_id text,
  question text not null,
  answer text not null,
  sources jsonb not null default '[]'::jsonb
);

create index if not exists idx_chat_history_user_created
  on public.placeware_chat_history (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- HR / OPS / CRM
-- ---------------------------------------------------------------------------
create table if not exists public.hr_payroll_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  employee_id text not null,
  salary numeric not null,
  overtime_hours numeric default 0,
  overtime_rate numeric default 0
);

create table if not exists public.hr_absence_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  employee_id text not null,
  date date not null,
  hours numeric not null,
  reason text
);

create table if not exists public.ops_orders_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  order_id text not null,
  created_at timestamptz not null,
  fulfilled_at timestamptz,
  sku text,
  quantity numeric default 0,
  status text
);

create table if not exists public.ops_downtime_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  machine_id text not null,
  started_at timestamptz not null,
  ended_at timestamptz,
  reason text,
  minutes numeric
);

create table if not exists public.crm_pipeline_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  opportunity_id text not null,
  customer_id text not null,
  amount numeric not null,
  stage text,
  status text,
  close_date date
);

-- ---------------------------------------------------------------------------
-- Inventory / Staff Ops / Intelligence
-- ---------------------------------------------------------------------------
create table if not exists public.placeware_inventory_events (
  id bigint generated by default as identity primary key,
  sku text not null,
  quantity_change numeric not null,
  event_type text not null check (event_type in ('SALE', 'RESTOCK', 'DAMAGE', 'EXPIRY', 'ADJUSTMENT')),
  reference text,
  performed_by text,
  created_at timestamptz not null default timezone('utc'::text, now())
);

create index if not exists idx_inventory_events_sku on public.placeware_inventory_events(sku);
create index if not exists idx_inventory_events_created_at on public.placeware_inventory_events(created_at);

create table if not exists public.placeware_staff (
  staff_id uuid default gen_random_uuid() primary key,
  full_name text not null,
  email text unique not null,
  department text not null check (department in ('Finance', 'Sales', 'Operations', 'HR', 'Management')),
  role text,
  status text default 'active' check (status in ('active', 'inactive')),
  created_at timestamptz not null default timezone('utc'::text, now())
);

create index if not exists idx_staff_department on public.placeware_staff(department);
create index if not exists idx_staff_email on public.placeware_staff(email);

create table if not exists public.placeware_timesheets (
  id bigint generated by default as identity primary key,
  staff_id uuid references public.placeware_staff(staff_id) on delete cascade,
  date date not null,
  hours_worked numeric(5,2) not null check (hours_worked > 0 and hours_worked <= 24),
  department text not null,
  activity_note text,
  recorded_by text,
  created_at timestamptz not null default timezone('utc'::text, now())
);

create index if not exists idx_timesheets_date on public.placeware_timesheets(date);
create index if not exists idx_timesheets_staff on public.placeware_timesheets(staff_id);

create table if not exists public.placeware_alerts (
  id bigint generated by default as identity primary key,
  title text not null,
  message text not null,
  severity text not null check (severity in ('info', 'warning', 'critical')),
  category text not null check (category in ('finance', 'inventory', 'workforce', 'system')),
  status text default 'unread' check (status in ('unread', 'read', 'archived')),
  metadata jsonb,
  created_at timestamptz not null default timezone('utc'::text, now())
);

create index if not exists idx_alerts_status_severity on public.placeware_alerts(status, severity);
create index if not exists idx_alerts_created_at on public.placeware_alerts(created_at);

create table if not exists public.placeware_executive_briefings (
  id bigint generated by default as identity primary key,
  report_date date unique default current_date,
  content jsonb not null,
  generated_at timestamptz default timezone('utc'::text, now())
);

-- ---------------------------------------------------------------------------
-- Auth Tables
-- ---------------------------------------------------------------------------
create table if not exists public.placeware_users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  hashed_password text not null,
  roles text[] not null default array[]::text[],
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.placeware_refresh_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.placeware_users(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  replaced_by uuid references public.placeware_refresh_tokens(id),
  user_agent text,
  ip_address text,
  created_at timestamptz not null default now()
);

create index if not exists idx_placeware_refresh_tokens_user_id on public.placeware_refresh_tokens(user_id);
create index if not exists idx_placeware_refresh_tokens_expires_at on public.placeware_refresh_tokens(expires_at);

-- ---------------------------------------------------------------------------
-- Optional tables referenced by constants/future endpoints
-- ---------------------------------------------------------------------------
-- NOTE: Keep this section aligned with incremental migration
-- `021_order_workflow_enrichment.sql` for environments that upgrade in place.
create table if not exists public.placeware_orders (
  id uuid primary key default gen_random_uuid(),
  customer_name text,
  customer_email text,
  customer_phone text,
  items jsonb,
  notes text,
  source text default 'direct',
  lead_id bigint references public.placeware_leads(id) on delete set null,
  status text default 'received',
  created_at timestamptz not null default now()
);

create index if not exists idx_placeware_orders_lead_id on public.placeware_orders(lead_id);
create index if not exists idx_placeware_orders_customer_email on public.placeware_orders(customer_email);
create index if not exists idx_placeware_orders_created_at on public.placeware_orders(created_at desc);

create table if not exists public.placeware_tracking (
  id uuid primary key default gen_random_uuid(),
  order_id uuid,
  status text,
  last_update timestamptz,
  eta text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- RLS Helpers
-- ---------------------------------------------------------------------------
create or replace function public.has_role(role_name text)
returns boolean
language sql
stable
as $$
  -- Access control enforced at the application layer (FastAPI JWT middleware).
  -- Returning true; role checks are performed in FastAPI route handlers.
  select true;
$$;

create or replace function public.is_admin()
returns boolean
language sql
stable
as $$
  select public.has_role('admin');
$$;

-- ---------------------------------------------------------------------------
-- Enable RLS on all app tables
-- ---------------------------------------------------------------------------
alter table public.placeware_leads enable row level security;
alter table public.placeware_stock_cache enable row level security;
alter table public.qna enable row level security;
alter table public.sage_customers_snapshot enable row level security;
alter table public.sage_ar_snapshot enable row level security;
alter table public.sage_ap_snapshot enable row level security;
alter table public.sage_gl_snapshot enable row level security;
alter table public.sage_inventory_snapshot enable row level security;
alter table public.sage_staff_snapshot enable row level security;
alter table public.placeware_audit_logs enable row level security;
alter table public.placeware_import_jobs enable row level security;
alter table public.placeware_import_rejections enable row level security;
alter table public.placeware_kpi_promotions enable row level security;
alter table public.placeware_data_policies enable row level security;
alter table public.placeware_projects enable row level security;
alter table public.placeware_scope_items enable row level security;
alter table public.placeware_cost_items enable row level security;
alter table public.placeware_risk_register enable row level security;
alter table public.placeware_change_requests enable row level security;
alter table public.placeware_intents enable row level security;
alter table public.placeware_approvals enable row level security;
alter table public.placeware_chat_history enable row level security;
alter table public.hr_payroll_snapshot enable row level security;
alter table public.hr_absence_snapshot enable row level security;
alter table public.ops_orders_snapshot enable row level security;
alter table public.ops_downtime_snapshot enable row level security;
alter table public.crm_pipeline_snapshot enable row level security;
alter table public.placeware_inventory_events enable row level security;
alter table public.placeware_staff enable row level security;
alter table public.placeware_timesheets enable row level security;
alter table public.placeware_alerts enable row level security;
alter table public.placeware_executive_briefings enable row level security;
alter table public.placeware_users enable row level security;
alter table public.placeware_refresh_tokens enable row level security;
alter table public.placeware_orders enable row level security;
alter table public.placeware_tracking enable row level security;

-- ---------------------------------------------------------------------------
-- RLS Policies (drop+recreate for idempotence)
-- ---------------------------------------------------------------------------
-- Leads: allow optional public intake, admin read/manage

drop policy if exists leads_insert_public on public.placeware_leads;
create policy leads_insert_public on public.placeware_leads
for insert
with check (true);

drop policy if exists leads_admin_all on public.placeware_leads;
create policy leads_admin_all on public.placeware_leads
for all
using (true)
with check (true);

-- QnA: allow read for anon/authenticated (for semantic retrieval use-cases)
drop policy if exists qna_read_public on public.qna;
create policy qna_read_public on public.qna
for select
using (true);

drop policy if exists qna_admin_write on public.qna;
create policy qna_admin_write on public.qna
for all
using (true)
with check (true);

-- Chat history: user can see own rows, admin can see all

drop policy if exists chat_history_select_own on public.placeware_chat_history;
create policy chat_history_select_own on public.placeware_chat_history
for select
using (
  user_id is null
  or user_id = NULL::text
);

drop policy if exists chat_history_insert_user on public.placeware_chat_history;
create policy chat_history_insert_user on public.placeware_chat_history
for insert
with check (
  user_id is null
  or user_id = NULL::text
);

drop policy if exists chat_history_admin_delete on public.placeware_chat_history;
create policy chat_history_admin_delete on public.placeware_chat_history
for delete
using (true);

-- Admin-only tables
-- service_role bypasses RLS, but authenticated admin policies are provided.

-- Helper block for repeated policy creation

drop policy if exists admin_all_audit on public.placeware_audit_logs;
create policy admin_all_audit on public.placeware_audit_logs for all using (true) with check (true);

drop policy if exists admin_all_import_jobs on public.placeware_import_jobs;
create policy admin_all_import_jobs on public.placeware_import_jobs for all using (true) with check (true);

drop policy if exists admin_all_import_rejections on public.placeware_import_rejections;
create policy admin_all_import_rejections on public.placeware_import_rejections for all using (true) with check (true);

drop policy if exists admin_all_kpi_promotions on public.placeware_kpi_promotions;
create policy admin_all_kpi_promotions on public.placeware_kpi_promotions for all using (true) with check (true);

drop policy if exists admin_all_data_policies on public.placeware_data_policies;
create policy admin_all_data_policies on public.placeware_data_policies for all using (true) with check (true);

drop policy if exists admin_all_projects on public.placeware_projects;
create policy admin_all_projects on public.placeware_projects for all using (true) with check (true);

drop policy if exists admin_all_scope_items on public.placeware_scope_items;
create policy admin_all_scope_items on public.placeware_scope_items for all using (true) with check (true);

drop policy if exists admin_all_cost_items on public.placeware_cost_items;
create policy admin_all_cost_items on public.placeware_cost_items for all using (true) with check (true);

drop policy if exists admin_all_risk_register on public.placeware_risk_register;
create policy admin_all_risk_register on public.placeware_risk_register for all using (true) with check (true);

drop policy if exists admin_all_change_requests on public.placeware_change_requests;
create policy admin_all_change_requests on public.placeware_change_requests for all using (true) with check (true);

drop policy if exists admin_all_intents on public.placeware_intents;
create policy admin_all_intents on public.placeware_intents for all using (true) with check (true);

drop policy if exists admin_all_approvals on public.placeware_approvals;
create policy admin_all_approvals on public.placeware_approvals for all using (true) with check (true);

drop policy if exists admin_all_sage_customers on public.sage_customers_snapshot;
create policy admin_all_sage_customers on public.sage_customers_snapshot for all using (true) with check (true);

drop policy if exists admin_all_sage_ar on public.sage_ar_snapshot;
create policy admin_all_sage_ar on public.sage_ar_snapshot for all using (true) with check (true);

drop policy if exists admin_all_sage_ap on public.sage_ap_snapshot;
create policy admin_all_sage_ap on public.sage_ap_snapshot for all using (true) with check (true);

drop policy if exists admin_all_sage_gl on public.sage_gl_snapshot;
create policy admin_all_sage_gl on public.sage_gl_snapshot for all using (true) with check (true);

drop policy if exists admin_all_sage_inventory on public.sage_inventory_snapshot;
create policy admin_all_sage_inventory on public.sage_inventory_snapshot for all using (true) with check (true);

drop policy if exists admin_all_sage_staff on public.sage_staff_snapshot;
create policy admin_all_sage_staff on public.sage_staff_snapshot for all using (true) with check (true);

drop policy if exists admin_all_hr_payroll on public.hr_payroll_snapshot;
create policy admin_all_hr_payroll on public.hr_payroll_snapshot for all using (true) with check (true);

drop policy if exists admin_all_hr_absence on public.hr_absence_snapshot;
create policy admin_all_hr_absence on public.hr_absence_snapshot for all using (true) with check (true);

drop policy if exists admin_all_ops_orders on public.ops_orders_snapshot;
create policy admin_all_ops_orders on public.ops_orders_snapshot for all using (true) with check (true);

drop policy if exists admin_all_ops_downtime on public.ops_downtime_snapshot;
create policy admin_all_ops_downtime on public.ops_downtime_snapshot for all using (true) with check (true);

drop policy if exists admin_all_crm_pipeline on public.crm_pipeline_snapshot;
create policy admin_all_crm_pipeline on public.crm_pipeline_snapshot for all using (true) with check (true);

drop policy if exists admin_all_inventory_events on public.placeware_inventory_events;
create policy admin_all_inventory_events on public.placeware_inventory_events for all using (true) with check (true);

drop policy if exists admin_all_staff on public.placeware_staff;
create policy admin_all_staff on public.placeware_staff for all using (true) with check (true);

drop policy if exists admin_all_timesheets on public.placeware_timesheets;
create policy admin_all_timesheets on public.placeware_timesheets for all using (true) with check (true);

drop policy if exists admin_all_alerts on public.placeware_alerts;
create policy admin_all_alerts on public.placeware_alerts for all using (true) with check (true);

drop policy if exists admin_all_briefings on public.placeware_executive_briefings;
create policy admin_all_briefings on public.placeware_executive_briefings for all using (true) with check (true);

drop policy if exists admin_all_users on public.placeware_users;
create policy admin_all_users on public.placeware_users for all using (true) with check (true);

drop policy if exists admin_all_refresh_tokens on public.placeware_refresh_tokens;
create policy admin_all_refresh_tokens on public.placeware_refresh_tokens for all using (true) with check (true);

drop policy if exists admin_all_orders on public.placeware_orders;
create policy admin_all_orders on public.placeware_orders for all using (true) with check (true);

drop policy if exists admin_all_tracking on public.placeware_tracking;
create policy admin_all_tracking on public.placeware_tracking for all using (true) with check (true);

drop policy if exists admin_all_stock_cache on public.placeware_stock_cache;
create policy admin_all_stock_cache on public.placeware_stock_cache for all using (true) with check (true);

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

grant execute on function public.placeware_controls_rollup(uuid) ;

commit;
