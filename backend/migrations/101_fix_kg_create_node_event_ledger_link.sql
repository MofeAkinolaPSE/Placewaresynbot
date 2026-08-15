-- 101_fix_kg_create_node_event_ledger_link.sql
--
-- Fixes a real, pre-existing bug found via live verification of the CRM
-- Lead Finder retrofit's "Score + Ingest" action (POST
-- /crm/lead-finder/prospects/{id}/score-ingest), which inserts a row into
-- `leads`. That INSERT fires the `leads_kg_node` trigger -> kg_create_node(),
-- which -- only when NEW.event_ledger_id is populated -- tries:
--
--   SELECT id FROM kg_nodes WHERE ref_table='event_ledger' AND ref_id=NEW.event_ledger_id
--
-- kg_nodes.ref_id is bigint; leads.event_ledger_id is uuid. This comparison
-- can never type-check, so it doesn't just fail to match -- it throws
-- "operator does not exist: bigint = uuid" and, because this is an
-- AFTER-INSERT trigger in the same transaction, rolls back the entire lead
-- insert. Every score-ingest call whose payload populates event_ledger_id
-- has been failing outright since this trigger was introduced.
--
-- The function's own comment already frames this as best-effort
-- ("Optionally create edge to EventLedger if event_ledger_id present") --
-- kg_nodes has no bigint representation of a uuid event_ledger id anywhere,
-- so this lookup can structurally never succeed as written. Rather than
-- attempt a real fix to the ref_id/uuid design mismatch (kg_nodes is shared
-- cross-cutting infrastructure with triggers on leads/customers/
-- opportunities -- out of scope to redesign here), this migration makes the
-- optional edge-creation genuinely optional: wrapped so a failure there
-- can never block the primary row insert it's attached to.
--
-- Idempotent: CREATE OR REPLACE FUNCTION is safe to re-run.

CREATE OR REPLACE FUNCTION kg_create_node()
RETURNS TRIGGER AS $$
DECLARE
    new_node_id BIGINT;
BEGIN
    INSERT INTO kg_nodes(node_type, ref_table, ref_id, properties)
    VALUES (TG_TABLE_NAME, TG_TABLE_NAME, NEW.id, to_jsonb(NEW) - 'metadata')
    RETURNING id INTO new_node_id;

    -- Optionally create edge to EventLedger if event_ledger_id present.
    -- Best-effort: kg_nodes.ref_id (bigint) cannot hold event_ledger's uuid
    -- ids, so this lookup never matches today -- swallow any error here
    -- rather than let a side-effect linkage failure roll back the primary
    -- insert that triggered it.
    IF TG_TABLE_NAME = 'leads' THEN
        IF NEW.event_ledger_id IS NOT NULL THEN
            BEGIN
                INSERT INTO kg_edges(from_node, to_node, edge_type, properties)
                VALUES (new_node_id,
                    (SELECT id FROM kg_nodes WHERE ref_table='event_ledger' AND ref_id::text = NEW.event_ledger_id::text LIMIT 1),
                    'LinkedTo',
                    jsonb_build_object('via','event_ledger')
                       ) ON CONFLICT DO NOTHING;
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
