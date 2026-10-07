-- 122: Inventory & Quality connected to ACE Books and the calendar.
--
-- The QMS records stay the single source for their own facts; these columns
-- let them carry a real date (so the calendar can show and move them) and a
-- link to the ACE Books record they act on:
--   recall_cases.fin_recall_id        -> fin_recalls (batch frozen, customers traced)
--   nafdac_batch_registry.fin_batch_id -> fin_batches (release = AVAILABLE, reject = QUARANTINED)
-- The calendar reads these tables directly (services/quality_hub.calendar_feed);
-- it does not copy them into placeware_calendar_events.

-- Audits get a real scheduled date (month_due/year stay for the annual plan view).
ALTER TABLE audit_schedule ADD COLUMN IF NOT EXISTS scheduled_date date;
UPDATE audit_schedule SET scheduled_date = make_date(year, COALESCE(month_due, 1), 1) WHERE scheduled_date IS NULL;

-- Recalls: link to ACE Books, the product code, when the stock is due back.
ALTER TABLE recall_cases
    ADD COLUMN IF NOT EXISTS fin_recall_id        uuid,
    ADD COLUMN IF NOT EXISTS sku                  text,
    ADD COLUMN IF NOT EXISTS expected_return_date date;

-- Deviations: when the investigation / CAPA should be closed.
ALTER TABLE deviation_reports ADD COLUMN IF NOT EXISTS target_close_date date;
UPDATE deviation_reports SET target_close_date = investigation_start_date + 30
 WHERE target_close_date IS NULL AND status <> 'closed';

-- QC batch release: which ACE Books product/batch, when it is expected, how many, from which stock order.
ALTER TABLE nafdac_batch_registry
    ADD COLUMN IF NOT EXISTS sku                   text,
    ADD COLUMN IF NOT EXISTS fin_batch_id          uuid,
    ADD COLUMN IF NOT EXISTS expected_arrival_date date,
    ADD COLUMN IF NOT EXISTS quantity              numeric,
    ADD COLUMN IF NOT EXISTS expiry_date           date,
    ADD COLUMN IF NOT EXISTS stock_order_id        uuid;

CREATE INDEX IF NOT EXISTS idx_nafdac_registry_sku_batch ON nafdac_batch_registry (sku, batch_number);
CREATE INDEX IF NOT EXISTS idx_recall_cases_fin ON recall_cases (fin_recall_id);
