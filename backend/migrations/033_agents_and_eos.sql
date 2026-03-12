-- 033_agents_and_eos.sql
-- Adds agent registry, executive action log, simulation cache, and reconciliation tables

CREATE TABLE IF NOT EXISTS agent_registry (
    agent_name TEXT PRIMARY KEY,
    description TEXT,
    event_types TEXT[],
    rpc_endpoint TEXT,
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    enabled BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS executive_action_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    executive_id TEXT,
    intent JSONB,
    tasks JSONB,
    actions JSONB,
    simulation BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulation_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT,
    payload JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Reconciliation tables (skeletal)
CREATE TABLE IF NOT EXISTS reconciliations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    snapshot_date DATE,
    status TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS reconciliation_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reconciliation_id UUID REFERENCES reconciliations(id) ON DELETE CASCADE,
    external_ref TEXT,
    internal_ref TEXT,
    amount NUMERIC,
    matched BOOLEAN DEFAULT FALSE,
    payload JSONB
);
