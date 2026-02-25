-- Migration 021: Order workflow enrichment for lead-to-order lifecycle

alter table if exists public.placeware_orders
  add column if not exists source text default 'direct';

alter table if exists public.placeware_orders
  add column if not exists lead_id bigint references public.placeware_leads(id) on delete set null;

create index if not exists idx_placeware_orders_lead_id on public.placeware_orders(lead_id);
create index if not exists idx_placeware_orders_customer_email on public.placeware_orders(customer_email);
create index if not exists idx_placeware_orders_created_at on public.placeware_orders(created_at desc);
