-- Migration: 039_raw_import_payloads.sql
-- Purpose: Store raw import payloads for lineage tracking and reprocessing
-- Part of the enterprise data pipeline (Layer 1: Ingestion)

-- Raw import payloads table
-- Stores immutable raw data as received from external sources
CREATE TABLE IF NOT EXISTS raw_import_payloads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_id UUID NOT NULL,
    source_system VARCHAR(100) NOT NULL,
    content_type VARCHAR(100) DEFAULT 'application/octet-stream',
    raw_data JSONB NOT NULL,
    filename VARCHAR(500),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash VARCHAR(64) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Indexing for common queries
    CONSTRAINT raw_import_payloads_content_hash_key UNIQUE (content_hash)
);

-- Index for querying by ingestion
CREATE INDEX IF NOT EXISTS idx_raw_import_payloads_ingestion_id 
ON raw_import_payloads(ingestion_id);

-- Index for querying by source system
CREATE INDEX IF NOT EXISTS idx_raw_import_payloads_source_system 
ON raw_import_payloads(source_system);

-- Index for querying by time
CREATE INDEX IF NOT EXISTS idx_raw_import_payloads_received_at 
ON raw_import_payloads(received_at);

-- Index on metadata for dataset queries
CREATE INDEX IF NOT EXISTS idx_raw_import_payloads_metadata_dataset 
ON raw_import_payloads USING gin ((metadata->'dataset_name'));

-- Pipeline execution audit log
-- Tracks full pipeline execution with lineage
CREATE TABLE IF NOT EXISTS pipeline_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL UNIQUE,
    ingestion_id UUID,
    batch_id UUID,
    source_system VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'running',
    layers_completed TEXT[] DEFAULT '{}',
    layers_failed TEXT[] DEFAULT '{}',
    lineage JSONB DEFAULT '{}'::jsonb,
    audit_trail JSONB DEFAULT '[]'::jsonb,
    errors JSONB DEFAULT '[]'::jsonb,
    warnings JSONB DEFAULT '[]'::jsonb,
    execution_time_ms DECIMAL(12, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Index for querying by status
CREATE INDEX IF NOT EXISTS idx_pipeline_executions_status 
ON pipeline_executions(status);

-- Index for querying by batch_id
CREATE INDEX IF NOT EXISTS idx_pipeline_executions_batch_id 
ON pipeline_executions(batch_id);

-- Computed features storage
-- Stores KPIs and derived metrics from feature computation layer
CREATE TABLE IF NOT EXISTS computed_features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL,
    batch_id UUID,
    feature_name VARCHAR(200) NOT NULL,
    feature_value JSONB NOT NULL,
    unit VARCHAR(50),
    category VARCHAR(100),
    dataset VARCHAR(100),
    metadata JSONB DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for querying features by pipeline
CREATE INDEX IF NOT EXISTS idx_computed_features_pipeline_id 
ON computed_features(pipeline_id);

-- Index for querying features by name
CREATE INDEX IF NOT EXISTS idx_computed_features_name 
ON computed_features(feature_name);

-- Index for querying features by category
CREATE INDEX IF NOT EXISTS idx_computed_features_category 
ON computed_features(category);

-- Intelligence insights storage
-- Stores generated insights from intelligence layer
CREATE TABLE IF NOT EXISTS intelligence_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL,
    batch_id UUID,
    insight_type VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL DEFAULT 'info',
    data JSONB DEFAULT '{}'::jsonb,
    recommendations JSONB DEFAULT '[]'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for querying insights by pipeline
CREATE INDEX IF NOT EXISTS idx_intelligence_insights_pipeline_id 
ON intelligence_insights(pipeline_id);

-- Index for querying insights by type
CREATE INDEX IF NOT EXISTS idx_intelligence_insights_type 
ON intelligence_insights(insight_type);

-- Index for querying insights by severity
CREATE INDEX IF NOT EXISTS idx_intelligence_insights_severity 
ON intelligence_insights(severity);

-- Risk scores storage
-- Stores risk assessments from intelligence layer
CREATE TABLE IF NOT EXISTS risk_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL,
    batch_id UUID,
    category VARCHAR(100) NOT NULL,
    score DECIMAL(5, 4) NOT NULL,
    level VARCHAR(20) NOT NULL,
    factors JSONB DEFAULT '[]'::jsonb,
    recommendations JSONB DEFAULT '[]'::jsonb,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for querying risk scores by pipeline
CREATE INDEX IF NOT EXISTS idx_risk_scores_pipeline_id 
ON risk_scores(pipeline_id);

-- Index for querying risk scores by level
CREATE INDEX IF NOT EXISTS idx_risk_scores_level 
ON risk_scores(level);

-- Trigger audit log
-- Stores fired triggers from intelligence layer
CREATE TABLE IF NOT EXISTS trigger_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL,
    batch_id UUID,
    trigger_name VARCHAR(200) NOT NULL,
    condition_description TEXT,
    matched BOOLEAN NOT NULL DEFAULT false,
    action VARCHAR(200),
    priority INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for querying triggered actions
CREATE INDEX IF NOT EXISTS idx_trigger_audit_log_matched 
ON trigger_audit_log(matched) WHERE matched = true;

-- Index for querying triggers by pipeline
CREATE INDEX IF NOT EXISTS idx_trigger_audit_log_pipeline_id 
ON trigger_audit_log(pipeline_id);

COMMENT ON TABLE raw_import_payloads IS 'Immutable raw data payloads from external sources (Layer 1: Ingestion)';
COMMENT ON TABLE pipeline_executions IS 'Full pipeline execution audit trail with lineage';
COMMENT ON TABLE computed_features IS 'KPIs and derived metrics from feature computation (Layer 4)';
COMMENT ON TABLE intelligence_insights IS 'Generated insights from intelligence layer (Layer 5)';
COMMENT ON TABLE risk_scores IS 'Risk assessments from intelligence layer (Layer 5)';
COMMENT ON TABLE trigger_audit_log IS 'Fired triggers and actions from intelligence layer (Layer 5)';
