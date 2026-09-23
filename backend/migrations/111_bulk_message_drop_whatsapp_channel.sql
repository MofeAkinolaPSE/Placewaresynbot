-- Migration 111: Drop WhatsApp as a bulk-message channel; fix status vocabulary
--
-- Two problems with crm_bulk_message_jobs, both fixed here:
--
-- 1. WhatsApp was never a production send channel (messaging.py's own header
--    said "whatsapp currently unused by the bulk-message flow"), yet it was
--    the column DEFAULT. SMS and email are the two supported channels, so
--    whatsapp comes out of the CHECK and the default becomes 'sms'.
--
-- 2. The status CHECK only ever allowed queued/processing/completed/failed,
--    but dispatch_job() returned 'sent'/'partial' and the dispatch endpoint
--    wrote that straight back -- so every successful dispatch violated the
--    constraint AFTER the messages had already gone out, leaving the caller
--    with a 500 and the job wrongly marked failed. dispatch_job() now returns
--    'completed'/'failed'; this migration repairs rows written before that.

-- Normalize existing data BEFORE touching the constraints.
UPDATE crm_bulk_message_jobs SET channel = 'sms' WHERE channel = 'whatsapp';
UPDATE crm_bulk_message_jobs SET status  = 'completed' WHERE status IN ('sent', 'partial');

ALTER TABLE crm_bulk_message_jobs
    DROP CONSTRAINT IF EXISTS crm_bulk_message_jobs_channel_check;

ALTER TABLE crm_bulk_message_jobs
    ADD CONSTRAINT crm_bulk_message_jobs_channel_check
    CHECK (channel IN ('email', 'sms'));

ALTER TABLE crm_bulk_message_jobs
    ALTER COLUMN channel SET DEFAULT 'sms';
