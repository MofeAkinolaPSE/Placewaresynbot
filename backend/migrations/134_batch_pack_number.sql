-- 134: The batch number printed on the pack (e.g. Y3C77D4), next to Placeware's own lot code.
--
-- The client's Sage uses one item code per lot (HEXAXIM (Q)); the letter is their internal lot
-- code. Their invoices print the manufacturer's batch number and manufacture date, which are not in
-- any Sage export, so ACE keeps them on the batch once someone enters them (Stock > Batches, or on
-- the invoice line) and every later invoice prints them.
ALTER TABLE fin_batches ADD COLUMN IF NOT EXISTS pack_batch_number text;
