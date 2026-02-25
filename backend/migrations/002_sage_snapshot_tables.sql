-- Append-only snapshot tables for Sage adapter

create table if not exists sage_customers_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  customer_id text not null,
  name text not null,
  email text,
  phone text,
  status text
);

create table if not exists sage_ar_snapshot (
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

create table if not exists sage_ap_snapshot (
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

create table if not exists sage_gl_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  period text not null,
  account_code text not null,
  account_name text not null,
  debit numeric not null,
  credit numeric not null
);

create table if not exists sage_inventory_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  sku text not null,
  name text not null,
  quantity numeric not null,
  unit_cost numeric,
  valuation numeric,
  updated_at timestamptz
);

create table if not exists placeware_audit_logs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  event_type text not null,
  details jsonb not null
);
