-- Migration 070: QMS Compliance Schema
-- Adds Quality Management System tables: SOP registry, audit schedule,
-- compliance activity log, equipment registry, maintenance schedule,
-- deviation reports (CAPA), recall cases, and document archive.
--
-- Document archive supports hybrid storage: local filesystem + cloud (Supabase/S3).

BEGIN;

-- ---------------------------------------------------------------------------
-- SOP Registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sop_registry (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sop_id                TEXT UNIQUE NOT NULL,           -- e.g. "SOP-QC-001"
  title                 TEXT NOT NULL,
  category              TEXT NOT NULL,                  -- storage|qc|distribution|warehouse|equipment|deviation|hr
  version               TEXT NOT NULL DEFAULT '1.0',
  effective_from        DATE,
  owner_department      TEXT NOT NULL,
  status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','retired','under_review','draft')),
  document_path         TEXT,                           -- path of uploaded original docx
  description           TEXT,
  review_interval_days  INTEGER DEFAULT 365,
  last_reviewed_at      TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sop_registry_category ON sop_registry(category);
CREATE INDEX IF NOT EXISTS idx_sop_registry_status   ON sop_registry(status);
CREATE INDEX IF NOT EXISTS idx_sop_registry_dept     ON sop_registry(owner_department);

-- ---------------------------------------------------------------------------
-- Audit Schedule
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_schedule (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_type          TEXT NOT NULL,                    -- e.g. "Self Audit", "Cold Chain Audit"
  risk_level          TEXT NOT NULL DEFAULT 'medium'
                        CHECK (risk_level IN ('low','medium','high','critical')),
  frequency           TEXT NOT NULL DEFAULT 'monthly'
                        CHECK (frequency IN ('monthly','quarterly','biannual','annual','ad_hoc')),
  department          TEXT NOT NULL,
  month_due           INTEGER CHECK (month_due BETWEEN 1 AND 12),
  year                INTEGER NOT NULL DEFAULT EXTRACT(YEAR FROM now())::integer,
  assigned_to         TEXT,
  status              TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled','in_progress','completed','overdue','skipped')),
  report_document_id  UUID,                             -- FK to document_archive (set after generation)
  notes               TEXT,
  completed_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_schedule_dept_year  ON audit_schedule(department, year);
CREATE INDEX IF NOT EXISTS idx_audit_schedule_status     ON audit_schedule(status);
CREATE INDEX IF NOT EXISTS idx_audit_schedule_month_year ON audit_schedule(month_due, year);

-- ---------------------------------------------------------------------------
-- Compliance Activity Log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance_activity_log (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  activity_name       TEXT NOT NULL,                    -- e.g. "Monthly Fumigation"
  sop_reference       TEXT,                             -- sop_registry.sop_id
  scheduled_date      DATE NOT NULL,
  completion_date     DATE,
  status              TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled','completed','missed','overdue','deferred')),
  department          TEXT,
  responsible_staff   TEXT,
  completed_by        TEXT,
  notes               TEXT,
  deviation_triggered BOOLEAN NOT NULL DEFAULT FALSE,
  deviation_id        UUID,                             -- FK to deviation_reports (set when triggered)
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_activity_status    ON compliance_activity_log(status);
CREATE INDEX IF NOT EXISTS idx_compliance_activity_scheduled ON compliance_activity_log(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_compliance_activity_dept      ON compliance_activity_log(department);
CREATE INDEX IF NOT EXISTS idx_compliance_activity_sop       ON compliance_activity_log(sop_reference)
  WHERE sop_reference IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Equipment Registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equipment_registry (
  id                           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  equipment_name               TEXT NOT NULL,
  equipment_type               TEXT NOT NULL,           -- refrigerator|cold_room|temperature_device|generator|other
  location                     TEXT NOT NULL,
  serial_number                TEXT,
  model                        TEXT,
  status                       TEXT NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active','decommissioned','under_maintenance','retired')),
  last_calibration_date        DATE,
  calibration_interval_days    INTEGER DEFAULT 365,
  last_maintenance_date        DATE,
  maintenance_interval_days    INTEGER DEFAULT 90,
  notes                        TEXT,
  created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_equipment_registry_type     ON equipment_registry(equipment_type);
CREATE INDEX IF NOT EXISTS idx_equipment_registry_status   ON equipment_registry(status);
CREATE INDEX IF NOT EXISTS idx_equipment_registry_location ON equipment_registry(location);

-- ---------------------------------------------------------------------------
-- Maintenance Schedule
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS maintenance_schedule (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  equipment_id          UUID NOT NULL REFERENCES equipment_registry(id) ON DELETE CASCADE,
  maintenance_type      TEXT NOT NULL DEFAULT 'preventive'
                          CHECK (maintenance_type IN ('preventive','calibration','repair','inspection')),
  interval_days         INTEGER NOT NULL DEFAULT 90,
  last_maintenance_date DATE,
  next_maintenance_date DATE NOT NULL,
  status                TEXT NOT NULL DEFAULT 'scheduled'
                          CHECK (status IN ('scheduled','completed','overdue','cancelled')),
  certificate_document_id UUID,
  performed_by          TEXT,
  completion_notes      TEXT,
  scheduled_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at          TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maintenance_schedule_equipment  ON maintenance_schedule(equipment_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_schedule_next_date  ON maintenance_schedule(next_maintenance_date);
CREATE INDEX IF NOT EXISTS idx_maintenance_schedule_status     ON maintenance_schedule(status);

-- ---------------------------------------------------------------------------
-- Deviation Reports (CAPA)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deviation_reports (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deviation_id             TEXT UNIQUE NOT NULL,        -- e.g. "DEV-2026-009"
  classification           TEXT NOT NULL DEFAULT 'minor'
                             CHECK (classification IN ('minor','major','critical')),
  trigger_type             TEXT NOT NULL
                             CHECK (trigger_type IN (
                               'missed_maintenance','audit_failure','inspection_failed',
                               'temperature_breach','manual','missed_activity','nafdac_violation'
                             )),
  trigger_ref              TEXT,                        -- id of triggering entity
  investigation_start_date DATE NOT NULL DEFAULT CURRENT_DATE,
  observation              TEXT NOT NULL,
  impact_assessment        TEXT,
  recommendations          TEXT,
  responsible_department   TEXT NOT NULL,
  responsible_person       TEXT,
  status                   TEXT NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open','under_investigation','closed','escalated')),
  capa_actions             JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{action,owner,due_date,status}]
  report_document_id       UUID,
  closed_at                TIMESTAMPTZ,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deviation_reports_status         ON deviation_reports(status);
CREATE INDEX IF NOT EXISTS idx_deviation_reports_dept           ON deviation_reports(responsible_department);
CREATE INDEX IF NOT EXISTS idx_deviation_reports_trigger        ON deviation_reports(trigger_type);
CREATE INDEX IF NOT EXISTS idx_deviation_reports_classification ON deviation_reports(classification);

-- ---------------------------------------------------------------------------
-- Recall Cases
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recall_cases (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  recall_id                TEXT UNIQUE NOT NULL,        -- e.g. "RECALL-2026-001"
  batch_number             TEXT NOT NULL,
  product_name             TEXT NOT NULL,
  recall_reason            TEXT NOT NULL,
  initiation_date          DATE NOT NULL DEFAULT CURRENT_DATE,
  scope                    TEXT NOT NULL DEFAULT 'voluntary'
                             CHECK (scope IN ('voluntary','mandatory')),
  status                   TEXT NOT NULL DEFAULT 'initiated'
                             CHECK (status IN ('initiated','in_progress','completed','closed')),
  regulatory_authority     TEXT DEFAULT 'NAFDAC',
  distribution_data        JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{customer_id,name,qty,location,delivered_at}]
  notice_document_id       UUID,
  investigation_document_id UUID,
  trace_document_id        UUID,
  resolved_at              TIMESTAMPTZ,
  created_by               TEXT,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recall_cases_status     ON recall_cases(status);
CREATE INDEX IF NOT EXISTS idx_recall_cases_batch      ON recall_cases(batch_number);
CREATE INDEX IF NOT EXISTS idx_recall_cases_initiation ON recall_cases(initiation_date DESC);

-- ---------------------------------------------------------------------------
-- Document Archive (generated compliance documents â€” hybrid storage)
-- file_path    â†’ local filesystem path (when storage_backend='local')
-- cloud_key    â†’ object storage key (when storage_backend='supabase'|'s3')
-- download_url â†’ always populated: relative API path (local) or pre-signed URL (cloud)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_archive (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_type         TEXT NOT NULL
                     CHECK (doc_type IN (
                       'audit_report','deviation_report','maintenance_report',
                       'recall_notice','recall_investigation','recall_distribution_trace',
                       'sop_document','other'
                     )),
  title            TEXT NOT NULL,
  format           TEXT NOT NULL DEFAULT 'pdf'
                     CHECK (format IN ('pdf','docx','xlsx','csv')),
  file_path        TEXT,                                -- populated for local backend
  cloud_key        TEXT,                                -- populated for cloud backend
  storage_backend  TEXT NOT NULL DEFAULT 'local'
                     CHECK (storage_backend IN ('local','supabase','s3')),
  download_url     TEXT,                                -- pre-signed (cloud) or /documents/archive/{id}/download (local)
  generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  generated_by     TEXT,
  related_id       TEXT,                                -- id of related entity
  related_type     TEXT,                                -- 'deviation_report'|'recall_case'|'audit_schedule'|etc.
  expires_at       TIMESTAMPTZ,                         -- for time-limited signed URLs
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_archive_type      ON document_archive(doc_type);
CREATE INDEX IF NOT EXISTS idx_document_archive_related   ON document_archive(related_type, related_id);
CREATE INDEX IF NOT EXISTS idx_document_archive_generated ON document_archive(generated_at DESC);

-- ---------------------------------------------------------------------------
-- Auto-update triggers
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION tg_qms_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'sop_registry_updated_at') THEN
    CREATE TRIGGER sop_registry_updated_at BEFORE UPDATE ON sop_registry
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_schedule_updated_at') THEN
    CREATE TRIGGER audit_schedule_updated_at BEFORE UPDATE ON audit_schedule
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'compliance_activity_log_updated_at') THEN
    CREATE TRIGGER compliance_activity_log_updated_at BEFORE UPDATE ON compliance_activity_log
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'equipment_registry_updated_at') THEN
    CREATE TRIGGER equipment_registry_updated_at BEFORE UPDATE ON equipment_registry
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'maintenance_schedule_updated_at') THEN
    CREATE TRIGGER maintenance_schedule_updated_at BEFORE UPDATE ON maintenance_schedule
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'deviation_reports_updated_at') THEN
    CREATE TRIGGER deviation_reports_updated_at BEFORE UPDATE ON deviation_reports
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'recall_cases_updated_at') THEN
    CREATE TRIGGER recall_cases_updated_at BEFORE UPDATE ON recall_cases
      FOR EACH ROW EXECUTE FUNCTION tg_qms_set_updated_at();
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
ALTER TABLE sop_registry             ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_schedule           ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_activity_log  ENABLE ROW LEVEL SECURITY;
ALTER TABLE equipment_registry       ENABLE ROW LEVEL SECURITY;
ALTER TABLE maintenance_schedule     ENABLE ROW LEVEL SECURITY;
ALTER TABLE deviation_reports        ENABLE ROW LEVEL SECURITY;
ALTER TABLE recall_cases             ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_archive         ENABLE ROW LEVEL SECURITY;

-- Admin: full CRUD
DROP POLICY IF EXISTS admin_all_sop_registry ON sop_registry;
CREATE POLICY admin_all_sop_registry ON sop_registry
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_audit_schedule ON audit_schedule;
CREATE POLICY admin_all_audit_schedule ON audit_schedule
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_compliance_activity ON compliance_activity_log;
CREATE POLICY admin_all_compliance_activity ON compliance_activity_log
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_equipment_registry ON equipment_registry;
CREATE POLICY admin_all_equipment_registry ON equipment_registry
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_maintenance_schedule ON maintenance_schedule;
CREATE POLICY admin_all_maintenance_schedule ON maintenance_schedule
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_deviation_reports ON deviation_reports;
CREATE POLICY admin_all_deviation_reports ON deviation_reports
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_recall_cases ON recall_cases;
CREATE POLICY admin_all_recall_cases ON recall_cases
  FOR ALL  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS admin_all_document_archive ON document_archive;
CREATE POLICY admin_all_document_archive ON document_archive
  FOR ALL  USING (true) WITH CHECK (true);

-- All authenticated users: read access
DROP POLICY IF EXISTS read_sop_registry ON sop_registry;
CREATE POLICY read_sop_registry ON sop_registry FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_audit_schedule ON audit_schedule;
CREATE POLICY read_audit_schedule ON audit_schedule FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_compliance_activity ON compliance_activity_log;
CREATE POLICY read_compliance_activity ON compliance_activity_log FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_equipment_registry ON equipment_registry;
CREATE POLICY read_equipment_registry ON equipment_registry FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_maintenance_schedule ON maintenance_schedule;
CREATE POLICY read_maintenance_schedule ON maintenance_schedule FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_deviation_reports ON deviation_reports;
CREATE POLICY read_deviation_reports ON deviation_reports FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_recall_cases ON recall_cases;
CREATE POLICY read_recall_cases ON recall_cases FOR SELECT  USING (true);

DROP POLICY IF EXISTS read_document_archive ON document_archive;
CREATE POLICY read_document_archive ON document_archive FOR SELECT  USING (true);

COMMIT;
