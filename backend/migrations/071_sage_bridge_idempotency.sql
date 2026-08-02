-- 071_sage_bridge_idempotency.sql
--
-- Supports the Sage Bridge v2 sync guarantees:
--   * placeware_sage_event_log   — dedupe key store; makes at-least-once
--                                  delivery from the bridge apply at most once
--   * sage_inventory_movements   — stock deltas derived from invoice lines
--   * sage_invoices_cache        — extra columns for the full invoice record
--
-- Idempotent: safe to re-run.

-- ── Applied-event log (idempotency gate) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS placeware_sage_event_log (
    event_id     TEXT PRIMARY KEY,          -- deterministic id from the bridge
    entity_type  TEXT,
    event        TEXT,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The webhook checks this on every inbound event, so it must stay fast.
CREATE INDEX IF NOT EXISTS idx_sage_event_log_applied_at
    ON placeware_sage_event_log (applied_at DESC);

COMMENT ON TABLE placeware_sage_event_log IS
    'Sage Bridge idempotency ledger. A row here means the event_id was already '
    'applied; the webhook returns 409 and the bridge stops retrying. Retain at '
    'least as long as the bridge retry window (default ~8h) plus a safety '
    'margin — 30 days is the recommended minimum.';

-- ── Inventory movement derived from invoice lines ───────────────────────────
CREATE TABLE IF NOT EXISTS sage_inventory_movements (
    source_document TEXT NOT NULL,          -- e.g. 'sage_invoice:1234'
    item_id         TEXT NOT NULL,
    quantity_delta  NUMERIC NOT NULL,       -- NEGATIVE for a sale
    direction       TEXT NOT NULL DEFAULT 'out',
    unit_price      NUMERIC,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_document, item_id)
);

-- Composite PK above is what makes replay safe: re-applying an invoice
-- overwrites its own movement rows instead of double-decrementing stock.

CREATE INDEX IF NOT EXISTS idx_sage_inv_move_item
    ON sage_inventory_movements (item_id);

COMMENT ON COLUMN sage_inventory_movements.quantity_delta IS
    'Signed change in stock. Negative for a sale (stock leaves). Apply directly '
    'to on-hand quantity — do not negate again.';

-- ── Extra columns on the invoice cache ──────────────────────────────────────
ALTER TABLE sage_invoices_cache
    ADD COLUMN IF NOT EXISTS customer_name   TEXT,
    ADD COLUMN IF NOT EXISTS subtotal        NUMERIC,
    ADD COLUMN IF NOT EXISTS total_tax       NUMERIC,
    ADD COLUMN IF NOT EXISTS amount_paid     NUMERIC,
    ADD COLUMN IF NOT EXISTS amount_due      NUMERIC,
    ADD COLUMN IF NOT EXISTS payment_status  TEXT,
    ADD COLUMN IF NOT EXISTS line_count      INTEGER,
    ADD COLUMN IF NOT EXISTS lines           JSONB,
    ADD COLUMN IF NOT EXISTS po_number       TEXT,
    ADD COLUMN IF NOT EXISTS note            TEXT,
    ADD COLUMN IF NOT EXISTS source          TEXT,
    ADD COLUMN IF NOT EXISTS completeness    TEXT,
    ADD COLUMN IF NOT EXISTS synced_at       TIMESTAMPTZ;

COMMENT ON COLUMN sage_invoices_cache.completeness IS
    'full = extracted via the Sage SDK (authoritative). partial = ODBC fallback; '
    'tax and some header fields may be missing. Treat partial rows as provisional.';

CREATE INDEX IF NOT EXISTS idx_sage_invoices_payment_status
    ON sage_invoices_cache (payment_status);
