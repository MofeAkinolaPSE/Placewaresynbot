-- 103_recall_severity_nafdac_notified.sql
--
-- Fixes a real, pre-existing bug found during the Compliance & QMS retrofit:
-- the "Initiate Product Recall" form has always collected a severity
-- classification and a "NAFDAC has been notified" checkbox, but neither
-- field exists on recall_cases or on the RecallCreate model, so both were
-- silently discarded on every submission (Pydantic ignores undeclared extra
-- fields by default). For a pharma recall, whether the regulator was
-- notified is a genuine compliance record that shouldn't silently vanish.
--
-- Pure additive, defaulted columns -- no existing row is affected.

ALTER TABLE public.recall_cases
  ADD COLUMN IF NOT EXISTS severity text NOT NULL DEFAULT 'major'
    CHECK (severity IN ('critical', 'major', 'minor', 'low'));

ALTER TABLE public.recall_cases
  ADD COLUMN IF NOT EXISTS nafdac_notified boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_recall_cases_severity ON public.recall_cases(severity);
