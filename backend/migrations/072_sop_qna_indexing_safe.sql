-- Migration 072: SOP / QnA Indexing Extensions (safe version of 071)
-- Adds doc_type, sop_reference, document_title, chunk_index columns to
-- qna_pairs ONLY if that table exists.  Safe to run against databases that
-- were seeded without pgvector / qna_pairs.

BEGIN;

DO $$
BEGIN
  -- Guard: skip entirely if qna_pairs doesn't exist in this DB
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'qna_pairs'
  ) THEN
    RAISE NOTICE 'qna_pairs table not found — skipping SOP column extensions.';
    RETURN;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'doc_type'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN doc_type TEXT DEFAULT 'general';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'sop_reference'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN sop_reference TEXT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'document_title'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN document_title TEXT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'chunk_index'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN chunk_index INTEGER DEFAULT 0;
  END IF;
END $$;

-- Indexes (only created if qna_pairs table exists)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'qna_pairs'
  ) THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_qna_pairs_doc_type ON qna_pairs(doc_type)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_qna_pairs_sop_ref ON qna_pairs(sop_reference) WHERE sop_reference IS NOT NULL';
  END IF;
END $$;

COMMIT;
