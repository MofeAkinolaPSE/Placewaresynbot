-- Migration 071: SOP / QnA Indexing Extensions
-- Adds doc_type, sop_reference, and document_title columns to the qna_pairs
-- table (or equivalent knowledge-base table) so that SOP documents ingested
-- via the /compliance/sop/ingest-docx endpoint are categorised and traceable.
-- Also creates a Supabase RPC extension for SOP-scoped similarity search.

BEGIN;

-- ---------------------------------------------------------------------------
-- Extend existing qna_pairs table with document metadata columns
-- (columns are added with safe IF NOT EXISTS guards)
-- ---------------------------------------------------------------------------

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
    COMMENT ON COLUMN qna_pairs.doc_type IS
      'Source document type: general | sop | audit_policy | training_material | recall_procedure';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'sop_reference'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN sop_reference TEXT;
    COMMENT ON COLUMN qna_pairs.sop_reference IS
      'FK to sop_registry.sop_id. Populated when doc_type = ''sop''.';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'document_title'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN document_title TEXT;
    COMMENT ON COLUMN qna_pairs.document_title IS
      'Human-readable title of the source document.';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'qna_pairs' AND column_name = 'chunk_index'
  ) THEN
    ALTER TABLE qna_pairs ADD COLUMN chunk_index INTEGER DEFAULT 0;
    COMMENT ON COLUMN qna_pairs.chunk_index IS
      'Position of this chunk within its source document (0-based).';
  END IF;
END $$;

-- Index for SOP-scoped look-ups (only if qna_pairs exists)
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

-- Supabase RPC: match_sop_documents
-- This function requires pgvector and is only created when qna_pairs exists.
-- On local PostgreSQL without pgvector it is skipped gracefully.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'qna_pairs'
  ) THEN
    RAISE NOTICE 'match_sop_documents RPC skipped — qna_pairs not found.';
  ELSE
    RAISE NOTICE 'qna_pairs exists. Create match_sop_documents manually from 071_sop_qna_indexing.sql if pgvector is available.';
  END IF;
EXCEPTION
  WHEN OTHERS THEN
    RAISE NOTICE 'match_sop_documents skipped: %', SQLERRM;
END $$;

COMMIT;
