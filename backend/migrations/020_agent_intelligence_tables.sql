-- ============================================================
-- Migration 020 — Agent Intelligence Tables
-- Enables the Email Agent, Calendar Agent, Report Agent, and
-- the universal active-learning memory layer for all agents.
-- Run once against Supabase via the SQL editor or psql.
-- ============================================================

-- ── 1. Email quota tracker (one row per department per day) ──────────────────
CREATE TABLE IF NOT EXISTS placeware_email_quota (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department     TEXT NOT NULL,
    quota_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    sent_count     INT  NOT NULL DEFAULT 0,
    daily_limit    INT  NOT NULL DEFAULT 50,
    updated_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (department, quota_date)
);

-- ── 2. Email send log (full audit trail) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS placeware_email_send_log (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department     TEXT,
    to_email       TEXT NOT NULL,
    subject        TEXT,
    body_preview   TEXT,       -- first 500 chars for debugging
    status         TEXT NOT NULL DEFAULT 'sent',  -- sent | failed | quota_exceeded
    error_detail   TEXT,
    actor_id       TEXT,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- ── 3. Calendar agent learning log ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS placeware_calendar_agent_log (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_text    TEXT,
    parsed_title   TEXT,
    parsed_time    TIMESTAMPTZ,
    parsed_duration_min INT,
    success        BOOLEAN DEFAULT TRUE,
    event_id       UUID,        -- FK to placeware_calendar_events if created
    actor_id       TEXT,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- ── 4. Report memory (progressive improvement store) ─────────────────────────
CREATE TABLE IF NOT EXISTS placeware_report_memory (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type      TEXT NOT NULL,  -- deviation | maintenance | compliance | ...
    intent_text      TEXT,
    full_report      TEXT,
    summary          TEXT,
    findings         JSONB  DEFAULT '[]',
    recommendations  JSONB  DEFAULT '[]',
    quality_score    FLOAT  DEFAULT 0,   -- self-scored 1-10 by the agent
    used_count       INT    DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_report_memory_type ON placeware_report_memory(report_type);
CREATE INDEX IF NOT EXISTS idx_report_memory_score ON placeware_report_memory(quality_score DESC);

-- ── 5. Universal agent memory (with vector search) ───────────────────────────
-- Requires pgvector extension (already enabled for match_documents).
CREATE TABLE IF NOT EXISTS placeware_agent_memory (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name     TEXT NOT NULL,
    memory_type    TEXT NOT NULL DEFAULT 'finding',  -- finding | pattern | recommendation
    content        TEXT NOT NULL,
    embedding      VECTOR(384),
    quality_score  FLOAT  DEFAULT 0.0,
    used_count     INT    DEFAULT 0,
    last_used_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON placeware_agent_memory(agent_name);

-- Semantic similarity search function for agent memories
CREATE OR REPLACE FUNCTION match_agent_memories(
    p_agent_name     TEXT,
    query_embedding  VECTOR(384),
    match_threshold  FLOAT DEFAULT 0.70,
    match_count      INT   DEFAULT 5
)
RETURNS TABLE (
    id            UUID,
    agent_name    TEXT,
    memory_type   TEXT,
    content       TEXT,
    quality_score FLOAT,
    similarity    FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        id,
        agent_name,
        memory_type,
        content,
        quality_score,
        1 - (embedding <=> query_embedding) AS similarity
    FROM placeware_agent_memory
    WHERE
        agent_name = p_agent_name
        AND embedding IS NOT NULL
        AND 1 - (embedding <=> query_embedding) >= match_threshold
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;
