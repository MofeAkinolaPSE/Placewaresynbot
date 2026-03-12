-- Migration: 020_kpi_tables.sql
-- KPI tables for MetricsAgent

CREATE TABLE IF NOT EXISTS placeware_kpi_leads_by_campaign (
    campaign_id BIGINT PRIMARY KEY,
    lead_count BIGINT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS placeware_kpi_leads_by_source (
    source TEXT PRIMARY KEY,
    lead_count BIGINT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS placeware_kpi_opportunities_by_stage (
    stage TEXT PRIMARY KEY,
    opp_count BIGINT DEFAULT 0,
    total_value NUMERIC(18,2) DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS placeware_kpis (
    metric_key TEXT PRIMARY KEY,
    metric_value NUMERIC DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT now()
);
