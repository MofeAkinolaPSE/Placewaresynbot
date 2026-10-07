-- =============================================================================
-- Migration 120 — ACE Books as the read source for the whole application
-- =============================================================================
-- Sage snapshots froze at the cut-over. These views give every non-finance
-- feature (CRM 360, reorder prediction, top sellers, analytics, dashboards,
-- agents, reports) one current source, built on ACE Books:
--
--   v_sales_lines            every sales line: Sage history to the cut-over +
--                            ACE Books invoices/credit notes after it
--   v_customer_invoices      one row per sales invoice, with what is still open
--   v_ar_open                open receivable items today (invoices, unapplied
--                            receipts and credits) - identical to ACE Books ageing
--   v_customer_sales_summary lifetime sales, cost and margin per customer
--   v_inventory              (redefined) current stock from ACE Books for every
--                            item the books hold
--
-- The old v_inventory summed the latest Sage stock batch, which holds every
-- item twice, so all operational stock read double (e.g. MENACTRA (R) 1,496
-- against 748 on hand). Items the books hold now read ACE Books FIFO stock;
-- anything else keeps a de-duplicated Sage baseline plus movement events.
-- =============================================================================

CREATE OR REPLACE VIEW v_sales_lines AS
SELECT 'SAGE'::text                AS source,
       s.invoice_number,
       s.invoice_date,
       s.customer_id               AS customer_pk,
       c.customer_code             AS customer_id,
       COALESCE(c.name, s.customer_name) AS customer_name,
       s.sku,
       s.description,
       s.quantity,
       s.amount,
       s.cost,
       s.amount - COALESCE(s.cost, 0) AS gross_profit,
       s.legal_entity_id
FROM fin_sage_sales_lines s
LEFT JOIN customers c ON c.id = s.customer_id
UNION ALL
SELECT 'ACE', i.invoice_number, i.invoice_date, i.customer_id, c.customer_code, c.name,
       l.sku, l.description, l.quantity, l.line_total, l.cost_amount,
       l.line_total - COALESCE(l.cost_amount, 0), i.legal_entity_id
FROM fin_sales_invoice_lines l
JOIN fin_sales_invoices i ON i.id = l.invoice_id
LEFT JOIN customers c ON c.id = i.customer_id
WHERE NOT i.is_opening AND i.status NOT IN ('DRAFT', 'VOID')
UNION ALL
SELECT 'ACE', n.credit_note_number, n.note_date, n.customer_id, c.customer_code, c.name,
       l.sku, l.description, -l.quantity, -l.line_total, -COALESCE(l.cost_amount, 0),
       -(l.line_total - COALESCE(l.cost_amount, 0)), n.legal_entity_id
FROM fin_credit_note_lines l
JOIN fin_credit_notes n ON n.id = l.credit_note_id
LEFT JOIN customers c ON c.id = n.customer_id
WHERE n.status = 'POSTED' AND n.journal_id IS NOT NULL;


-- One row per invoice. Sage invoices that were still open at the cut-over are
-- ACE Books opening invoices (their open balance is live); the rest were
-- settled in Sage and carry a zero balance.
CREATE OR REPLACE VIEW v_customer_invoices AS
WITH sage AS (
    SELECT s.legal_entity_id, s.invoice_number, MIN(s.invoice_date) AS invoice_date, s.customer_id,
           MAX(s.customer_name) AS customer_name, SUM(s.amount) AS amount
    FROM fin_sage_sales_lines s
    GROUP BY s.legal_entity_id, s.invoice_number, s.customer_id
)
SELECT 'SAGE'::text AS source, sg.invoice_number AS invoice_id, sg.customer_id AS customer_pk,
       c.customer_code AS customer_id, COALESCE(c.name, sg.customer_name) AS customer_name,
       sg.invoice_date AS date,
       COALESCE(oi.due_date, sg.invoice_date + COALESCE(c.payment_terms_days, 30)) AS due_date,
       sg.amount,
       COALESCE(oi.total - oi.amount_settled, 0) AS balance,
       CASE WHEN oi.id IS NULL OR oi.total - oi.amount_settled = 0 THEN 'paid' ELSE 'open' END AS status,
       oi.id AS ace_invoice_id, sg.legal_entity_id
