-- 8 Oct 2026: recalls can be voided (opened by mistake), and Sage-era bank / supplier history is
-- listed beside ACE Books documents (payments, vouchers), which needs a fast lookup of a Sage
-- transaction in the customer / vendor ledgers.

ALTER TABLE fin_recalls DROP CONSTRAINT IF EXISTS fin_recalls_status_check;
ALTER TABLE fin_recalls ADD CONSTRAINT fin_recalls_status_check CHECK (status = ANY (ARRAY['OPEN', 'CLOSED', 'VOID']));
ALTER TABLE fin_recalls ADD COLUMN IF NOT EXISTS void_reason text;
ALTER TABLE fin_recalls ADD COLUMN IF NOT EXISTS voided_by text;
ALTER TABLE fin_recalls ADD COLUMN IF NOT EXISTS voided_at timestamptz;

ALTER TABLE recall_cases DROP CONSTRAINT IF EXISTS recall_cases_status_check;
ALTER TABLE recall_cases ADD CONSTRAINT recall_cases_status_check
    CHECK (status = ANY (ARRAY['initiated', 'in_progress', 'completed', 'closed', 'voided']));

CREATE INDEX IF NOT EXISTS idx_fin_sage_pl_trans_date ON fin_sage_party_ledger (legal_entity_id, trans_no, txn_date);
