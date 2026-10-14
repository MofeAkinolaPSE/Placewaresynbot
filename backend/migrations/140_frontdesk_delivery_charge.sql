-- 13 Oct 2026: Frontdesk invoice requests can carry a delivery charge (finance meeting 3).
-- It is billed to the customer with the goods and, when Finance approves, posts to ACE Books as a
-- "Delivery charge" line on the invoice - credited to Other Income (40800), never to product sales.
ALTER TABLE frontdesk_invoices ADD COLUMN IF NOT EXISTS delivery_charge numeric(14,2) NOT NULL DEFAULT 0;
