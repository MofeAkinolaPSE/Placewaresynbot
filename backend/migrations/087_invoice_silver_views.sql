-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 087: Invoice Silver Views + placeware_invoices table
-- Adds v_ar_invoices, v_ar_invoice_lines (Silver layer) and the
-- placeware_invoices table (ACE's branded copy, auto-populated on Sage import).
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Performance indexes on invoice Bronze tables ──────────────────────────
CREATE INDEX IF NOT EXISTS idx_sage_ar_inv_id_batch
    ON sage_ar_snapshot (invoice_id, batch_id, imported_at DESC);

CREATE INDEX IF NOT EXISTS idx_sage_inv_lines_inv_id_batch
    ON sage_invoice_lines_snapshot (invoice_id, batch_id, imported_at DESC);

-- ── v_ar_invoices ─────────────────────────────────────────────────────────
-- Deduplicated invoice headers from the latest import batch, enriched with
-- customer name from v_customers.
CREATE OR REPLACE VIEW v_ar_invoices AS
WITH latest_batch AS (
    SELECT batch_id
    FROM sage_ar_snapshot
    ORDER BY imported_at DESC
    LIMIT 1
)
SELECT
    s.invoice_id,
    s.customer_id,
    c.name          AS customer_name,
    s.date          AS invoice_date,
    s.due_date,
    s.amount        AS total_amount,
    s.balance       AS outstanding_balance,
    s.status
FROM sage_ar_snapshot s
JOIN latest_batch lb ON s.batch_id = lb.batch_id
LEFT JOIN v_customers c ON c.customer_id = s.customer_id;

-- ── v_ar_invoice_lines ────────────────────────────────────────────────────
-- Invoice line items from the latest batch, enriched with item name from
-- v_inventory.
CREATE OR REPLACE VIEW v_ar_invoice_lines AS
WITH latest_batch AS (
    SELECT batch_id
    FROM sage_invoice_lines_snapshot
    ORDER BY imported_at DESC
    LIMIT 1
)
SELECT
    l.invoice_id,
    l.line_id,
    l.item_id,
    i.name          AS item_name,
    l.quantity,
    l.unit_price,
    l.discount,
    l.line_total,
    l.gross_profit
FROM sage_invoice_lines_snapshot l
JOIN latest_batch lb ON l.batch_id = lb.batch_id
LEFT JOIN v_inventory i ON i.sku = l.item_id;

-- ── placeware_invoices ────────────────────────────────────────────────────
-- ACE's branded invoice table. Auto-populated when sales_invoices.csv is
-- imported via POST /sage/import/csv. Upserted on invoice_id so re-imports
-- update rather than duplicate.
CREATE TABLE IF NOT EXISTS placeware_invoices (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id      text        NOT NULL UNIQUE,
    customer_id     text,
    customer_name   text,
    invoice_date    date,
    due_date        date,
    total_amount    numeric(14, 2),
    outstanding     numeric(14, 2),
    status          text        DEFAULT 'open',
    synced_from     text        DEFAULT 'sage_50',
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_placeware_inv_customer
    ON placeware_invoices (customer_id);

CREATE INDEX IF NOT EXISTS idx_placeware_inv_date
    ON placeware_invoices (invoice_date DESC);
