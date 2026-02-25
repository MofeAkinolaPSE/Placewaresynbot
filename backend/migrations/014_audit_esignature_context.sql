-- Add explicit e-signature context for high-risk audit events
begin;

alter table if exists public.placeware_audit_logs
  add column if not exists approval_reason text,
  add column if not exists attestation_text text,
  add column if not exists signature_hash_ref text;

create index if not exists idx_audit_logs_signature_hash on public.placeware_audit_logs(signature_hash_ref);

commit;
