-- Migration 112: Make dispatch-driven SALE events idempotent
--
-- Dispatching an invoice now writes a SALE event per line item so that
-- v_inventory.current_stock (Sage CSV baseline + events, per migration 106)
-- finally reflects goods that actually left the building. Until now nothing
-- in the frontdesk lifecycle decremented stock at all: a full
-- qc -> finance -> dispatch run left current_stock untouched and recorded
-- zero SALE events, so every stock figure was only as fresh as the last CSV
-- import.
--
-- The only thing stopping a double-decrement today is an application-level
-- status check in send_for_delivery(), which is not safe against a retry or
-- two concurrent dispatch calls. This adds the DB-level guarantee: one SALE
-- event per (invoice reference, sku). The partial index deliberately covers
-- SALE only -- RESTOCK/ADJUSTMENT/DAMAGE/EXPIRY are legitimately repeatable
-- for the same reference.

-- Collapse any pre-existing duplicates before enforcing uniqueness. There
-- should be none (no SALE event has ever been written), but a migration that
-- assumes that and fails on a live DB is worse than one that doesn't.
DELETE FROM placeware_inventory_events a
USING placeware_inventory_events b
WHERE a.event_type = 'SALE'
  AND b.event_type = 'SALE'
  AND a.reference IS NOT NULL
  AND a.reference = b.reference
  AND a.sku = b.sku
  AND a.id > b.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_events_sale_ref_sku
    ON placeware_inventory_events (reference, sku)
    WHERE event_type = 'SALE' AND reference IS NOT NULL;