FROM sage sg
LEFT JOIN customers c ON c.id = sg.customer_id
LEFT JOIN fin_sales_invoices oi ON oi.legal_entity_id = sg.legal_entity_id AND oi.is_opening
     AND split_part(oi.source_id, ':', 3) = sg.invoice_number AND oi.customer_id = sg.customer_id
UNION ALL
SELECT 'ACE', i.invoice_number, i.customer_id, c.customer_code, c.name, i.invoice_date, i.due_date, i.total,
       i.total - i.amount_settled,
       CASE WHEN i.total - i.amount_settled = 0 THEN 'paid' ELSE 'open' END, i.id, i.legal_entity_id
FROM fin_sales_invoices i
LEFT JOIN customers c ON c.id = i.customer_id
WHERE NOT i.is_opening AND i.status NOT IN ('DRAFT', 'VOID');


-- Open receivable items as at today: same rules as reports.ar_open_items.
CREATE OR REPLACE VIEW v_ar_open AS
SELECT x.*, c.customer_code AS customer_id, c.name AS customer_name,
       GREATEST(current_date - x.due_date, 0) AS days_overdue
FROM (
    SELECT i.legal_entity_id, 'INVOICE'::text AS doc_type, i.id AS doc_id, i.invoice_number AS doc_number,
           i.customer_id AS customer_pk, i.invoice_date AS doc_date, i.due_date, i.total AS amount,
           i.total - COALESCE((SELECT SUM(a.amount) FROM fin_ar_allocations a WHERE a.invoice_id = i.id AND NOT a.reversed), 0) AS balance
    FROM fin_sales_invoices i WHERE i.status NOT IN ('DRAFT', 'VOID')
    UNION ALL
    SELECT r.legal_entity_id, 'RECEIPT', r.id, r.receipt_number, r.customer_id, r.receipt_date, r.receipt_date, r.amount + r.wht_amount,
           -(r.amount + r.wht_amount - COALESCE((SELECT SUM(a.amount) FROM fin_ar_allocations a WHERE a.source_type = 'RECEIPT'
                                                  AND a.source_id = r.id AND NOT a.reversed), 0))
    FROM fin_customer_receipts r WHERE r.status = 'POSTED'
    UNION ALL
    SELECT n.legal_entity_id, 'CREDIT_NOTE', n.id, n.credit_note_number, n.customer_id, n.note_date, n.note_date, n.total,
           -(n.total - COALESCE((SELECT SUM(a.amount) FROM fin_ar_allocations a WHERE a.source_type = 'CREDIT_NOTE'
                                  AND a.source_id = n.id AND NOT a.reversed), 0))
    FROM fin_credit_notes n WHERE n.status = 'POSTED'
) x
LEFT JOIN customers c ON c.id = x.customer_pk
WHERE x.balance <> 0;


CREATE OR REPLACE VIEW v_customer_sales_summary AS
SELECT customer_pk, MAX(customer_id) AS customer_id, MAX(customer_name) AS customer_name,
       SUM(amount) AS amount, SUM(COALESCE(cost, 0)) AS cost_of_sales, SUM(gross_profit) AS gross_profit,
       CASE WHEN SUM(amount) <> 0 THEN ROUND(SUM(gross_profit) / SUM(amount) * 100, 2) END AS gross_margin,
       COUNT(DISTINCT invoice_number) AS invoices, MIN(invoice_date) AS first_sale, MAX(invoice_date) AS last_sale
FROM v_sales_lines
WHERE customer_pk IS NOT NULL
GROUP BY customer_pk;


