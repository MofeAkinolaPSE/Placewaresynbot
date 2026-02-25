-- Migration 022: Procurement/Import agent tables and lifecycle audit trail

create table if not exists public.placeware_procurement_shipments (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  shipment_ref text not null,
  supplier_name text not null,
  status text not null check (status in ('in_transit', 'at_port', 'under_clearance', 'released', 'delivered_to_warehouse')),
  expected_arrival_date date,
  arrived_port_at timestamptz,
  clearance_started_at timestamptz,
  released_at timestamptz,
  delivered_at timestamptz,
  clearance_sla_days integer not null default 5 check (clearance_sla_days > 0 and clearance_sla_days <= 90),
  estimated_delay_cost numeric,
  currency text not null default 'NGN',
  last_risk_level text,
  last_risk_reason text,
  metadata jsonb not null default '{}'::jsonb,
  unique (shipment_ref)
);

create index if not exists idx_procurement_shipments_status_created
  on public.placeware_procurement_shipments(status, created_at desc);

create index if not exists idx_procurement_shipments_supplier
  on public.placeware_procurement_shipments(supplier_name, created_at desc);

create index if not exists idx_procurement_shipments_clearance_started
  on public.placeware_procurement_shipments(clearance_started_at)
  where clearance_started_at is not null;

create table if not exists public.placeware_procurement_shipment_events (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  shipment_id uuid not null references public.placeware_procurement_shipments(id) on delete cascade,
  from_status text,
  to_status text not null,
  reason text,
  actor_id text,
  details jsonb not null default '{}'::jsonb
);

create index if not exists idx_procurement_shipment_events_shipment_created
  on public.placeware_procurement_shipment_events(shipment_id, created_at desc);
