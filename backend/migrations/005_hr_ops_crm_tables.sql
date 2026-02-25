-- Snapshot tables for HR, Operations, and CRM ingestion

-- HR payroll and absences
create table if not exists hr_payroll_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  employee_id text not null,
  salary numeric not null,
  overtime_hours numeric default 0,
  overtime_rate numeric default 0
);

create table if not exists hr_absence_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  employee_id text not null,
  date date not null,
  hours numeric not null,
  reason text
);

-- Operations: orders and downtime
create table if not exists ops_orders_snapshot (
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

create table if not exists ops_downtime_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  machine_id text not null,
  started_at timestamptz not null,
  ended_at timestamptz,
  reason text,
  minutes numeric
);

-- CRM Pipeline
create table if not exists crm_pipeline_snapshot (
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
