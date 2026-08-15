-- 110_frontdesk_invoice_template_fields.sql
--
-- Adds the fields needed to match the real Placeware paper invoice template
-- (Bill To/Ship To, Customer PO, Payment Terms, Shipping Method, Due Date,
-- Tax) — the printed template previously carried none of these. See
-- printInvoice() in SynbotUI/client/pages/Frontdesk.tsx for the consumer.
--
-- Purely additive: 7 nullable/defaulted columns on frontdesk_invoices.
-- Existing rows are unaffected; the print template falls back to "—"/
-- "Same as Bill To"/"Pending dispatch" for invoices created before this
-- migration (no backfill attempted -- no reliable source data exists for
-- historical rows).
--
-- Idempotent: safe to re-run.

ALTER TABLE frontdesk_invoices
    ADD COLUMN IF NOT EXISTS billing_address   TEXT,
    ADD COLUMN IF NOT EXISTS shipping_address  TEXT,
    ADD COLUMN IF NOT EXISTS customer_po       TEXT,
    ADD COLUMN IF NOT EXISTS payment_terms     TEXT NOT NULL DEFAULT 'Due on Receipt',
    ADD COLUMN IF NOT EXISTS due_date          DATE,
    ADD COLUMN IF NOT EXISTS shipping_method   TEXT,
    ADD COLUMN IF NOT EXISTS tax_amount        NUMERIC(14,2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN frontdesk_invoices.billing_address IS
    'Free-text, always manually entered -- customers.contact_details never has an address key populated anywhere in this codebase, so there is no autofill source.';
COMMENT ON COLUMN frontdesk_invoices.shipping_address IS
    'Same as billing_address if not diverged (frontend shows "Same as Bill To" instead of duplicating text when empty).';
COMMENT ON COLUMN frontdesk_invoices.due_date IS
    'Computed once at creation time from payment_terms and stored, not recomputed on read -- an issued invoice''s due date must never move if the payment-terms taxonomy changes later.';
COMMENT ON COLUMN frontdesk_invoices.tax_amount IS
    'Separate from total_amount (which stays "sum of line items" -- too many other modules already read it that way to redefine). Total Invoice Amount = total_amount + tax_amount, computed at print time only.';
