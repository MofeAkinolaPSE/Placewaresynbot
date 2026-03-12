-- 034_customer_360.sql
-- Create customer_360 table and refresh function; optional trigger on event_ledger

CREATE TABLE IF NOT EXISTS customer_360 (
    customer_id BIGINT PRIMARY KEY,
    last_activity TIMESTAMP WITH TIME ZONE,
    total_purchases NUMERIC DEFAULT 0,
    open_opportunities INTEGER DEFAULT 0,
    lifetime_value NUMERIC DEFAULT 0,
    risk_score NUMERIC DEFAULT 0,
    data JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE OR REPLACE FUNCTION refresh_customer_360(p_customer_id BIGINT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF p_customer_id IS NULL THEN
        RETURN;
    END IF;

    -- Aggregate basic metrics from known tables; tolerate missing tables
    PERFORM 1;

    -- total_purchases: sum of event payload.amount for events linked to customer with event_type 'order' or 'payment'
    WITH evt AS (
        SELECT payload, created_at
        FROM event_ledger
        WHERE linked_customer_id = p_customer_id
    ),
    purchases AS (
        SELECT COALESCE((payload->>'amount')::numeric,0) AS amount FROM evt WHERE event_type IN ('order','payment')
    ),
    open_ops AS (
        SELECT COUNT(*) AS cnt FROM opportunities WHERE linked_customer_id = p_customer_id AND status NOT IN ('won','lost')
    ),
    last_act AS (
        SELECT max(created_at) AS last_at FROM event_ledger WHERE linked_customer_id = p_customer_id
    )
    INSERT INTO customer_360 (customer_id, last_activity, total_purchases, open_opportunities, lifetime_value, updated_at)
    VALUES (
        p_customer_id,
        (SELECT last_at FROM last_act),
        (SELECT COALESCE(SUM(amount),0) FROM purchases),
        (SELECT COALESCE(cnt,0) FROM open_ops),
        (SELECT COALESCE(SUM(amount),0) FROM purchases),
        now()
    )
    ON CONFLICT (customer_id) DO UPDATE SET
        last_activity = EXCLUDED.last_activity,
        total_purchases = EXCLUDED.total_purchases,
        open_opportunities = EXCLUDED.open_opportunities,
        lifetime_value = EXCLUDED.lifetime_value,
        updated_at = now();

END;
$$;

-- Optional trigger: when new event with linked_customer_id is inserted, refresh the 360 row
CREATE OR REPLACE FUNCTION trg_refresh_customer_360() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.linked_customer_id IS NOT NULL THEN
        PERFORM refresh_customer_360(NEW.linked_customer_id);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS event_refresh_customer_360 ON event_ledger;
CREATE TRIGGER event_refresh_customer_360
AFTER INSERT ON event_ledger
FOR EACH ROW
EXECUTE FUNCTION trg_refresh_customer_360();
