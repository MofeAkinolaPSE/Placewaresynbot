-- =============================================================================
-- Migration 118 — ACE Books: stricter duplicate supplier-invoice rule
-- =============================================================================
-- 117 compared supplier invoice numbers ignoring case and whitespace only, so
-- "INV-0045", "inv 0045" and "INV/0045" were treated as different invoices.
-- Compare on letters and digits only, per supplier.
-- =============================================================================

DROP INDEX IF EXISTS uq_fin_bill_supplier_invoice;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fin_bill_supplier_invoice
    ON fin_supplier_bills (legal_entity_id, supplier_id,
                           lower(regexp_replace(supplier_invoice_number, '[^[:alnum:]]', '', 'g')))
    WHERE status <> 'VOID';
