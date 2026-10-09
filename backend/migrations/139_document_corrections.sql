-- 9 Oct 2026: correcting posted documents without editing posted history.
--  * An invoice can take more items after posting (the customer adds to the order before paying):
--    each addition is its own journal on the same invoice, listed here so a void reverses it too.
--  * A receipt or a voucher posted with a mistake is corrected: the wrong one is voided (reversed,
--    unapplied) and the right one posted in the same step; the two point at each other.

CREATE TABLE IF NOT EXISTS fin_invoice_amendments (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id    uuid NOT NULL REFERENCES fin_sales_invoices(id) ON DELETE CASCADE,
    journal_id    uuid NOT NULL,
    amend_date    date NOT NULL,
    added_total   numeric(20,2) NOT NULL,
    line_from     integer NOT NULL,
    line_to       integer NOT NULL,
    reason        text NOT NULL,
    reversed      boolean NOT NULL DEFAULT false,
    created_by    text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_amendments_invoice ON fin_invoice_amendments (invoice_id);

ALTER TABLE fin_customer_receipts ADD COLUMN IF NOT EXISTS replaces_id uuid;
ALTER TABLE fin_customer_receipts ADD COLUMN IF NOT EXISTS replaced_by_id uuid;
ALTER TABLE fin_cash_vouchers     ADD COLUMN IF NOT EXISTS replaces_id uuid;
ALTER TABLE fin_cash_vouchers     ADD COLUMN IF NOT EXISTS replaced_by_id uuid;
