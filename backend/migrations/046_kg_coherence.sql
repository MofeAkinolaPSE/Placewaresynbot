-- Phase 5: Knowledge Graph coherence and writer/read model alignment

ALTER TABLE kg_nodes
  ADD COLUMN IF NOT EXISTS ref_key TEXT;

UPDATE kg_nodes
SET ref_key = COALESCE(ref_key, CONCAT(COALESCE(ref_table, ''), ':', COALESCE(ref_id::text, '')))
WHERE ref_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_nodes_identity
  ON kg_nodes(node_type, ref_table, ref_key)
  WHERE ref_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_kg_nodes_type_key
  ON kg_nodes(node_type, ref_key);

CREATE INDEX IF NOT EXISTS idx_kg_edges_from_to_type
  ON kg_edges(from_node, to_node, edge_type);
