-- 23 Oct 2026: an invoice voided in ACE Books is voided on Frontdesk too (sales.void_frontdesk_twin).
-- This repairs requests left behind before that: a Frontdesk invoice whose ACE Books invoice is void
-- (and that has no live ACE invoice) is cancelled, so it leaves the QC queue and Frontdesk; its
-- walk-in is cancelled when it has no other live invoice.
WITH voided AS (
    SELECT DISTINCT f.id, f.walk_in_id
    FROM frontdesk_invoices f
    JOIN fin_sales_invoices i
      ON i.status = 'VOID'
     AND ((i.source_type = 'FRONTDESK' AND i.source_id = f.id::text)
          OR ((i.invoice_number = f.invoice_number OR i.invoice_number = f.invoice_number || '-VOID')
              AND f.created_at <= COALESCE(i.voided_at, now())))
    WHERE f.status <> 'cancelled'
      AND NOT EXISTS (SELECT 1 FROM fin_sales_invoices j
                      WHERE j.status <> 'VOID'
                        AND ((j.source_type = 'FRONTDESK' AND j.source_id = f.id::text) OR j.invoice_number = f.invoice_number))
), upd AS (
    UPDATE frontdesk_invoices f
       SET status = 'cancelled', updated_at = now(),
           notes = trim(both ' ' from COALESCE(f.notes, '') || ' [Voided in ACE Books]')
      FROM voided v WHERE f.id = v.id
    RETURNING f.walk_in_id
)
UPDATE frontdesk_walk_ins w SET status = 'cancelled', updated_at = now()
 WHERE w.id IN (SELECT walk_in_id FROM upd)
   AND w.status <> 'cancelled'
   AND NOT EXISTS (SELECT 1 FROM frontdesk_invoices o WHERE o.walk_in_id = w.id AND o.status <> 'cancelled'
                   AND o.id NOT IN (SELECT id FROM voided));
