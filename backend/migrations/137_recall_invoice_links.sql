-- Recalls linked to the invoices and supplier bills they affect (8 Oct 2026).
-- A recall line is now one invoice (ACE Books or Sage) or one loan: the quantity of the recalled
-- batch on that document and the price it was sold at, so a return credits that invoice at that
-- price. Stock sent back to the supplier is a debit note against the bill the batch came in on.

ALTER TABLE fin_recall_items ADD COLUMN IF NOT EXISTS source        text;          -- ACE | SAGE | LOAN
ALTER TABLE fin_recall_items ADD COLUMN IF NOT EXISTS invoice_date  date;
ALTER TABLE fin_recall_items ADD COLUMN IF NOT EXISTS unit_price    numeric(18,4);
ALTER TABLE fin_recall_items ADD COLUMN IF NOT EXISTS added_by_hand boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_fin_recall_items_invoice ON fin_recall_items (invoice_id) WHERE invoice_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fin_recall_items_invno   ON fin_recall_items (invoice_number);

CREATE TABLE IF NOT EXISTS fin_recall_supplier_returns (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recall_id        uuid NOT NULL REFERENCES fin_recalls(id) ON DELETE CASCADE,
    supplier_id      uuid,
    bill_id          uuid,
    sage_bill_number text,
    debit_note_id    uuid,
    quantity         numeric(18,4) NOT NULL,
    unit_cost        numeric(18,4),
    created_by       text,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_recall_supplier_returns_recall ON fin_recall_supplier_returns (recall_id);
