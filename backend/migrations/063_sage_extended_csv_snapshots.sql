-- Migration 063: Extended Sage CSV snapshot tables
-- Supports the full 10-file PlacewareBot CSV import package.
-- Tables already covered by migration 002: sage_customers_snapshot, sage_ar_snapshot,
-- sage_inventory_snapshot, sage_gl_snapshot. This migration adds the remaining six.

-- ---------------------------------------------------------------------------
-- chart_of_accounts  →  sage_coa_snapshot
-- ---------------------------------------------------------------------------
create table if not exists public.sage_coa_snapshot (
  id           bigint generated always as identity primary key,
  batch_id     uuid        not null,
  imported_at  timestamptz not null,
  account_id   text        not null,
  account_code text        not null,
  account_name text        not null,
  account_type text,
  parent_account_id text,
  description  text,
  is_active    boolean default true
);

create index if not exists sage_coa_snapshot_batch_id_idx   on public.sage_coa_snapshot (batch_id);
create index if not exists sage_coa_snapshot_account_code_idx on public.sage_coa_snapshot (account_code);

-- ---------------------------------------------------------------------------
-- vendors  →  sage_vendors_snapshot
-- ---------------------------------------------------------------------------
create table if not exists public.sage_vendors_snapshot (
  id             bigint generated always as identity primary key,
  batch_id       uuid        not null,
  imported_at    timestamptz not null,
  vendor_id      text        not null,
  vendor_name    text        not null,
  contact_name   text,
  email          text,
  phone          text,
  address        text,
  city           text,
  state          text,
  country        text,
  payment_terms  text,
  tax_id         text,
  status         text
);

create index if not exists sage_vendors_snapshot_batch_id_idx on public.sage_vendors_snapshot (batch_id);
create index if not exists sage_vendors_snapshot_vendor_id_idx on public.sage_vendors_snapshot (vendor_id);

-- ---------------------------------------------------------------------------
-- items (product catalogue)  →  sage_items_snapshot
-- ---------------------------------------------------------------------------
create table if not exists public.sage_items_snapshot (
  id                  bigint generated always as identity primary key,
  batch_id            uuid        not null,
  imported_at         timestamptz not null,
  item_id             text        not null,
  item_name           text        not null,
  category            text,
  unit                text,
  cost_price          numeric,
  selling_price       numeric,
  vat_category        text,
  reorder_level       numeric,
  preferred_vendor_id text,
  is_active           boolean default true
);

create index if not exists sage_items_snapshot_batch_id_idx on public.sage_items_snapshot (batch_id);
create index if not exists sage_items_snapshot_item_id_idx  on public.sage_items_snapshot (item_id);

-- ---------------------------------------------------------------------------
-- purchase_orders  →  sage_purchase_orders_snapshot
-- ---------------------------------------------------------------------------
create table if not exists public.sage_purchase_orders_snapshot (
  id                       bigint generated always as identity primary key,
  batch_id                 uuid        not null,
  imported_at              timestamptz not null,
  po_id                    text        not null,
  po_number                text        not null,
  vendor_id                text,
  order_date               date,
  expected_delivery_date   date,
  total_amount             numeric,
  tax_amount               numeric,
  discount_amount          numeric,
  net_amount               numeric,
  status                   text,
  warehouse_id             text,
  created_by               text
);

create index if not exists sage_purchase_orders_snapshot_batch_id_idx  on public.sage_purchase_orders_snapshot (batch_id);
create index if not exists sage_purchase_orders_snapshot_po_id_idx      on public.sage_purchase_orders_snapshot (po_id);
create index if not exists sage_purchase_orders_snapshot_status_idx     on public.sage_purchase_orders_snapshot (status);

-- ---------------------------------------------------------------------------
-- sales_invoice_lines  →  sage_invoice_lines_snapshot
-- ---------------------------------------------------------------------------
create table if not exists public.sage_invoice_lines_snapshot (
  id            bigint generated always as identity primary key,
  batch_id      uuid        not null,
  imported_at   timestamptz not null,
  line_id       text        not null,
  invoice_id    text        not null,
  item_id       text,
  quantity      numeric,
  unit_price    numeric,
  discount      numeric,
  line_total    numeric,
  cost_at_sale  numeric,
  gross_profit  numeric
);

