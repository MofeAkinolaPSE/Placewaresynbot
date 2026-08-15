-- Migration 107: Purchase order status constraint + close/cancel tracking
--
-- sage_purchase_orders_snapshot.status has never had a CHECK constraint --
-- the frontend's STATUS_COLOR map (open/pending/approved/received/closed/
-- cancelled) was a guess, not an enforced vocabulary. There has also never
-- been any status-mutation endpoint anywhere in the app; the table is
-- purely CSV-import-populated and otherwise read-only. This migration adds
-- real close/cancel tracking columns and enforces the status vocabulary --
-- normalizing existing data BEFORE adding the constraint (a Python enum and
-- a DB CHECK constraint drifting out of sync on the same column already
-- caused a real bug in this codebase once, migration 102 -- keep them
-- defined together).

ALTER TABLE sage_purchase_orders_snapshot
    ADD COLUMN IF NOT EXISTS closed_at timestamptz,
    ADD COLUMN IF NOT EXISTS closed_by text,
    ADD COLUMN IF NOT EXISTS close_reason text;

-- Normalize existing NULL/blank/out-of-vocabulary status values to 'open'
-- (preserves current display for historical data -- the stale-cutoff query
-- logic in purchase_orders.py, not this migration, is what stops genuinely
-- stale rows from inflating the "pending" KPI going forward).
UPDATE sage_purchase_orders_snapshot
SET status = 'open'
WHERE status IS NULL
   OR btrim(status) = ''
   OR status NOT IN ('open', 'pending', 'approved', 'received', 'closed', 'cancelled');

-- Postgres has no native ADD CONSTRAINT IF NOT EXISTS for CHECK constraints;
-- guard explicitly so this migration stays safely re-runnable (the apply
-- script re-applies un-tracked files on every container start).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'sage_purchase_orders_snapshot_status_check'
    ) THEN
        ALTER TABLE sage_purchase_orders_snapshot
            ADD CONSTRAINT sage_purchase_orders_snapshot_status_check
            CHECK (status IN ('open', 'pending', 'approved', 'received', 'closed', 'cancelled'));
    END IF;
END $$;
