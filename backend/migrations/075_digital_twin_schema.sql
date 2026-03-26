-- =============================================================================
-- Migration 075 — Digital Twin Schema
-- Creates the four tables that represent the System Digital Twin layer.
-- Depends on: placeware_touch_updated_at() from migration 074.
-- =============================================================================

-- Twin node registry — one row per tracked system checkpoint
CREATE TABLE IF NOT EXISTS placeware_twin_nodes (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    node_key     VARCHAR(100) UNIQUE NOT NULL,   -- e.g. "database.ar_snapshot"
    component    VARCHAR(50)  NOT NULL,           -- database | pipeline | api | cache | dashboard | worker
    label        VARCHAR(200) NOT NULL,
    expected_state JSONB      NOT NULL DEFAULT '{}',  -- baseline thresholds / contracts
    actual_state   JSONB      NOT NULL DEFAULT '{}',  -- last observed state
    health_status  VARCHAR(20) NOT NULL DEFAULT 'unknown',  -- healthy | degraded | anomalous | unknown
    last_sync_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Historical snapshots of each node state (time-series)
CREATE TABLE IF NOT EXISTS placeware_twin_state_history (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id      UUID        NOT NULL REFERENCES placeware_twin_nodes(id) ON DELETE CASCADE,
    node_key     VARCHAR(100) NOT NULL,
    snapshot     JSONB        NOT NULL DEFAULT '{}',
    anomaly_score NUMERIC(6,4) DEFAULT 0.0,
    captured_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Anomaly events emitted when expected vs actual state diverges significantly
CREATE TABLE IF NOT EXISTS placeware_twin_anomaly_events (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id        UUID        REFERENCES placeware_twin_nodes(id) ON DELETE SET NULL,
    node_key       VARCHAR(100),
    anomaly_type   VARCHAR(100) NOT NULL,   -- e.g. "stale_data", "empty_table", "null_kpi"
    severity       VARCHAR(20)  NOT NULL DEFAULT 'medium',
    details        JSONB        NOT NULL DEFAULT '{}',
    correlation_id VARCHAR(100),
    detected_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Dependency graph — directional edges between twin nodes
CREATE TABLE IF NOT EXISTS placeware_twin_dependency_edges (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key  VARCHAR(100) NOT NULL,
    target_key  VARCHAR(100) NOT NULL,
    direction   VARCHAR(20)  NOT NULL DEFAULT 'forward',  -- forward | reverse
    weight      NUMERIC(5,2) DEFAULT 1.0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (source_key, target_key)
);

-- ── Indexes ────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_twin_nodes_component
    ON placeware_twin_nodes (component);
CREATE INDEX IF NOT EXISTS idx_twin_nodes_health
    ON placeware_twin_nodes (health_status);
CREATE INDEX IF NOT EXISTS idx_twin_history_node_captured
    ON placeware_twin_state_history (node_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_twin_anomaly_node_key
    ON placeware_twin_anomaly_events (node_key, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_twin_anomaly_unresolved
    ON placeware_twin_anomaly_events (resolved_at)
    WHERE resolved_at IS NULL;

-- ── Triggers ──────────────────────────────────────────────────────────────
CREATE OR REPLACE TRIGGER trg_twin_nodes_updated_at
    BEFORE UPDATE ON placeware_twin_nodes
    FOR EACH ROW EXECUTE FUNCTION placeware_touch_updated_at();

CREATE OR REPLACE TRIGGER trg_twin_anomaly_events_updated_at
    BEFORE UPDATE ON placeware_twin_anomaly_events
    FOR EACH ROW EXECUTE FUNCTION placeware_touch_updated_at();