-- ---------------------------------------------------------------------------
-- v_inventory: ACE Books stock for items the books hold
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_inventory AS
WITH latest_items AS (
    SELECT DISTINCT ON (s.item_id, COALESCE(s.company_id, 'default'))
           s.item_id AS sku, s.item_name AS name, s.category, s.unit, s.cost_price, s.selling_price, s.vat_category,
           s.reorder_level, s.is_active, s.expiry_date, s.batch_number, s.company_id
    FROM sage_items_snapshot s
    ORDER BY s.item_id, COALESCE(s.company_id, 'default'), s.imported_at DESC
), books_live AS (
    SELECT EXISTS (SELECT 1 FROM fin_journals WHERE journal_type = 'OPENING' AND status = 'POSTED') AS live
), books AS (
    -- Valued stock per item, and the batch to sell next (earliest expiry with stock).
    SELECT p.sku, COALESCE(SUM(l.qty_remaining), 0) AS qty,
           (SELECT b.batch_number FROM fin_cost_layers l2 JOIN fin_batches b ON b.id = l2.batch_id
             WHERE l2.sku = p.sku AND l2.qty_remaining > 0 ORDER BY b.expiry_date NULLS LAST LIMIT 1) AS next_batch,
           (SELECT MIN(b.expiry_date) FROM fin_cost_layers l2 JOIN fin_batches b ON b.id = l2.batch_id
             WHERE l2.sku = p.sku AND l2.qty_remaining > 0) AS next_expiry
    FROM fin_products p LEFT JOIN fin_cost_layers l ON l.legal_entity_id = p.legal_entity_id AND l.sku = p.sku
    GROUP BY p.sku
), latest_inv_batch AS (
    SELECT batch_id FROM sage_inventory_snapshot ORDER BY imported_at DESC LIMIT 1
), stock_agg AS (
    -- The latest Sage batch lists each item/warehouse twice: count each row once.
    SELECT d.sku, SUM(d.quantity) AS baseline_qty, MAX(d.imported_at) AS baseline_ts
    FROM (SELECT DISTINCT ON (s.sku, COALESCE(s.warehouse_id, ''), COALESCE(s.batch_number, ''))
                 s.sku, s.quantity, s.imported_at
          FROM sage_inventory_snapshot s JOIN latest_inv_batch lb ON s.batch_id = lb.batch_id
          ORDER BY s.sku, COALESCE(s.warehouse_id, ''), COALESCE(s.batch_number, ''), s.imported_at DESC) d
    GROUP BY d.sku
), event_deltas AS (
    SELECT e.sku, SUM(e.quantity_change) AS delta_qty, COUNT(*) AS event_count
    FROM placeware_inventory_events e
    LEFT JOIN stock_agg sa ON sa.sku = e.sku
    WHERE e.created_at > COALESCE(sa.baseline_ts, '-infinity'::timestamptz)
    GROUP BY e.sku
)
SELECT li.sku, li.name, li.category, li.unit, li.cost_price, li.selling_price, li.vat_category, li.reorder_level, li.is_active,
       CASE WHEN bl.live AND bk.sku IS NOT NULL THEN COALESCE(bk.next_expiry, li.expiry_date) ELSE li.expiry_date END AS expiry_date,
       CASE WHEN bl.live AND bk.sku IS NOT NULL THEN COALESCE(bk.next_batch, li.batch_number) ELSE li.batch_number END AS batch_number,
       li.company_id,
       CASE WHEN bl.live AND bk.sku IS NOT NULL THEN bk.qty
            ELSE COALESCE(sa.baseline_qty, 0.0) + COALESCE(ed.delta_qty, 0.0) END AS current_stock,
       (sa.sku IS NOT NULL) AS has_sage_qty,
       COALESCE(ed.event_count, 0::bigint) AS events_since_baseline,
       CASE WHEN bl.live AND bk.sku IS NOT NULL THEN 'ACE Books' ELSE 'Sage baseline + events' END AS stock_source
FROM latest_items li
CROSS JOIN books_live bl
LEFT JOIN books bk ON bk.sku = li.sku
LEFT JOIN stock_agg sa ON sa.sku = li.sku
LEFT JOIN event_deltas ed ON ed.sku = li.sku;


-- Monthly ledger movement per account (for reports, dashboards and agents).
-- Migrated opening balances carry journal_type OPENING so consumers can keep
-- them out of month-by-month analysis.
CREATE OR REPLACE VIEW v_gl_monthly AS
SELECT g.legal_entity_id, to_char(g.journal_date, 'YYYY-MM') AS period, g.journal_type,
       g.account_code, g.account_name, g.account_type, g.subtype,
       SUM(g.debit) AS debit, SUM(g.credit) AS credit, SUM(g.debit - g.credit) AS net
FROM fin_v_general_ledger g
GROUP BY g.legal_entity_id, to_char(g.journal_date, 'YYYY-MM'), g.journal_type, g.account_code, g.account_name, g.account_type, g.subtype;
