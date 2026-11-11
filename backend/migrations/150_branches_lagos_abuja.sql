-- 7 Nov 2026: two branches, Lagos and Abuja, in one ACE (client: "Abuja has its own inventory and its own books;
-- same application, same features - only the inventory and the finance books differ").
--
-- Design (backend/docs/Branches.md):
--   * A branch IS an ACE Books legal entity. Lagos = the existing PNL entity, Abuja = PNL-ABJ. ACE Books already
--     keeps every book per entity (accounts, journals, stock, invoice numbers, settings...).
--   * Everything that belongs to a branch's trading carries legal_entity_id too: customers, suppliers, Frontdesk,
--     deliveries, stock orders, QC batches/recalls/deviations, equipment/temperature, the Sage snapshots.
--     Existing rows are Lagos. New rows take the branch of the request that creates them (column DEFAULT).
--   * HR, My Workspace, chat, tasks, notifications and the CRM pipeline stay company-wide (no column).
--   * Each login has a home branch (+ optional extra branches). Admin and management (CEO/CFO) see every branch.
--   * The database enforces it: web requests run as role ace_app with app.entity_id set to the request's branch,
--     and row-level security hides every other branch's rows. A query that forgets its branch filter returns
--     nothing from the other branch rather than mixing them.

-- 1. Branch names --------------------------------------------------------------------------------------------
ALTER TABLE fin_legal_entities ADD COLUMN IF NOT EXISTS branch_name text;
ALTER TABLE fin_legal_entities ADD COLUMN IF NOT EXISTS is_primary boolean NOT NULL DEFAULT FALSE;
ALTER TABLE fin_legal_entities ADD COLUMN IF NOT EXISTS sort_order int NOT NULL DEFAULT 0;

DO $$
DECLARE
    lagos uuid;
    abuja uuid;
BEGIN
    SELECT id INTO lagos FROM fin_legal_entities WHERE is_primary LIMIT 1;
    IF lagos IS NULL THEN
        SELECT id INTO lagos FROM fin_legal_entities WHERE code = 'PNL' LIMIT 1;
    END IF;
    IF lagos IS NULL THEN
        SELECT id INTO lagos FROM fin_legal_entities WHERE status = 'ACTIVE' ORDER BY created_at LIMIT 1;
    END IF;
    IF lagos IS NULL THEN
        RAISE NOTICE 'No legal entity yet - branches are set up when ACE Books is.';
        RETURN;
    END IF;
    UPDATE fin_legal_entities SET is_primary = TRUE, branch_name = COALESCE(branch_name, 'Lagos'), sort_order = 1
     WHERE id = lagos;

    SELECT id INTO abuja FROM fin_legal_entities WHERE code = 'PNL-ABJ';
    IF abuja IS NULL THEN
        INSERT INTO fin_legal_entities (organization_id, code, name, base_currency, fiscal_year_start_month,
                                        branch_name, sort_order)
        SELECT organization_id, 'PNL-ABJ', 'Placeware Nigeria Limited - Abuja', base_currency,
               fiscal_year_start_month, 'Abuja', 2
          FROM fin_legal_entities WHERE id = lagos
        RETURNING id INTO abuja;
    END IF;
    -- Abuja's settings start like Lagos's (credit-limit mode, ageing buckets, ship methods, invoice layout) but
    -- with no cut-over and no auto-posting until its own books are loaded.
    INSERT INTO fin_settings (legal_entity_id) VALUES (abuja) ON CONFLICT DO NOTHING;
    UPDATE fin_settings a SET
        journal_approval_required = l.journal_approval_required,
        allow_self_approval = l.allow_self_approval,
        credit_limit_mode = l.credit_limit_mode,
        negative_stock_policy = l.negative_stock_policy,
        aging_buckets = l.aging_buckets,
        invoice_layout = l.invoice_layout,
        ship_methods = l.ship_methods,
        default_customer_code = l.default_customer_code,
        auto_post_frontdesk = FALSE,
        cutover_date = NULL
      FROM fin_settings l
     WHERE a.legal_entity_id = abuja AND l.legal_entity_id = lagos
       AND a.cutover_date IS NULL AND NOT EXISTS (SELECT 1 FROM fin_journals j WHERE j.legal_entity_id = abuja);
END $$;

-- The branch a request runs for (set per database connection by the backend). NULL outside a web request.
CREATE OR REPLACE FUNCTION pw_entity() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT NULLIF(current_setting('app.entity_id', true), '')::uuid $$;

-- The branch a new row belongs to: the request's branch; for background jobs (no request), the primary branch.
CREATE OR REPLACE FUNCTION pw_entity_default() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT COALESCE(pw_entity(), (SELECT id FROM fin_legal_entities WHERE is_primary ORDER BY created_at LIMIT 1)) $$;

-- 2. Who works where -----------------------------------------------------------------------------------------
ALTER TABLE placeware_users ADD COLUMN IF NOT EXISTS home_entity_id uuid REFERENCES fin_legal_entities(id);
ALTER TABLE placeware_users ADD COLUMN IF NOT EXISTS extra_entity_ids uuid[] NOT NULL DEFAULT '{}';
ALTER TABLE placeware_users ALTER COLUMN home_entity_id SET DEFAULT pw_entity_default();
UPDATE placeware_users SET home_entity_id = (SELECT id FROM fin_legal_entities WHERE is_primary LIMIT 1)
 WHERE home_entity_id IS NULL;

-- 3. Branch column on the per-branch tables ------------------------------------------------------------------
-- Existing rows become Lagos (a constant default fills them without rewriting big tables); then the default
-- switches to "the request's branch".
DO $$
DECLARE
    lagos uuid := (SELECT id FROM fin_legal_entities WHERE is_primary LIMIT 1);
    t text;
    branch_tables text[] := ARRAY[
        'customers', 'suppliers',
        'frontdesk_invoices', 'frontdesk_walk_ins', 'deliveries', 'riders', 'routes',
        'replenishment_requests', 'supplier_deliveries',
        'nafdac_batch_registry', 'batch_status_locks', 'recall_cases', 'deviation_reports',
        'temperature_logs', 'equipment_registry', 'maintenance_schedule', 'audit_schedule',
        'placeware_inventory_events', 'placeware_stock_cache',
        'fin_ar_alert_rules', 'fin_ar_alert_events', 'fin_vendor_payment_requests', 'fin_budget_targets',
        'ar_receipts', 'ar_receipt_applications', 'credit_risk_actions', 'placeware_invoices', 'placeware_orders'];
BEGIN
    IF lagos IS NULL THEN
        RETURN;
    END IF;
    FOR t IN
        SELECT unnest(branch_tables)
        UNION
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.relname LIKE 'sage\_%'
    LOOP
        IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
            CONTINUE;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = t AND column_name = 'legal_entity_id') THEN
            EXECUTE format('ALTER TABLE public.%I ADD COLUMN legal_entity_id uuid DEFAULT %L', t, lagos);
        END IF;
        EXECUTE format('UPDATE public.%I SET legal_entity_id = %L WHERE legal_entity_id IS NULL', t, lagos);
        EXECUTE format('ALTER TABLE public.%I ALTER COLUMN legal_entity_id SET DEFAULT pw_entity_default()', t);
        EXECUTE format('ALTER TABLE public.%I ALTER COLUMN legal_entity_id SET NOT NULL', t);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON public.%I (legal_entity_id)', 'ix_' || left(t, 50) || '_entity', t);
    END LOOP;
