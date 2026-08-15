-- 099_frontdesk_delivery_handoff.sql
--
-- Connects the Frontdesk walk-in workflow to the (previously unwired)
-- Logistics module. A finance-approved invoice can now be handed off to
-- Logistics via POST /frontdesk/invoices/{id}/send-for-delivery, which
-- creates a real row in `deliveries` (backend/src/routers/logistics.py)
-- directly (service-to-service — logistics.py's own POST /logistics/deliveries
-- endpoint is `ops`-role-gated, and `finance` does not implicitly satisfy
-- `ops` under this app's role model, so the handoff writes to the table
-- itself rather than calling that endpoint over HTTP).
--
-- Purely additive: two nullable columns on `deliveries` for provenance,
-- two nullable columns on `frontdesk_invoices` for the reverse link, and
-- one CHECK-constraint extension to allow the new terminal status
-- 'dispatched'. Nothing existing is altered in meaning — pre-existing rows
-- are unaffected (all new columns are nullable / no default required).
--
-- Idempotent: safe to re-run.

-- ── Provenance columns on deliveries ────────────────────────────────────────
-- No column existed to tag which system/record a delivery originated from.
-- Kept generic (not "frontdesk_invoice_id") since other future callers
-- (e.g. Sales) may want to create deliveries too.
ALTER TABLE deliveries
    ADD COLUMN IF NOT EXISTS source          TEXT,
    ADD COLUMN IF NOT EXISTS source_ref_id   UUID;

COMMENT ON COLUMN deliveries.source IS
    'Originating system/flow, e.g. ''frontdesk_walk_in''. NULL for deliveries created the old way (LogisticsMonitor.tsx''s manual form).';
COMMENT ON COLUMN deliveries.source_ref_id IS
    'ID of the originating record in the source system (e.g. frontdesk_invoices.id when source=''frontdesk_walk_in'').';

CREATE INDEX IF NOT EXISTS idx_deliveries_source_ref
    ON deliveries (source, source_ref_id);

-- ── Reverse link + new terminal status on frontdesk_invoices ───────────────
ALTER TABLE frontdesk_invoices
    ADD COLUMN IF NOT EXISTS delivery_id    UUID,
    ADD COLUMN IF NOT EXISTS dispatched_at  TIMESTAMPTZ;

COMMENT ON COLUMN frontdesk_invoices.delivery_id IS
    'References deliveries.id once sent for delivery. No FK constraint — deliveries is owned by a separate module (logistics.py), matching this schema''s existing soft-relationship convention.';

-- Postgres has no ALTER CONSTRAINT for CHECK conditions — drop and recreate.
-- Auto-generated name confirmed from migration 082's unnamed inline CHECK.
ALTER TABLE frontdesk_invoices
    DROP CONSTRAINT IF EXISTS frontdesk_invoices_status_check;

ALTER TABLE frontdesk_invoices
    ADD CONSTRAINT frontdesk_invoices_status_check
    CHECK (status IN (
        'draft', 'qc_pending', 'qc_passed', 'qc_failed',
        'finance_pending', 'finance_approved', 'finance_rejected',
        'completed', 'cancelled', 'dispatched'
    ));
