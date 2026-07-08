-- Migration 092: GL account summary snapshot table (beginning/ending balances)
-- Ingests: Gl account summaru.xlsx (Financial Statements folder)

create table if not exists public.sage_gl_account_summary_snapshot (
  id                bigint generated always as identity primary key,
  batch_id          uuid        not null,
  imported_at       timestamptz not null,
  account_code      text        not null,
  account_name      text,
  beginning_balance numeric,
  debit_change      numeric,
  credit_change     numeric,
  net_change        numeric,
  ending_balance    numeric
);

create index if not exists sage_gl_acct_summary_batch_idx on public.sage_gl_account_summary_snapshot (batch_id);
create index if not exists sage_gl_acct_summary_acct_idx  on public.sage_gl_account_summary_snapshot (account_code);

alter table public.sage_gl_account_summary_snapshot enable row level security;

drop policy if exists admin_all_sage_gl_summary on public.sage_gl_account_summary_snapshot;
create policy admin_all_sage_gl_summary on public.sage_gl_account_summary_snapshot
  for all using (true) with check (true);

drop policy if exists read_sage_gl_summary on public.sage_gl_account_summary_snapshot;
create policy read_sage_gl_summary on public.sage_gl_account_summary_snapshot
  for select using (true);
