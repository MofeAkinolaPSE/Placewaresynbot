-- 135: Who signed the Frontdesk invoice checks.
--
-- QC and Finance sign with their own login (the name shown and printed comes from their account,
-- not a typed field), and the person who raised an invoice cannot also QC it.
ALTER TABLE frontdesk_invoices ADD COLUMN IF NOT EXISTS qc_inspector_id uuid;
ALTER TABLE frontdesk_invoices ADD COLUMN IF NOT EXISTS finance_approver_id uuid;
