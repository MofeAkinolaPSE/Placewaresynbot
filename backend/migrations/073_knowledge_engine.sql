-- ============================================================
-- Migration 073: SynBot Knowledge Engine
-- Creates the four tables that power the RAG Knowledge Engine:
--   ingested_documents  — registry of all ingested files (dedup via hash)
--   knowledge_chunks    — chunked + embedded document content (pgvector)
--   knowledge_gaps      — queries where retrieval confidence was too low
--   synbot_memory       — solved investigations stored for fast reuse
-- ============================================================

-- Enable pgvector extension (idempotent)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Drop pre-existing tables if embedding column has wrong dimensions ────
-- Handles the case where these tables were created manually before this
-- migration (e.g. with vector(1536) for OpenAI). Since knowledge-engine
-- data is re-seedable via the ingestion pipeline, a clean rebuild is safe.
DO $$
BEGIN
    -- Check if knowledge_chunks exists with wrong embedding dimensions
    IF EXISTS (
        SELECT 1
        FROM   information_schema.columns
        WHERE  table_name  = 'knowledge_chunks'
          AND  column_name = 'embedding'
          AND  udt_name   != 'vector'   -- catches any mismatch
    ) OR EXISTS (
        SELECT 1
        FROM   pg_attribute a
        JOIN   pg_class     c ON c.oid = a.attrelid
        JOIN   pg_type      t ON t.oid = a.atttypid
        WHERE  c.relname  = 'knowledge_chunks'
          AND  a.attname  = 'embedding'
          AND  t.typname  = 'vector'
          AND  a.atttypmod <> 384        -- wrong dimension stored in typmod
    ) THEN
        DROP TABLE IF EXISTS knowledge_chunks    CASCADE;
        DROP TABLE IF EXISTS ingested_documents  CASCADE;
        RAISE NOTICE 'Dropped mismatched knowledge tables – will recreate with vector(384).';
    END IF;
END;
$$;

-- ── ingested_documents ─────────────────────────────────────────────────────
-- One row per source document. file_hash enforces deduplication.
CREATE TABLE IF NOT EXISTS ingested_documents (
    id              SERIAL PRIMARY KEY,
    document_id     TEXT        NOT NULL UNIQUE,          -- short hash-based ID
    file_name       TEXT        NOT NULL,
    file_path       TEXT,
    file_hash       TEXT        NOT NULL UNIQUE,          -- SHA-256; prevents re-ingest
    document_type   TEXT        NOT NULL DEFAULT 'general_document',
    department      TEXT        NOT NULL DEFAULT 'general',
    source          TEXT        NOT NULL DEFAULT 'manual',    -- 'manual' | 'generated' | 'upload'
    metadata        JSONB       NOT NULL DEFAULT '{}',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingested_documents_type
    ON ingested_documents (document_type);

CREATE INDEX IF NOT EXISTS idx_ingested_documents_department
    ON ingested_documents (department);

CREATE INDEX IF NOT EXISTS idx_ingested_documents_source
    ON ingested_documents (source);

-- ── knowledge_chunks ───────────────────────────────────────────────────────
-- One row per text chunk extracted from a document.
-- embedding is a 384-dim vector produced by FastEmbed all-MiniLM-L6-v2.
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id              SERIAL PRIMARY KEY,
    document_id     TEXT        NOT NULL
                        REFERENCES ingested_documents (document_id)
                        ON DELETE CASCADE,
    chunk_index     INTEGER     NOT NULL,
    content         TEXT        NOT NULL,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    embedding       vector(384),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- GIN index for fast JSONB metadata filtering
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_metadata
    ON knowledge_chunks USING GIN (metadata);

-- ivfflat index for approximate nearest-neighbour vector search.
-- lists=100 is a good default for up to ~1 M rows; tune upward as data grows.
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id
    ON knowledge_chunks (document_id);

-- ── knowledge_gaps ─────────────────────────────────────────────────────────
-- Logged when the best retrieval similarity falls below the configured
-- threshold. Surfaces blind spots so missing documents can be ingested.
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id              SERIAL PRIMARY KEY,
    query           TEXT        NOT NULL,
    agent           TEXT,                                  -- which agent triggered the search
    department      TEXT,
    document_type   TEXT,
    best_similarity FLOAT,                                 -- highest similarity score found
    status          TEXT        NOT NULL DEFAULT 'pending',  -- 'pending' | 'resolved' | 'ignored'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_status
    ON knowledge_gaps (status);

CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_department
    ON knowledge_gaps (department);

-- ── synbot_memory ──────────────────────────────────────────────────────────
-- Stores solved investigations, detected patterns, and key decisions.
-- Checked before vector retrieval as a fast-path for known topics.
CREATE TABLE IF NOT EXISTS synbot_memory (
    id              SERIAL PRIMARY KEY,
    memory_type     TEXT        NOT NULL,   -- 'investigation' | 'pattern' | 'decision'
    topic           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    source_query    TEXT,
    agent           TEXT,
    department      TEXT,
    confidence      FLOAT       NOT NULL DEFAULT 1.0,
    hit_count       INTEGER     NOT NULL DEFAULT 0,        -- how many times retrieved
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_synbot_memory_type
    ON synbot_memory (memory_type);

CREATE INDEX IF NOT EXISTS idx_synbot_memory_topic
    ON synbot_memory (topic);

CREATE INDEX IF NOT EXISTS idx_synbot_memory_confidence
    ON synbot_memory (confidence DESC);

-- Auto-update updated_at on any row change
CREATE OR REPLACE FUNCTION update_synbot_memory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_synbot_memory_updated_at ON synbot_memory;
CREATE TRIGGER trg_synbot_memory_updated_at
    BEFORE UPDATE ON synbot_memory
    FOR EACH ROW EXECUTE FUNCTION update_synbot_memory_timestamp();

-- ── match_knowledge_chunks RPC ─────────────────────────────────────────────
-- Called by knowledge_service.py for cosine-similarity retrieval.
-- Returns chunks ordered by similarity DESC.
CREATE OR REPLACE FUNCTION match_knowledge_chunks(
    query_embedding vector(384),
    match_threshold  FLOAT   DEFAULT 0.55,
    match_count      INTEGER DEFAULT 20,
    filter_department TEXT   DEFAULT NULL,
    filter_doc_type   TEXT   DEFAULT NULL
)
RETURNS TABLE (
    id           INT,
    document_id  TEXT,
    chunk_index  INT,
    content      TEXT,
    metadata     JSONB,
    similarity   FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        kc.id,
        kc.document_id,
        kc.chunk_index,
        kc.content,
        kc.metadata,
        1 - (kc.embedding <=> query_embedding) AS similarity
    FROM knowledge_chunks kc
    WHERE
        kc.embedding IS NOT NULL
        AND (1 - (kc.embedding <=> query_embedding)) >= match_threshold
        AND (filter_department IS NULL
             OR kc.metadata->>'department' = filter_department)
        AND (filter_doc_type IS NULL
             OR kc.metadata->>'document_type' = filter_doc_type)
    ORDER BY kc.embedding <=> query_embedding
    LIMIT match_count;
$$;
