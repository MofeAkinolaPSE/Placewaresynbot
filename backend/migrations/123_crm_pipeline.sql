-- 123: CRM on real data.
--
-- Pipeline stages become  new -> qualified -> proposal -> won | lost.
-- "proposal" covers proposal, negotiation and payment-plan discussion (payment terms are a field
-- on the deal, not a stage). A lead links to the customer it became (customers is the same
-- master ACE Books invoices), so a lead is won automatically when that customer's first ACE Books
-- invoice is posted.
--
-- Clean-up (archived, not deleted):
--   * 155 "won" leads were copies of Sage customers (source 'sage_import', value 0) - they are
--     customers, not deals, and made the win rate 96%.
--   * 1,780 lead-finder "prospects" were copies of our own Sage customers, 12 were mock places.
--     The lead finder now shows only what a rep searches for and the prospects the team works.

-- leads.stage is the crm_stage enum; 'archived' parks rows that are not deals.
-- (ADD VALUE must be committed before it is used - psql -f runs statements in autocommit.)
ALTER TYPE crm_stage ADD VALUE IF NOT EXISTS 'archived';

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS customer_id      bigint,
    ADD COLUMN IF NOT EXISTS prospect_id      uuid,
    ADD COLUMN IF NOT EXISTS stage_changed_at timestamptz,
    ADD COLUMN IF NOT EXISTS won_at           timestamptz,
    ADD COLUMN IF NOT EXISTS lost_at          timestamptz,
    ADD COLUMN IF NOT EXISTS lost_reason      text;

UPDATE leads SET stage = 'proposal' WHERE stage IN ('negotiation', 'payment_plan');
UPDATE leads SET stage = 'archived', metadata = COALESCE(metadata, '{}'::jsonb) || '{"archived_reason": "Sage customer copied into the pipeline; not a deal"}'::jsonb
 WHERE source = 'sage_import' AND stage <> 'archived';
UPDATE leads SET stage_changed_at = COALESCE(stage_changed_at, updated_at, created_at);

CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads (stage);
CREATE INDEX IF NOT EXISTS idx_leads_customer ON leads (customer_id);

ALTER TABLE crm_prospects DROP CONSTRAINT IF EXISTS crm_prospects_status_check;
ALTER TABLE crm_prospects ADD CONSTRAINT crm_prospects_status_check CHECK (status IN (
    'sourced', 'enriched', 'scored', 'saved', 'contacted', 'not_interested', 'converted', 'archived'));
ALTER TABLE crm_prospects
    ADD COLUMN IF NOT EXISTS distance_m    numeric,
    ADD COLUMN IF NOT EXISTS last_note     text,
    ADD COLUMN IF NOT EXISTS contacted_at  timestamptz,
    ADD COLUMN IF NOT EXISTS customer_id   bigint;

UPDATE crm_prospects SET status = 'archived' WHERE source IN ('sage_import', 'mock') AND status <> 'archived';

-- Interaction log carries stage moves too, so the weekly report can show them.
ALTER TABLE crm_interaction_log ADD COLUMN IF NOT EXISTS customer_id bigint;
ALTER TABLE crm_follow_up_reminders ADD COLUMN IF NOT EXISTS title text;

-- Stage moves and lead creation are logged as activity (weekly report, lead timeline).
ALTER TABLE crm_interaction_log DROP CONSTRAINT IF EXISTS crm_interaction_log_interaction_type_check;
ALTER TABLE crm_interaction_log ADD CONSTRAINT crm_interaction_log_interaction_type_check CHECK (interaction_type IN (
    'call', 'visit', 'site_visit', 'demo', 'email', 'whatsapp', 'meeting', 'note', 'stage_change', 'created'));

-- Calls and visits can be logged against a customer without a deal.
ALTER TABLE crm_interaction_log ALTER COLUMN lead_id DROP NOT NULL;
ALTER TABLE crm_interaction_log DROP CONSTRAINT IF EXISTS crm_interaction_log_subject_check;
ALTER TABLE crm_interaction_log ADD CONSTRAINT crm_interaction_log_subject_check CHECK (lead_id IS NOT NULL OR customer_id IS NOT NULL);
