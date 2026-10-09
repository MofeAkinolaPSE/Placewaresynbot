-- 133: indexes for 30-50 laptops at once.
--
-- Every ACE Books balance up to the hand-over date reads Sage history through
-- books_ledger._hist_balances. Its correction lookup (jrnl 'ADJ' lines with no load) had no
-- index of its own, so for each of ~340 accounts Postgres walked every Sage line before the
-- account's month - about 420,000 index entries per call, ~2s - and the income statement makes
-- 8-12 of those calls (the Books dashboard took 24s). A partial index over just the correction
-- lines makes the lookup a direct hit (there are only a handful of them).
--
-- ANALYZE because the Sage history tables (400k+ rows) had never been analysed since they were
-- loaded, so the planner was guessing their size. Additive only.

CREATE INDEX IF NOT EXISTS ix_fin_sage_gl_corrections
    ON fin_sage_gl_lines (legal_entity_id, account_code, txn_date)
    WHERE jrnl = 'ADJ' AND load_id IS NULL;

ANALYZE;
