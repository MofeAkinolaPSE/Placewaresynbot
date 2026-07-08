-- 096: Customer profitability snapshot from Sage "Customer sales History".
--
-- One row per customer with lifetime sales, cost of sales, gross profit and
-- margin — the only per-customer profitability data in the Sage exports.

CREATE TABLE IF NOT EXISTS sage_customer_sales_snapshot (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id      uuid        NOT NULL,
    imported_at   timestamptz NOT NULL,
    customer_id   text        NOT NULL,
    name          text,
    amount        numeric,
    cost_of_sales numeric,
    gross_profit  numeric,
    gross_margin  numeric
);

CREATE INDEX IF NOT EXISTS sage_customer_sales_cust_idx
    ON sage_customer_sales_snapshot (customer_id, imported_at DESC);
CREATE INDEX IF NOT EXISTS sage_customer_sales_batch_idx
    ON sage_customer_sales_snapshot (batch_id);

ALTER TABLE sage_customer_sales_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS admin_all_sage_customer_sales ON sage_customer_sales_snapshot;
CREATE POLICY admin_all_sage_customer_sales ON sage_customer_sales_snapshot
    USING (true) WITH CHECK (true);
