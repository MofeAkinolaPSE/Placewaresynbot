-- Reports written about a specific record (a deviation, recall, audit, sale, customer,
-- product, batch, stock order, or a period). The report remembers what it is about, so
-- the Report Library can show it and each record can list the reports written on it.
BEGIN;
ALTER TABLE placeware_report_memory ADD COLUMN IF NOT EXISTS subject_kind text;
ALTER TABLE placeware_report_memory ADD COLUMN IF NOT EXISTS subject_id text;
ALTER TABLE placeware_report_memory ADD COLUMN IF NOT EXISTS subject_label text;
ALTER TABLE placeware_report_memory ADD COLUMN IF NOT EXISTS author_notes text;
ALTER TABLE placeware_report_memory ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE placeware_report_memory ADD COLUMN IF NOT EXISTS facts jsonb;
CREATE INDEX IF NOT EXISTS idx_report_memory_subject ON placeware_report_memory(subject_kind, subject_id);
COMMIT;