END $$;

-- 4. Codes are unique per branch, not across the company (Abuja's Sage has its own customer and vendor IDs,
--    its own RECALL-/DEV- numbers and its own invoice numbers). ---------------------------------------------
ALTER TABLE customers DROP CONSTRAINT IF EXISTS customers_customer_code_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_entity_code ON customers (legal_entity_id, customer_code);

ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS suppliers_external_vendor_id_key;
DROP INDEX IF EXISTS idx_suppliers_external_vendor_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_entity_vendor ON suppliers (legal_entity_id, external_vendor_id);

ALTER TABLE recall_cases DROP CONSTRAINT IF EXISTS recall_cases_recall_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_recall_cases_entity_id ON recall_cases (legal_entity_id, recall_id);

ALTER TABLE deviation_reports DROP CONSTRAINT IF EXISTS deviation_reports_deviation_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_deviation_reports_entity_id ON deviation_reports (legal_entity_id, deviation_id);

DROP INDEX IF EXISTS uidx_nafdac_batch_product;
CREATE UNIQUE INDEX IF NOT EXISTS uidx_nafdac_batch_product ON nafdac_batch_registry (legal_entity_id, batch_number, product_name);

ALTER TABLE fin_budget_targets DROP CONSTRAINT IF EXISTS uq_budget_dept_cat_period;
CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_dept_cat_period ON fin_budget_targets (legal_entity_id, department, category, period);

