-- 131: Data exceptions - the problems found in the Sage hand-over, each with its lineage and the
-- ways the finance team can resolve it (meeting 7 Oct 2026).
--
--   fin_sage_snapshots        the "as at" reports of a Sage export (Trial Balance, Aged Receivables,
--                             Aged Payables, Inventory Valuation), kept so every check can be
--                             re-run and shown later without the export folder
--   fin_data_exceptions       one row per problem (a lot Sage sold below zero, a trial balance /
--                             general ledger difference, a control account that disagrees with its
--                             subledger), with what was found, how big it is and its status
--   fin_data_exception_actions every decision taken on a problem: who, when, why, the journal it
--                             posted and what it changed (ledger and stock), so the fix is traceable
--
-- Corrections posted from here are carried as overlays on Sage's history: a journal in ACE Books
-- plus a line in the Sage-period General Ledger (jrnl 'ADJ', no load) dated the hand-over date, and
-- for stock a quantity/value overlay. Reloading Sage files and later roll-forwards keep them.

CREATE TABLE IF NOT EXISTS fin_sage_snapshots (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES fin_legal_entities(id),
    kind            text NOT NULL,
    as_of           date NOT NULL,
    file_name       text,
    rows            jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary         jsonb NOT NULL DEFAULT '{}'::jsonb,
    issues          jsonb NOT NULL DEFAULT '[]'::jsonb,
    loaded_by       text,
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, kind, as_of)
);

CREATE TABLE IF NOT EXISTS fin_data_exceptions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES fin_legal_entities(id),
    kind            text NOT NULL CHECK (kind IN ('STOCK_SHORT_LOT', 'TB_GL_DIFFERENCE', 'AR_CONTROL', 'AP_CONTROL', 'INVENTORY_CONTROL')),
    key             text NOT NULL,
    title           text NOT NULL,
    summary         text,
    severity        text NOT NULL DEFAULT 'MEDIUM' CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    amount          numeric(20,2),
    quantity        numeric(18,4),
    as_of           date,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb,
    status          text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED', 'ACCEPTED')),
    resolution      text,
    resolution_note text,
    resolved_by     text,
    resolved_at     timestamptz,
    first_seen      timestamptz NOT NULL DEFAULT now(),
    last_seen       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, kind, key)
);
CREATE INDEX IF NOT EXISTS idx_fin_data_exceptions_status ON fin_data_exceptions (legal_entity_id, status, kind);

CREATE TABLE IF NOT EXISTS fin_data_exception_actions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    exception_id    uuid NOT NULL REFERENCES fin_data_exceptions(id),
    legal_entity_id uuid NOT NULL REFERENCES fin_legal_entities(id),
    action          text NOT NULL,
    reference       text,
    note            text,
    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
    journal_id      uuid REFERENCES fin_journals(id),
    gl_delta        jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{account_code, debit, credit}]
    stock_delta     jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{sku, quantity, value}]
    created_by      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_data_exception_actions ON fin_data_exception_actions (exception_id, created_at);

-- Goods that arrived before their supplier invoice was entered (the client's Sage lags its
-- purchases). Mapped to Accrued Expenses until the accountant picks a dedicated account.
INSERT INTO fin_account_mappings (legal_entity_id, mapping_key, account_id)
SELECT a.legal_entity_id, 'GOODS_RECEIVED_ACCRUAL', a.id FROM fin_accounts a
 WHERE a.code = '23000'
   AND NOT EXISTS (SELECT 1 FROM fin_account_mappings m WHERE m.legal_entity_id = a.legal_entity_id
                   AND m.mapping_key = 'GOODS_RECEIVED_ACCRUAL');
