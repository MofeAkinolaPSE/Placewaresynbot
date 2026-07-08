-- Migration 089: Bank reconciliation tracking
-- Tracks when each Sage 50 reconciliation snapshot was last imported and
-- allows staff to manually log completed reconciliations via the Placeware UI.
-- Reports 1, 4, 5, 6 from the Account Reconciliation category are point-in-time
-- snapshots (outstanding items change each cycle); reports 2 & 3 are historical.
-- This table is the source of truth for staleness checks used by Ace and the UI.

create table if not exists public.reconciliation_tracking (
  id                uuid        primary key default gen_random_uuid(),
  account_code      text        not null,
  account_name      text,
  -- Which Sage report this row represents
  snapshot_type     text        not null
    check (snapshot_type in (
      'account_reconciliation',   -- report 1: last-reconciliation summary
      'account_register',         -- report 2: historical, append-only
      'bank_deposit_report',      -- report 3: historical, append-only
      'deposits_in_transit',      -- report 4: point-in-time, overwrite
      'other_outstanding_items',  -- report 5: point-in-time, overwrite
      'outstanding_checks'        -- report 6: point-in-time, overwrite
    )),
  -- Whether the row was imported from a Sage export or entered manually via UI
  entry_method      text        not null default 'sage_export'
    check (entry_method in ('sage_export', 'manual')),
  -- Period this reconciliation covers, e.g. '2026-06'
  reconciled_period text,
  -- Key balances from the reconciliation
  gl_balance        numeric(14, 2),
  bank_balance      numeric(14, 2),
  -- difference = gl_balance - bank_balance; 0 means fully reconciled
  difference        numeric(14, 2) generated always as (
    case when gl_balance is not null and bank_balance is not null
         then gl_balance - bank_balance
         else null end
  ) stored,
  outstanding_count integer,     -- number of outstanding items (for reports 4-6)
  outstanding_total numeric(14, 2),
  -- Audit fields
  last_imported_at  timestamptz, -- when the Sage export file was last ingested
  logged_by         text,
  notes             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- One active row per account+type combination (upsert target)
create unique index if not exists recon_tracking_account_type_uidx
  on public.reconciliation_tracking (account_code, snapshot_type);

create index if not exists recon_tracking_period_idx
  on public.reconciliation_tracking (reconciled_period);

create index if not exists recon_tracking_imported_at_idx
  on public.reconciliation_tracking (last_imported_at);

-- Auto-update updated_at
create or replace function public.set_recon_tracking_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists recon_tracking_updated_at on public.reconciliation_tracking;
create trigger recon_tracking_updated_at
  before update on public.reconciliation_tracking
  for each row execute function public.set_recon_tracking_updated_at();

-- RLS
alter table public.reconciliation_tracking enable row level security;

drop policy if exists recon_tracking_admin_all on public.reconciliation_tracking;
create policy recon_tracking_admin_all on public.reconciliation_tracking
  for all using (true) with check (true);

drop policy if exists recon_tracking_finance_read on public.reconciliation_tracking;
create policy recon_tracking_finance_read on public.reconciliation_tracking
  for select using (true);
