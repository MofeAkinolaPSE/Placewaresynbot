-- 130: documents brought forward from Sage carry their real Sage numbers, dates and amounts
-- ("OB-51844" -> "51844"; no "Sage open item ... at cutover" text). Display only: these
-- documents have no journals of their own (the opening trial balance carries them).
-- Safe to re-run.

-- invoices: the Sage invoice number (kept unique: a number used twice gets "/<customer code>")
WITH src AS (
    SELECT i.id, split_part(i.source_id, ':', 3) AS doc, c.customer_code,
           row_number() OVER (PARTITION BY i.legal_entity_id, split_part(i.source_id, ':', 3) ORDER BY i.created_at) AS n
    FROM fin_sales_invoices i JOIN customers c ON c.id = i.customer_id
    WHERE i.is_opening AND i.invoice_number LIKE 'OB-%'
)
UPDATE fin_sales_invoices i
   SET invoice_number = CASE WHEN s.n = 1 AND NOT EXISTS (SELECT 1 FROM fin_sales_invoices x WHERE x.legal_entity_id = i.legal_entity_id
                                                          AND x.invoice_number = s.doc)
                             THEN s.doc ELSE left(s.doc || '/' || COALESCE(s.customer_code, i.customer_id::text), 60) END,
       notes = NULL
  FROM src s WHERE s.id = i.id;

UPDATE fin_sales_invoices SET notes = NULL WHERE is_opening AND notes LIKE 'Sage open item%';

-- the invoice's original amount and date from the customer's own Sage ledger line
UPDATE fin_sales_invoices SET original_total = NULL WHERE is_opening;
UPDATE fin_sales_invoices i SET original_total = l.debit
  FROM fin_sage_party_ledger l, customers c
 WHERE i.is_opening AND c.id = i.customer_id AND l.legal_entity_id = i.legal_entity_id AND l.party_kind = 'CUSTOMER'
   AND l.party_code = c.customer_code AND l.trans_no = split_part(i.source_id, ':', 3) AND l.jrnl = 'SJ'
   AND l.debit >= i.total;

UPDATE fin_sales_invoices i SET invoice_date = l.txn_date,
       due_date = l.txn_date + COALESCE(i.terms_days, c.payment_terms_days, 30)
  FROM fin_sage_party_ledger l, customers c
 WHERE i.is_opening AND c.id = i.customer_id AND l.legal_entity_id = i.legal_entity_id AND l.party_kind = 'CUSTOMER'
   AND l.party_code = c.customer_code AND l.trans_no = split_part(i.source_id, ':', 3) AND l.jrnl = 'SJ'
   AND l.txn_date <= COALESCE((SELECT history_until FROM fin_settings s WHERE s.legal_entity_id = i.legal_entity_id), l.txn_date);

-- customer credits: the Sage reference (cheque / transfer / credit memo number)
WITH src AS (
    SELECT n.id, regexp_replace(n.credit_note_number, '^OB-CR-(.*)-[0-9]+$', '\1') AS doc, c.customer_code,
           row_number() OVER (PARTITION BY n.legal_entity_id, regexp_replace(n.credit_note_number, '^OB-CR-(.*)-[0-9]+$', '\1')
                              ORDER BY n.created_at) AS k
    FROM fin_credit_notes n JOIN customers c ON c.id = n.customer_id
    WHERE n.journal_id IS NULL AND n.credit_note_number LIKE 'OB-CR-%'
)
UPDATE fin_credit_notes n
   SET credit_note_number = left(CASE WHEN s.k = 1 THEN s.doc ELSE s.doc || '/' || COALESCE(s.customer_code, n.customer_id::text) || '/' || s.k END, 60),
       sage_invoice_number = s.doc,
       reason = CASE WHEN s.doc ~* '^(transfer|cash|cheque|chq|pos|wht|direct)' OR s.doc !~ '[0-9]'
                     THEN 'Payment received, not yet applied to an invoice (Sage ' || s.doc || ')'
                     ELSE 'Credit ' || s.doc || ' (Sage)' END
  FROM src s WHERE s.id = n.id;

-- supplier bills: the supplier's own invoice number
WITH src AS (
    SELECT b.id, b.supplier_invoice_number AS doc, s.external_vendor_id AS code,
           row_number() OVER (PARTITION BY b.legal_entity_id, b.supplier_invoice_number ORDER BY b.created_at) AS n
    FROM fin_supplier_bills b JOIN suppliers s ON s.id = b.supplier_id
    WHERE b.is_opening AND b.bill_number LIKE 'OB-%'
)
UPDATE fin_supplier_bills b
   SET bill_number = left(CASE WHEN s.n = 1 AND NOT EXISTS (SELECT 1 FROM fin_supplier_bills x WHERE x.legal_entity_id = b.legal_entity_id
                                                            AND x.bill_number = s.doc)
                               THEN s.doc ELSE s.doc || '/' || COALESCE(s.code, '') END, 60),
       notes = NULL
  FROM src s WHERE s.id = b.id;

UPDATE fin_supplier_bills b SET bill_date = l.txn_date
  FROM fin_sage_party_ledger l, suppliers s
 WHERE b.is_opening AND s.id = b.supplier_id AND l.legal_entity_id = b.legal_entity_id AND l.party_kind = 'VENDOR'
   AND l.party_code = s.external_vendor_id AND l.trans_no = b.supplier_invoice_number AND l.jrnl = 'PJ'
   AND l.txn_date <= b.due_date + 365;

UPDATE fin_debit_notes d
   SET debit_note_number = left(regexp_replace(d.debit_note_number, '^OB-DR-', ''), 60),
       sage_bill_number = regexp_replace(regexp_replace(d.debit_note_number, '^OB-DR-', ''), '-[0-9]+$', ''),
       reason = 'Supplier balance in our favour (Sage ' || regexp_replace(regexp_replace(d.debit_note_number, '^OB-DR-', ''), '-[0-9]+$', '') || ')'
 WHERE d.journal_id IS NULL AND d.debit_note_number LIKE 'OB-DR-%';
