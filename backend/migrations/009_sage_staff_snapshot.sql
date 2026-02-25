-- Append-only snapshot table for Sage staff
create table if not exists sage_staff_snapshot (
  id bigint generated always as identity primary key,
  batch_id uuid not null,
  imported_at timestamptz not null,
  staff_id text not null,
  full_name text not null,
  email text,
  department text,
  role text,
  status text
);
