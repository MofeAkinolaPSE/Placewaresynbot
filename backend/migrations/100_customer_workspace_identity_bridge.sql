-- 100_customer_workspace_identity_bridge.sql
--
-- Links Frontdesk walk-in intake to the CRM `customers` registry so the
-- Centralized Customer Workspace can search a customer once and raise a
-- request against their real customer_id, instead of the free-text-only
-- identity Frontdesk has used until now. Prior to this migration there was
-- no shared key between `customers` (CRM/Sage-bridged), `frontdesk_walk_ins`
-- (free-text customer_name/contact_phone only), and the Sage silver view
-- `v_customers` — three genuinely disconnected identity systems.
--
-- Purely additive: one nullable FK column + one index. No existing row's
-- meaning changes. Not backfilled — see column comment below for why.
--
-- Idempotent: safe to re-run.

ALTER TABLE frontdesk_walk_ins
    ADD COLUMN IF NOT EXISTS customer_id BIGINT REFERENCES customers(id) ON DELETE SET NULL;

COMMENT ON COLUMN frontdesk_walk_ins.customer_id IS
    'Optional link to customers.id (CRM/Sage-bridged identity). NULL for historical/free-text walk-ins and genuinely new/unregistered customers. Populated going forward by POST /frontdesk/customers/{id}/quick-request (Centralized Customer Workspace). Not backfilled by this migration -- no reliable name/phone match exists between historical frontdesk_walk_ins rows (free-text customer_name/contact_phone, no normalization) and customers (contact_details->>''phone'', also unnormalized JSONB).';

CREATE INDEX IF NOT EXISTS idx_fd_walk_ins_customer_id
    ON frontdesk_walk_ins (customer_id);
