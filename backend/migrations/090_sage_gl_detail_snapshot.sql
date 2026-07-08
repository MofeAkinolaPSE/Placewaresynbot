-- Migration 090: Transaction-level General Ledger snapshot table
-- Ingests: GEneral Ledger.xlsx, General Journal.xlsx, Sales Journal.xlsx,
--          Cash receipts journal.xlsx, Cost of goods sold journal.xlsx

create table if not exists public.sage_gl_detail_snapshot (
  id              bigint generated always as identity primary key,
  batch_id        uuid        not null,
  imported_at     timestamptz not null,
  account_code    text        not null,
  account_name    text,
  txn_date        date,
  reference       text,
  journal_type    text,
  description     text,
  debit           numeric     not null default 0,
  credit          numeric     not null default 0,
  running_balance numeric,
  source_file     text
);

create index if not exists sage_gl_detail_batch_idx on public.sage_gl_detail_snapshot (batch_id);
create index if not exists sage_gl_detail_date_idx  on public.sage_gl_detail_snapshot (txn_date);
create index if not exists sage_gl_detail_acct_idx  on public.sage_gl_detail_snapshot (account_code);

alter table public.sage_gl_detail_snapshot enable row level security;

drop policy if exists admin_all_sage_gl_detail on public.sage_gl_detail_snapshot;
create policy admin_all_sage_gl_detail on public.sage_gl_detail_snapshot
  for all using (true) with check (true);

drop policy if exists read_sage_gl_detail on public.sage_gl_detail_snapshot;
create policy read_sage_gl_detail on public.sage_gl_detail_snapshot
  for select using (true);
