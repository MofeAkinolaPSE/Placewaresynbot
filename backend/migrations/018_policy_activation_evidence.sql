-- Stage 4 Pass E: policy activation evidence fields
begin;

alter table if exists public.placeware_data_policies
  add column if not exists approved_by text,
  add column if not exists approval_reason text,
  add column if not exists attestation_text text,
  add column if not exists signature_hash_ref text;

commit;
