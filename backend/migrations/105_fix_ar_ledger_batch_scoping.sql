-- Migration 105: Fix placeware_ar_ledger — unfiltered across every re-import batch
--
-- placeware_ar_ledger (migration 043) selects from sage_ar_snapshot with no
-- batch_id filter. sage_ar_snapshot is append-only: every CSV/DAT import
-- writes a brand-new batch_id and nothing deletes/supersedes older rows. So
-- this view sums AR across every historical import batch ever loaded — this
-- is the root cause of the ~21x AR-vs-revenue mismatch reported by the
-- Financial Analyst Agent (which reads this view via the `ar_aging` query
-- spec in agents_exec.py), since revenue is correctly read from a single
-- latest GL batch elsewhere (sage_adapter/service.py's kpis()).
--
-- Fix: scope the view to only the most recent sage_ar_snapshot batch, the
-- same pattern _latest_batch_for_table("sage_ar_snapshot") already applies
-- for every other AR-reading function (kpis(), ar_aging_buckets()).

CREATE OR REPLACE VIEW placeware_ar_ledger AS
WITH latest_ar_batch AS (
  SELECT batch_id
  FROM sage_ar_snapshot
  ORDER BY imported_at DESC
  LIMIT 1
)
SELECT
  ar.id,
  ar.batch_id,
  ar.customer_id,
  COALESCE(c.name, ar.customer_id) AS customer_name,
  ar.invoice_id,
  ar.date AS invoice_date,
  ar.due_date,
  ar.amount,
  ar.balance,
  ar.status,
  ar.imported_at,
  c.risk_score AS customer_risk_score
FROM sage_ar_snapshot ar
JOIN latest_ar_batch lb ON ar.batch_id = lb.batch_id
LEFT JOIN customers c ON c.customer_code = ar.customer_id
                      OR c.id::TEXT = ar.customer_id;
