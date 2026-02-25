-- Migration 024: Add walk-in metadata columns to orders

alter table if exists public.placeware_orders
  add column if not exists walk_in_agent text,
  add column if not exists walk_in_location text;

create index if not exists idx_placeware_orders_walkin_agent on public.placeware_orders(walk_in_agent);
create index if not exists idx_placeware_orders_walkin_location on public.placeware_orders(walk_in_location);
