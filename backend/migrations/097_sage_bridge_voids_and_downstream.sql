-- 097_sage_bridge_voids_and_downstream.sql
--
-- Completes the Sage Bridge sync surface. Two things were missing:
--
--   1. VOID / DELETE HANDLING. The bridge's forward scan walks ARTRANS from a
--      watermark upward and structurally cannot see a deleted row, so an
--      invoice voided in Sage stayed active in the cache forever with no
--      mechanism that would ever correct it. The bridge now runs a periodic
--      reconciliation sweep and emits `record_deleted`; these columns let us
--      apply that as a soft delete (never a hard one — the audit trail must
--      survive the void).
--
--   2. DOWNSTREAM COVERAGE. Invoice sync updated inventory, the invoice cache
--      and the audit log, but not customer records, finance, or sales. Those
--      three surfaces are added here.
--
-- Idempotent: safe to re-run.

-- ── Soft-delete support on the invoice cache ─────────────────────────────────
ALTER TABLE sage_invoices_cache
    ADD COLUMN IF NOT EXISTS is_voided  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS voided_at  TIMESTAMPTZ;

COMMENT ON COLUMN sage_invoices_cache.is_voided IS
    'TRUE once the invoice no longer exists in Sage (detected by the bridge''s '
    'reconciliation sweep). The row is retained rather than deleted so the '
    'audit trail and any historical reporting that referenced it stay intact. '
    'Every consumer computing live AR totals MUST filter on is_voided = FALSE.';

-- Partial index: the overwhelmingly common query is "live invoices only".
CREATE INDEX IF NOT EXISTS idx_sage_invoices_live
    ON sage_invoices_cache (customer_id)
    WHERE is_voided = FALSE;

-- ── Customer AR rollup (downstream: customer records) ────────────────────────
-- Derived from invoices rather than pulled from Sage: the bridge pushes each
-- invoice as it changes, so maintaining the rollup here keeps customer balances
-- current without a full customer re-pull on every invoice.
ALTER TABLE sage_customers_cache
    ADD COLUMN IF NOT EXISTS ar_balance         NUMERIC(18,4) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS open_invoice_count INTEGER       DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_invoice_date  DATE,
    ADD COLUMN IF NOT EXISTS last_invoice_at    TIMESTAMPTZ;

COMMENT ON COLUMN sage_customers_cache.ar_balance IS
    'Outstanding receivable derived from non-voided, unpaid invoices in '
    'sage_invoices_cache. Maintained incrementally by the bridge sync; '
    'recomputed authoritatively by refresh_customer_ar_rollup().';

-- ── Finance: GL impact per invoice (downstream: finance) ─────────────────────
-- One row per (invoice, account). Sage does the real ledger posting; this is
-- the mirror SynBot reports from. Composite PK makes replay idempotent for the
-- same reason sage_inventory_movements uses one.
CREATE TABLE IF NOT EXISTS sage_gl_entries (
    source_document TEXT NOT NULL,             -- 'sage_invoice:1234'
    gl_account      TEXT NOT NULL,
    entry_type      TEXT NOT NULL,             -- revenue | tax | receivable
    amount          NUMERIC(18,4) NOT NULL,
    customer_id     TEXT,
    entry_date      DATE,
    is_voided       BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_document, gl_account, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_sage_gl_account
    ON sage_gl_entries (gl_account, entry_date);

CREATE INDEX IF NOT EXISTS idx_sage_gl_live
    ON sage_gl_entries (entry_date)
    WHERE is_voided = FALSE;

COMMENT ON TABLE sage_gl_entries IS
    'Mirror of the ledger impact of each synced invoice. NOT the book of record '
    '— Sage is. Voided invoices flip is_voided rather than deleting, so period '
    'reports reconstructed for a past date stay correct.';

-- ── Sales facts (downstream: sales + reporting) ──────────────────────────────
-- Line-level sales grain. The invoice cache stores lines as JSONB, which is
-- fine for display but unqueryable for "units of item X sold last quarter".
CREATE TABLE IF NOT EXISTS sage_sales_lines (
    source_document TEXT NOT NULL,             -- 'sage_invoice:1234'
    line_no         INTEGER NOT NULL,
    sage_id         TEXT NOT NULL,
    customer_id     TEXT,
    item_id         TEXT,
    description     TEXT,
    quantity        NUMERIC(18,4),
    unit_price      NUMERIC(18,4),
    amount          NUMERIC(18,4),
    gl_account      TEXT,
    tax_amount      NUMERIC(18,4) DEFAULT 0,
    invoice_date    DATE,
    is_voided       BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_document, line_no)
);

CREATE INDEX IF NOT EXISTS idx_sage_sales_item
    ON sage_sales_lines (item_id, invoice_date);

CREATE INDEX IF NOT EXISTS idx_sage_sales_customer
    ON sage_sales_lines (customer_id, invoice_date);

CREATE INDEX IF NOT EXISTS idx_sage_sales_live
    ON sage_sales_lines (invoice_date)
    WHERE is_voided = FALSE;

-- ── Void propagation to inventory movements ──────────────────────────────────
ALTER TABLE sage_inventory_movements
    ADD COLUMN IF NOT EXISTS is_voided BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN sage_inventory_movements.is_voided IS
    'TRUE when the source invoice was voided. Stock calculations must exclude '
    'these rows — the goods never left. Kept rather than deleted so the '
    'movement history remains auditable.';

CREATE INDEX IF NOT EXISTS idx_sage_inv_move_live
    ON sage_inventory_movements (item_id)
    WHERE is_voided = FALSE;

-- ── Authoritative rollup recompute ───────────────────────────────────────────
-- The incremental path in sage_sync_engine keeps ar_balance current per
-- invoice. This recomputes from scratch — use it after a bulk replay, a
-- watermark reset, or any time the incremental figures are in doubt.
CREATE OR REPLACE FUNCTION refresh_customer_ar_rollup()
RETURNS void
LANGUAGE sql
AS $$
    UPDATE sage_customers_cache c
    SET ar_balance         = COALESCE(agg.balance, 0),
        open_invoice_count = COALESCE(agg.open_count, 0),
        last_invoice_date  = agg.last_date
    FROM (
        SELECT
            customer_id,
            SUM(amount_due) FILTER (WHERE payment_status <> 'paid') AS balance,
            COUNT(*)        FILTER (WHERE payment_status <> 'paid') AS open_count,
            MAX(date)                                               AS last_date
        FROM sage_invoices_cache
        WHERE is_voided = FALSE
        GROUP BY customer_id
    ) agg
    WHERE c.id = agg.customer_id;
$$;

COMMENT ON FUNCTION refresh_customer_ar_rollup() IS
    'Recompute every customer AR rollup from the invoice cache. Safe to run '
    'any time; O(invoices). Run after a bulk replay or watermark reset.';
