-- 7 Nov 2026 (client re-introduction meeting, 6 Nov):
--
-- 1. One invoice total for every screen. frontdesk_invoices.total_amount holds the GOODS only; the form
--    showed goods - discount + delivery + tax, while the QC queue, invoice detail, Frontdesk list, AR
--    receipts, customer screens and notifications showed total_amount - so an invoice with a delivery
--    charge looked short (e.g. N95,000 raised, N93,500 at QC). grand_total is worked out by the database
--    from the stored parts, so no screen can add it up differently again.
ALTER TABLE frontdesk_invoices
    ADD COLUMN IF NOT EXISTS grand_total numeric(14,2)
    GENERATED ALWAYS AS (total_amount - discount_amount + delivery_charge + tax_amount) STORED;

-- 2. The client dropped the QC stage: Frontdesk raises the invoice, Finance approves it, and approval posts
--    it to ACE Books. Requests still waiting for QC (or failed at QC) move to Finance's queue.
UPDATE frontdesk_invoices
   SET status = 'finance_pending', updated_at = now()
 WHERE status IN ('draft', 'qc_pending', 'qc_passed', 'qc_failed');

UPDATE frontdesk_walk_ins w
   SET status = 'finance_pending', updated_at = now()
 WHERE w.status IN ('invoiced', 'qc_pending', 'qc_passed', 'qc_failed')
   AND EXISTS (SELECT 1 FROM frontdesk_invoices f WHERE f.walk_in_id = w.id AND f.status = 'finance_pending');

-- Nobody is asked to QC-check an invoice any more: those bell items go.
DELETE FROM staff_notifications WHERE kind IN ('qc_check', 'qc_result');

-- 3. Approval posts to the books (it was paused while the Sage periods were loaded; that is finished -
--    the books are rolled forward and live since the cut-over). Finance can still pause it in Setup > Settings.
UPDATE fin_settings SET auto_post_frontdesk = TRUE WHERE cutover_date IS NOT NULL AND auto_post_frontdesk IS DISTINCT FROM TRUE;
