-- 28 Oct 2026: an incoming batch QC registered is received when it arrives ("Confirm arrived"), as Sage's
-- Receive Inventory with "Waiting on bill": the stock goes into its batch at once (held until QC releases
-- it) and the books record goods received with the supplier's bill to come (Dr inventory, Cr goods-received
-- accrual). Purchases & Payables lists it until finance records the bill, whose line clears the accrual
-- instead of receiving the stock again.
CREATE TABLE IF NOT EXISTS fin_goods_receipts (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id          uuid NOT NULL REFERENCES fin_legal_entities(id),
    registry_id              uuid,
    supplier_id              uuid NOT NULL,
    supplier_invoice_number  text,
    sku                      text NOT NULL,
    batch_id                 uuid,
    quantity                 numeric(18,4) NOT NULL CHECK (quantity > 0),
    unit_cost                numeric(20,4) NOT NULL CHECK (unit_cost >= 0),
    total                    numeric(20,2) NOT NULL,
    received_date            date NOT NULL,
    inventory_txn_id         uuid,
    journal_id               uuid,
    bill_id                  uuid,
    status                   text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','BILLED','VOID')),
    notes                    text,
    created_by               text,
    created_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_goods_receipts_open ON fin_goods_receipts (legal_entity_id, supplier_id) WHERE status = 'RECEIVED';

ALTER TABLE nafdac_batch_registry ADD COLUMN IF NOT EXISTS arrived_at        timestamptz;
ALTER TABLE nafdac_batch_registry ADD COLUMN IF NOT EXISTS goods_receipt_id  uuid;
ALTER TABLE fin_supplier_bill_lines ADD COLUMN IF NOT EXISTS goods_receipt_id uuid;
