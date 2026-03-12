-- Migration: 019_crm_and_kg.sql
-- Creates CRM tables, Knowledge Graph tables, and basic agent subscription table

-- ENUMS
DO $$ BEGIN
    CREATE TYPE crm_stage AS ENUM ('new','qualified','proposal','negotiation','won','lost');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE activity_type AS ENUM ('call','email','meeting','followup','note');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE ticket_status AS ENUM ('open','in_progress','escalated','resolved','closed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- CRM: Leads
CREATE TABLE IF NOT EXISTS leads (
    id BIGSERIAL PRIMARY KEY,
    source TEXT,
    industry TEXT,
    assigned_rep UUID,
    stage crm_stage NOT NULL DEFAULT 'new',
    score NUMERIC(5,2) DEFAULT 0,
    expected_value NUMERIC(14,2) DEFAULT 0,
    linked_campaign_id BIGINT,
    metadata JSONB DEFAULT '{}'::jsonb,
    event_ledger_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_assigned_rep ON leads(assigned_rep);
CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);

DO $$ BEGIN
    IF to_regclass('public.event_ledger') IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_leads_event_ledger') THEN
            ALTER TABLE leads
            ADD CONSTRAINT fk_leads_event_ledger
            FOREIGN KEY (event_ledger_id) REFERENCES event_ledger(event_id) ON DELETE SET NULL;
        END IF;
    END IF;
END $$;


-- CRM: Customers
CREATE TABLE IF NOT EXISTS customers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    customer_code TEXT UNIQUE,
    contact_details JSONB DEFAULT '{}'::jsonb,
    risk_score NUMERIC(5,2) DEFAULT 0,
    account_manager UUID,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_customers_account_manager ON customers(account_manager);


-- CRM: Opportunities
CREATE TABLE IF NOT EXISTS opportunities (
    id BIGSERIAL PRIMARY KEY,
    title TEXT,
    customer_id BIGINT REFERENCES customers(id) ON DELETE CASCADE,
    value NUMERIC(14,2) DEFAULT 0,
    probability NUMERIC(5,2) DEFAULT 0,
    expected_close_date DATE,
    linked_inventory_needs JSONB DEFAULT '[]'::jsonb,
    linked_documents JSONB DEFAULT '[]'::jsonb,
    linked_events BIGINT[],
    status TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_opportunities_customer ON opportunities(customer_id);


-- CRM Activity Tracking
CREATE TABLE IF NOT EXISTS crm_activities (
    id BIGSERIAL PRIMARY KEY,
    type activity_type NOT NULL,
    subject TEXT,
    body TEXT,
    customer_id BIGINT REFERENCES customers(id) ON DELETE SET NULL,
    opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,
    project_id BIGINT,
    created_by UUID,
    occurred_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);


-- Support Ticketing
CREATE TABLE IF NOT EXISTS support_tickets (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id) ON DELETE SET NULL,
    issue_type TEXT,
    sla_hours INT,
    assigned_staff UUID,
    status ticket_status NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolution_time INTERVAL,
    metadata JSONB DEFAULT '{}'::jsonb
);


-- Marketing Campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    budget NUMERIC(14,2) DEFAULT 0,
    leads_generated INT DEFAULT 0,
    conversion_rate NUMERIC(5,4) DEFAULT 0,
    revenue_attributed NUMERIC(14,2) DEFAULT 0,
    roi NUMERIC(8,4) DEFAULT 0,
    start_date DATE,
    end_date DATE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);


-- Revenue Forecasts (simple store for weighted forecasts)
CREATE TABLE IF NOT EXISTS revenue_forecasts (
    id BIGSERIAL PRIMARY KEY,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    weighted_forecast NUMERIC(18,2) NOT NULL,
    method JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);


-- Knowledge Graph Nodes & Edges
CREATE TABLE IF NOT EXISTS kg_nodes (
    id BIGSERIAL PRIMARY KEY,
    node_type TEXT NOT NULL,
    ref_table TEXT,
    ref_id BIGINT,
    properties JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_ref ON kg_nodes(ref_table, ref_id);

CREATE TABLE IF NOT EXISTS kg_edges (
    id BIGSERIAL PRIMARY KEY,
    from_node BIGINT NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    to_node BIGINT NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    properties JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);


-- Agent subscriptions (basic)
CREATE TABLE IF NOT EXISTS agent_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);


-- Triggers: keep updated_at current
CREATE OR REPLACE FUNCTION tg_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END; $$;

-- Attach to tables that have updated_at
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'leads_set_updated_at') THEN
        CREATE TRIGGER leads_set_updated_at BEFORE UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'customers_set_updated_at') THEN
        CREATE TRIGGER customers_set_updated_at BEFORE UPDATE ON customers FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'opps_set_updated_at') THEN
        CREATE TRIGGER opps_set_updated_at BEFORE UPDATE ON opportunities FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at();
    END IF;
END $$;

-- Basic helper: create KG node on insert for leads/customers/opportunities
CREATE OR REPLACE FUNCTION kg_create_node()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    new_node_id BIGINT;
BEGIN
    INSERT INTO kg_nodes(node_type, ref_table, ref_id, properties)
    VALUES (TG_TABLE_NAME, TG_TABLE_NAME, NEW.id, to_jsonb(NEW) - 'metadata')
    RETURNING id INTO new_node_id;

    -- Optionally create edge to EventLedger if event_ledger_id present
    IF TG_TABLE_NAME = 'leads' AND NEW.event_ledger_id IS NOT NULL THEN
        -- find EventLedger node if exists
        INSERT INTO kg_edges(from_node, to_node, edge_type, properties)
        VALUES (new_node_id,
            (SELECT id FROM kg_nodes WHERE ref_table='event_ledger' AND ref_id=NEW.event_ledger_id LIMIT 1),
            'LinkedTo',
            jsonb_build_object('via','event_ledger')
               ) ON CONFLICT DO NOTHING;
    END IF;

    RETURN NEW;
END; $$;

-- Attach triggers for creating KG nodes
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'leads_kg_node') THEN
        CREATE TRIGGER leads_kg_node AFTER INSERT ON leads FOR EACH ROW EXECUTE FUNCTION kg_create_node();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'customers_kg_node') THEN
        CREATE TRIGGER customers_kg_node AFTER INSERT ON customers FOR EACH ROW EXECUTE FUNCTION kg_create_node();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'opps_kg_node') THEN
        CREATE TRIGGER opps_kg_node AFTER INSERT ON opportunities FOR EACH ROW EXECUTE FUNCTION kg_create_node();
    END IF;
END $$;

-- END OF MIGRATION