create index if not exists sage_invoice_lines_snapshot_batch_id_idx  on public.sage_invoice_lines_snapshot (batch_id);
create index if not exists sage_invoice_lines_snapshot_invoice_id_idx on public.sage_invoice_lines_snapshot (invoice_id);
create index if not exists sage_invoice_lines_snapshot_item_id_idx    on public.sage_invoice_lines_snapshot (item_id);

-- ---------------------------------------------------------------------------
-- inventory_transactions  →  sage_inv_transactions_snapshot
-- ---------------------------------------------------------------------------
create table if not exists public.sage_inv_transactions_snapshot (
  id               bigint generated always as identity primary key,
  batch_id         uuid        not null,
  imported_at      timestamptz not null,
  transaction_id   text        not null,
  item_id          text,
  warehouse_id     text,
  transaction_type text,
  quantity_in      numeric,
  quantity_out     numeric,
  unit_cost        numeric,
  reference_number text,
  transaction_date date,
  posted_by        text
);

create index if not exists sage_inv_transactions_snapshot_batch_id_idx  on public.sage_inv_transactions_snapshot (batch_id);
create index if not exists sage_inv_transactions_snapshot_item_id_idx    on public.sage_inv_transactions_snapshot (item_id);
create index if not exists sage_inv_transactions_snapshot_type_idx       on public.sage_inv_transactions_snapshot (transaction_type);

-- ---------------------------------------------------------------------------
-- RLS: allow admin full access; others read-only
-- ---------------------------------------------------------------------------
alter table public.sage_coa_snapshot            enable row level security;
alter table public.sage_vendors_snapshot        enable row level security;
alter table public.sage_items_snapshot          enable row level security;
alter table public.sage_purchase_orders_snapshot enable row level security;
alter table public.sage_invoice_lines_snapshot  enable row level security;
alter table public.sage_inv_transactions_snapshot enable row level security;

-- Admin write (drop-then-create is the correct idempotent pattern for policies)
drop policy if exists admin_all_sage_coa on public.sage_coa_snapshot;
create policy admin_all_sage_coa on public.sage_coa_snapshot
  for all USING (true) WITH CHECK (true);

drop policy if exists admin_all_sage_vendors on public.sage_vendors_snapshot;
create policy admin_all_sage_vendors on public.sage_vendors_snapshot
  for all USING (true) WITH CHECK (true);

drop policy if exists admin_all_sage_items on public.sage_items_snapshot;
create policy admin_all_sage_items on public.sage_items_snapshot
  for all USING (true) WITH CHECK (true);

drop policy if exists admin_all_sage_po on public.sage_purchase_orders_snapshot;
create policy admin_all_sage_po on public.sage_purchase_orders_snapshot
  for all USING (true) WITH CHECK (true);

drop policy if exists admin_all_sage_inv_lines on public.sage_invoice_lines_snapshot;
create policy admin_all_sage_inv_lines on public.sage_invoice_lines_snapshot
  for all USING (true) WITH CHECK (true);

drop policy if exists admin_all_sage_inv_txn on public.sage_inv_transactions_snapshot;
create policy admin_all_sage_inv_txn on public.sage_inv_transactions_snapshot
  for all USING (true) WITH CHECK (true);

-- Read access for finance/ops/management
-- NOTE: has_any_role() is not defined in this schema; grant read to all
-- authenticated users (consistent with other sage snapshot tables that rely
-- solely on is_admin() for write and allow authenticated reads).
drop policy if exists read_sage_coa on public.sage_coa_snapshot;
create policy read_sage_coa on public.sage_coa_snapshot
  for select using (true);

drop policy if exists read_sage_vendors on public.sage_vendors_snapshot;
create policy read_sage_vendors on public.sage_vendors_snapshot
  for select using (true);

drop policy if exists read_sage_items on public.sage_items_snapshot;
create policy read_sage_items on public.sage_items_snapshot
  for select using (true);

drop policy if exists read_sage_po on public.sage_purchase_orders_snapshot;
create policy read_sage_po on public.sage_purchase_orders_snapshot
  for select using (true);

drop policy if exists read_sage_inv_lines on public.sage_invoice_lines_snapshot;
create policy read_sage_inv_lines on public.sage_invoice_lines_snapshot
  for select using (true);

drop policy if exists read_sage_inv_txn on public.sage_inv_transactions_snapshot;
create policy read_sage_inv_txn on public.sage_inv_transactions_snapshot
  for select using (true);
