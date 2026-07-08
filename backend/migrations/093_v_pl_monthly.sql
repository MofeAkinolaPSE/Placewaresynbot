-- 093: Monthly P&L view over GL detail transactions.
--
-- sage_gl_snapshot (account summary export) carries no per-period breakdown
-- for income accounts (period = '0000-00'), so the monthly P&L must be
-- computed from the dated transaction rows in sage_gl_detail_snapshot,
-- classified by account_type from the chart of accounts.

CREATE OR REPLACE VIEW v_pl_monthly AS
SELECT
    to_char(g.txn_date, 'YYYY-MM') AS period,
    SUM(CASE WHEN c.account_type = 'Income'
             THEN g.credit - g.debit ELSE 0 END)          AS revenue,
    SUM(CASE WHEN c.account_type IN ('Cost of Sales', 'Expenses')
             THEN g.debit - g.credit ELSE 0 END)          AS expenses
FROM sage_gl_detail_snapshot g
JOIN (
    SELECT DISTINCT ON (account_code) account_code, account_type
    FROM sage_coa_snapshot
    ORDER BY account_code, imported_at DESC
) c ON c.account_code = g.account_code
WHERE g.txn_date IS NOT NULL
  AND c.account_type IN ('Income', 'Cost of Sales', 'Expenses')
GROUP BY 1;
