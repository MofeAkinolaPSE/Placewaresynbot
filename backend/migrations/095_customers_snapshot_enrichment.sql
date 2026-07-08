-- 095: Enrich sage_customers_snapshot with the full Customer Master fields.
--
-- The Sage "Customer Master File list" export carries address, city, billing
-- contact, trade terms, and customer-since date; previously only name/phone/
-- email were captured, leaving the CRM customer table mostly blank.

ALTER TABLE sage_customers_snapshot
    ADD COLUMN IF NOT EXISTS address        text,
    ADD COLUMN IF NOT EXISTS city           text,
    ADD COLUMN IF NOT EXISTS contact_person text,
    ADD COLUMN IF NOT EXISTS terms          text,
    ADD COLUMN IF NOT EXISTS customer_since date;