DROP INDEX IF EXISTS uq_inventory_events_sale_ref_sku;
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_events_sale_ref_sku ON placeware_inventory_events (legal_entity_id, reference, sku)
    WHERE event_type = 'SALE' AND reference IS NOT NULL;

ALTER TABLE placeware_invoices DROP CONSTRAINT IF EXISTS placeware_invoices_invoice_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_placeware_invoices_entity_id ON placeware_invoices (legal_entity_id, invoice_id);

-- 5. The web role and row-level security ---------------------------------------------------------------------
-- pw_apply_branch_security() is idempotent; scripts/apply_migrations.py runs it after every migration run, so a
-- table or view added later is covered without anyone remembering to.
CREATE OR REPLACE FUNCTION pw_apply_branch_security() RETURNS void
    LANGUAGE plpgsql
    AS $fn$
DECLARE
    t text;
    v text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ace_app') THEN
        CREATE ROLE ace_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
    EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO ace_app', current_database());
    GRANT USAGE ON SCHEMA public TO ace_app;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO ace_app;
    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ace_app;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ace_app;
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '_archive') THEN
        GRANT USAGE ON SCHEMA _archive TO ace_app;
        GRANT ALL ON ALL TABLES IN SCHEMA _archive TO ace_app;
    END IF;

    -- Every table with a branch column: a web request sees and writes only its own branch. RESTRICTIVE, so it
    -- holds whatever other policies a table has (old "allow all" policies from the Supabase days are OR-ed
    -- together and would otherwise switch it off). (Background jobs connect as the owner and are not filtered.)
    FOR t IN
        SELECT c.table_name FROM information_schema.columns c
          JOIN information_schema.tables tb ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
         WHERE c.table_schema = 'public' AND c.column_name = 'legal_entity_id' AND tb.table_type = 'BASE TABLE'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = t
                                               AND policyname = 'branch_isolation' AND permissive <> 'RESTRICTIVE') THEN
            EXECUTE format('DROP POLICY branch_isolation ON public.%I', t);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = t
                                                    AND policyname = 'branch_isolation') THEN
            EXECUTE format('CREATE POLICY branch_isolation ON public.%I AS RESTRICTIVE FOR ALL TO ace_app '
                           'USING (legal_entity_id = pw_entity()) WITH CHECK (legal_entity_id = pw_entity())', t);
        END IF;
    END LOOP;

    -- The web role otherwise sees every row, exactly as the app did before (it ran as the owner, which skips
    -- row security). Without this, old per-user policies written for Supabase (e.g. on chat history and the
    -- calendar, whose user checks now compare with NULL) would hide rows the app has always shown.
    FOR t IN
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') AND c.relrowsecurity
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = t
                                                    AND policyname = 'ace_app_access') THEN
            EXECUTE format('CREATE POLICY ace_app_access ON public.%I AS PERMISSIVE FOR ALL TO ace_app '
                           'USING (true) WITH CHECK (true)', t);
        END IF;
    END LOOP;

    -- Views check the reader's rights (not the view owner's), so branch filtering reaches through them.
    FOR v IN
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'v'
           AND NOT COALESCE(c.reloptions @> ARRAY['security_invoker=true'], FALSE)
    LOOP
        EXECUTE format('ALTER VIEW public.%I SET (security_invoker = true)', v);
    END LOOP;
END
$fn$;

SELECT pw_apply_branch_security();
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ace_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ace_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO ace_app;
