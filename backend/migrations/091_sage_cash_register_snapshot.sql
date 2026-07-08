-- Migration 091: Cash account register snapshot table
-- Ingests: Cash ACcount Register.xlsx (General Ledger folder)
--          Accounts register.xlsx (Account Reconciliation folder)

create table if not exists public.sage_cash_register_snapshot (
  id              bigint generated always as identity primary key,
  batch_id        uuid        not null,
  imported_at     timestamptz not null,
  txn_date        date,
  trans_no        text,
  txn_type        text,
  description     text,
  reference       text,
  payment_amount  numeric     not null default 0,
  receipt_amount  numeric     not null default 0,
  running_balance numeric,
  source_file     text
);

create index if not exists sage_cash_register_batch_idx on public.sage_cash_register_snapshot (batch_id);
create index if not exists sage_cash_register_date_idx  on public.sage_cash_register_snapshot (txn_date);

alter table public.sage_cash_register_snapshot enable row level security;

drop policy if exists admin_all_sage_cash_register on public.sage_cash_register_snapshot;
create policy admin_all_sage_cash_register on public.sage_cash_register_snapshot
  for all using (true) with check (true);

drop policy if exists read_sage_cash_register on public.sage_cash_register_snapshot;
create policy read_sage_cash_register on public.sage_cash_register_snapshot
  for select using (true);
