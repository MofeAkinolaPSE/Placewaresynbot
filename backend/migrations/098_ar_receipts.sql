-- 098_ar_receipts.sql
--
-- Customer Receipts & Accounts — the AR write-side counterpart to the
-- existing read-only /finance/ar/aging, /finance/ar/match endpoints.
--
-- Purely additive: two new tables + one new view. Nothing existing is
-- altered. sage_ar_snapshot (the Sage CSV/DAT import target) and
-- v_ar_invoices (migration 087's Silver view over it) are read-only inputs
-- here — never written to — so a future Sage re-import behaves exactly as
-- it does today and never wipes out a recorded receipt.
--
-- Idempotent: safe to re-run.

-- ── ar_receipts — one row per payment recorded ──────────────────────────────
CREATE TABLE IF NOT EXISTS ar_receipts (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_number   text GENERATED ALWAYS AS ('RCT-' || upper(right(id::text, 8))) STORED,
    customer_id      text NOT NULL,
    customer_name    text,
    amount           numeric(14, 2) NOT NULL CHECK (amount > 0),
    payment_method   text NOT NULL CHECK (payment_method IN (
                         'cash', 'card', 'bank_transfer', 'mobile_payment',
                         'corporate_account', 'split_payment', 'cheque', 'pos'
                     )),
    reference        text,
    collector        text,
    receipt_date     date NOT NULL DEFAULT current_date,
    status           text NOT NULL DEFAULT 'posted' CHECK (status IN ('posted', 'voided')),
    void_reason      text,
    voided_by        text,
    voided_at        timestamptz,
    notes            text,
    created_by       text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE ar_receipts IS
    'ACE-native customer payment ledger — NOT a Sage snapshot table. Immutable '
    'after posting: the only allowed transition is posted -> voided (terminal, '
    'requires void_reason). There is deliberately no UPDATE endpoint on the '
    'core fields; corrections happen by voiding and re-recording.';

CREATE INDEX IF NOT EXISTS idx_ar_receipts_customer     ON ar_receipts (customer_id);
CREATE INDEX IF NOT EXISTS idx_ar_receipts_date          ON ar_receipts (receipt_date DESC);
CREATE INDEX IF NOT EXISTS idx_ar_receipts_status        ON ar_receipts (status);
CREATE INDEX IF NOT EXISTS idx_ar_receipts_created_at    ON ar_receipts (created_at DESC);


-- ── ar_receipt_applications — allocation of a receipt across invoice(s) ─────
CREATE TABLE IF NOT EXISTS ar_receipt_applications (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id      uuid NOT NULL REFERENCES ar_receipts(id),
    invoice_id      text NOT NULL,   -- soft relationship (text-typed, like the
                                      -- rest of this schema) — no FK to
                                      -- sage_ar_snapshot, which is an
                                      -- append-only batch-import table, not a
                                      -- stable-PK master table.
    amount_applied  numeric(14, 2) NOT NULL CHECK (amount_applied > 0),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (receipt_id, invoice_id)
);

COMMENT ON TABLE ar_receipt_applications IS
    'Allocation lines for a receipt. Never deleted or edited, even when the '
    'parent receipt is voided — voiding only flips ar_receipts.status; '
    'v_ar_receivables_open filters on that status to "restore" the balance, '
    'so this table stays a complete, append-only audit trail.';

CREATE INDEX IF NOT EXISTS idx_ar_receipt_apps_invoice  ON ar_receipt_applications (invoice_id);
CREATE INDEX IF NOT EXISTS idx_ar_receipt_apps_receipt  ON ar_receipt_applications (receipt_id);


-- ── v_ar_receivables_open — true outstanding balance per invoice ───────────
-- Built on v_ar_invoices (086/087's Silver view over sage_ar_snapshot), the
-- same source finance.py's existing /finance/ar/aging and /finance/ar/match
-- already treat as the source of truth — this keeps the new feature's
-- numbers consistent with what staff already see on the AR Aging page,
-- rather than introducing a third, divergent notion of "the balance".
CREATE OR REPLACE VIEW v_ar_receivables_open AS
SELECT
    v.invoice_id,
    v.customer_id,
    v.customer_name,
    v.invoice_date,
    v.due_date,
    v.total_amount,
    v.outstanding_balance                                                  AS sage_outstanding_balance,
    COALESCE(applied.total_applied, 0)                                     AS ace_receipts_applied,
    GREATEST(v.outstanding_balance - COALESCE(applied.total_applied, 0), 0) AS true_outstanding_balance,
    v.status
FROM v_ar_invoices v
LEFT JOIN (
    SELECT ra.invoice_id, SUM(ra.amount_applied) AS total_applied
    FROM ar_receipt_applications ra
    JOIN ar_receipts r ON r.id = ra.receipt_id
    WHERE r.status != 'voided'
    GROUP BY ra.invoice_id
) applied ON applied.invoice_id = v.invoice_id;

COMMENT ON VIEW v_ar_receivables_open IS
    'True outstanding balance = Sage-imported balance minus unvoided ACE '
    'receipt applications. sage_ar_snapshot itself is never written to, so a '
    'Sage re-import safely recomputes sage_outstanding_balance while '
    'ace_receipts_applied (and therefore recorded receipts) is untouched. '
    'Operational note: if accounts staff continue entering a payment directly '
    'in Sage 50 (as they do today) AND also record it here, the payment is '
    'not double-counted in this view (Sage''s own balance recalculation is '
    'the sage_outstanding_balance input either way) — but staff should be '
    'trained to record each payment in ONE place during the transition, not '
    'both, to avoid confusion about which system is authoritative for a given '
    'receipt. See ACE-Customer-Receipts-Workspace.md.';
