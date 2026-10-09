-- 136: A register entry remembers the ledger line it came from (a Sage purchase line, or the
-- payment voucher that bought it), so "Assets in the books" shows what is registered and the
-- register traces back to the payment.
ALTER TABLE fin_fixed_assets ADD COLUMN IF NOT EXISTS source_line text;
CREATE INDEX IF NOT EXISTS idx_fin_fixed_assets_source_line ON fin_fixed_assets (legal_entity_id, source_line);
