-- 15 Oct 2026: Frontdesk invoice requests can carry a discount allowed (client follow-up to meeting 3).
-- It reduces what the customer is billed and, when Finance approves, posts to ACE Books as a
-- "Discount allowed" line - debited to Sales Discount (49000).
ALTER TABLE frontdesk_invoices ADD COLUMN IF NOT EXISTS discount_amount numeric(14,2) NOT NULL DEFAULT 0;
