-- Workflow intent + approval append-only tables

create table if not exists placeware_intents (
  id uuid primary key,
  created_at timestamptz not null default now(),
  intent_type text not null,
  payload jsonb not null,
  recommendation jsonb not null,
  status text not null default 'pending'
);

create table if not exists placeware_approvals (
  id bigint generated always as identity primary key,
  intent_id uuid not null,
  approved boolean not null,
  approver_note text,
  approved_at timestamptz not null default now()
);
