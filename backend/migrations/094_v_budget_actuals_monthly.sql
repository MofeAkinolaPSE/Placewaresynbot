-- 094: Monthly departmental spend view for Budget vs. Actual.
--
-- Actuals must come from dated GL detail transactions (sage_gl_snapshot has
-- no per-period expense breakdown). Only expense-type accounts count as
-- spend; "department" is the account name (no cost centers in this CoA),
-- falling back to the account code when the name is blank.

CREATE OR REPLACE VIEW v_budget_actuals_monthly AS
SELECT
    to_char(g.txn_date, 'YYYY-MM') AS period,
    COALESCE(
        NULLIF(TRIM(g.account_name), ''),
        NULLIF(TRIM(c.account_name), ''),
        g.account_code
    ) AS department,
    SUM(g.debit - g.credit) AS actual
FROM sage_gl_detail_snapshot g
JOIN (
    SELECT DISTINCT ON (account_code) account_code, account_type, account_name
    FROM sage_coa_snapshot
    ORDER BY account_code, imported_at DESC
) c ON c.account_code = g.account_code
WHERE g.txn_date IS NOT NULL
  AND c.account_type IN ('Cost of Sales', 'Expenses')
GROUP BY 1, 2;
