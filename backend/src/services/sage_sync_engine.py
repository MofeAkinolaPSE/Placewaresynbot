"""
sage_sync_engine.py — Background sync engine for SynBot.

Responsibilities:
  1. Receive entity-type change signals from the webhook router
     (triggered by the Sage Bridge file watcher).
  2. Pull fresh data from the Sage Bridge for that entity type.
  3. Upsert records into Supabase snapshot/cache tables.
  4. Maintain last-sync timestamps.
  5. Provide a one-time historical migration pull.

Cache tables (Supabase) used:
  sage_customers_cache         — live customer records from Sage
  sage_invoices_cache          — AR invoices from Sage
  sage_vendors_cache           — vendor records
  sage_inventory_cache         — inventory items
  sage_accounts_cache          — chart of accounts
  sage_employees_cache         — employee records
  sage_sales_orders_cache      — sales orders
  sage_purchase_orders_cache   — purchase orders
  sage_payments_cache          — customer receipts / payments received
  sage_journal_cache           — general journal entries
  sage_payroll_cache           — payroll checks
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from src.db import db, audit_event

logger = logging.getLogger("synbot.sage_sync")

SAGE_BRIDGE_URL = os.getenv("SAGE_BRIDGE_URL", "http://SAGE_BRIDGE_HOST_PLACEHOLDER:7070")
SAGE_BRIDGE_KEY = os.getenv("SAGE_BRIDGE_KEY", "")
_BRIDGE_TIMEOUT = 30


def _headers() -> Dict[str, str]:
    return {"X-Bridge-API-Key": SAGE_BRIDGE_KEY}


# ── Entity → bridge path + cache table mapping ────────────────────────────────

ENTITY_SYNC_MAP: Dict[str, Dict[str, str]] = {
    "customer": {
        "bridge_path": "/customers",
        "cache_table": "sage_customers_cache",
        "pk": "id",
    },
    "vendor": {
        "bridge_path": "/vendors",
        "cache_table": "sage_vendors_cache",
        "pk": "id",
    },
    "employee": {
        "bridge_path": "/employees",
        "cache_table": "sage_employees_cache",
        "pk": "id",
    },
    "inventory": {
        "bridge_path": "/inventory",
        "cache_table": "sage_inventory_cache",
        "pk": "id",
    },
    "account": {
        "bridge_path": "/accounts",
        "cache_table": "sage_accounts_cache",
        "pk": "id",
    },
    "ar_transaction": {
        "bridge_path": "/invoices",
        "cache_table": "sage_invoices_cache",
        "pk": "sage_id",
    },
    "sales_order": {
        "bridge_path": "/sales-orders",
        "cache_table": "sage_sales_orders_cache",
        "pk": "sage_id",
    },
    "purchase_order": {
        "bridge_path": "/purchase-orders",
        "cache_table": "sage_purchase_orders_cache",
        "pk": "sage_id",
    },
    # AP transactions — vendor bills/payments tracked via purchase orders in Sage 50
    "ap_transaction": {
        "bridge_path": "/purchase-orders",
        "cache_table": "sage_purchase_orders_cache",
        "pk": "sage_id",
    },
    # General journal entries (JRNLHDR + JRNLROW .DAT files)
    "journal_entry": {
        "bridge_path": "/journal",
        "cache_table": "sage_journal_cache",
        "pk": "sage_id",
    },
    # Payroll — mapped to employees cache until a dedicated payroll cache table exists
    "payroll": {
        "bridge_path": "/employees",
        "cache_table": "sage_employees_cache",
        "pk": "id",
    },
}


async def _fetch_from_bridge(path: str, limit: int = 2000) -> List[Dict[str, Any]]:
    """Fetch entity list from the bridge service."""
    url = f"{SAGE_BRIDGE_URL}{path}"
    async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as client:
        resp = await client.get(url, params={"limit": limit}, headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _upsert_to_supabase(table: str, rows: List[Dict[str, Any]], pk: str = "id") -> int:
    """
    Upsert rows into the cache table using the correct primary key column.
    Returns number of rows upserted.
    """
    if not rows:
        return 0
    try:
        db.table(table).upsert(rows, on_conflict=pk).execute()
    except Exception as exc:
        logger.error("Supabase upsert to %s failed: %s", table, exc)
        raise
    return len(rows)


async def schedule_entity_sync(entity_type: str) -> None:
    """
    Called by the webhook handler when the bridge detects a Sage data change.
    Pulls fresh data, upserts into Supabase, then runs any post-sync workflow hooks.
    """
    mapping = ENTITY_SYNC_MAP.get(entity_type)
    if not mapping:
        logger.warning("No sync mapping for entity_type: %s — event acknowledged but not processed", entity_type)
        return

    logger.info("Syncing entity_type=%s from Sage Bridge", entity_type)
    try:
        rows = await _fetch_from_bridge(mapping["bridge_path"])
        count = _upsert_to_supabase(mapping["cache_table"], rows, pk=mapping["pk"])
        logger.info("Sync complete: entity=%s rows=%d", entity_type, count)
        _record_sync_timestamp(entity_type)

        # ── Post-sync workflow hooks ─────────────────────────────────────────
        if entity_type == "ar_transaction":
            await _run_invoice_workflow(rows)

    except Exception as exc:
        logger.error("Sync failed for %s: %s", entity_type, exc)
        _log_sync_error(entity_type, str(exc))


async def _run_invoice_workflow(invoice_rows: List[Dict[str, Any]]) -> None:
    """
    Invoice workflow — triggered automatically after every AR sync.

    Steps:
      1. Detect overdue invoices (balance > 0 AND due_date < today)
      2. Log overdue count + critical threshold breach to audit trail
      3. If overdue total exceeds threshold, emit a WARNING-level alert
         (email / push notification integration point for future sprint)
    """
    if not invoice_rows:
        return

    today = datetime.date.today()
    overdue: List[Dict[str, Any]] = []
    total_overdue_amount = 0.0

    for inv in invoice_rows:
        # Normalise field names — bridge may return 'due_date' or 'date_due'
        raw_due = inv.get("due_date") or inv.get("date_due") or ""
        raw_balance = inv.get("balance") or inv.get("amount_due") or 0
        try:
            balance = float(raw_balance)
        except (TypeError, ValueError):
            balance = 0.0

        if not raw_due or balance <= 0:
            continue

        try:
            due_date = datetime.date.fromisoformat(str(raw_due)[:10])
        except ValueError:
            continue

        if due_date < today:
            overdue.append({
                "invoice_id": inv.get("sage_id") or inv.get("id") or "unknown",
                "customer_id": inv.get("customer_id") or inv.get("ACCTID") or "",
                "due_date": str(due_date),
                "balance": balance,
                "days_overdue": (today - due_date).days,
            })
            total_overdue_amount += balance

    overdue_count = len(overdue)
    logger.info(
        "Invoice workflow: %d overdue invoice(s), total outstanding ₦%.2f",
        overdue_count, total_overdue_amount,
    )

    if overdue_count == 0:
        return

    # ── Persist overdue summary to audit trail ────────────────────────────────
    try:
        audit_event(
            action="sage_ar_overdue_detected",
            actor="sage_sync_engine",
            resource="sage_invoices_cache",
            metadata={
                "overdue_count": overdue_count,
                "total_overdue_amount": round(total_overdue_amount, 2),
                "currency": "NGN",
                "detected_at": datetime.datetime.utcnow().isoformat() + "Z",
                "top_overdue": sorted(overdue, key=lambda x: x["balance"], reverse=True)[:5],
            },
        )
    except Exception as exc:
        logger.warning("Could not write invoice workflow audit event: %s", exc)

    # ── Threshold alert (₦500,000 = escalation threshold) ────────────────────
    OVERDUE_ALERT_THRESHOLD = float(os.getenv("OVERDUE_ALERT_THRESHOLD", "500000"))
    if total_overdue_amount >= OVERDUE_ALERT_THRESHOLD:
        logger.warning(
            "INVOICE ALERT: Total overdue AR (₦%.2f) exceeds threshold (₦%.2f). "
            "%d invoice(s) outstanding. Manual review required.",
            total_overdue_amount, OVERDUE_ALERT_THRESHOLD, overdue_count,
        )
        # TODO (next sprint): trigger email notification to finance department
        # from src.services.email_service import send_overdue_alert
        # await send_overdue_alert(overdue, total_overdue_amount)


async def run_full_historical_migration() -> Dict[str, Any]:
    """
    One-time migration: pull ALL historical data from Sage and seed Supabase.
    Call this manually once from the admin panel or a migration script.
    Returns a summary of rows pulled per entity type.
    """
    logger.info("=== Starting full historical migration from Sage ===")
    summary: Dict[str, int] = {}
    errors: Dict[str, str] = {}

    for entity_type, mapping in ENTITY_SYNC_MAP.items():
        try:
            # Pull in pages of 2000
            all_rows: List[Dict[str, Any]] = []
            offset = 0
            page_size = 2000
            while True:
                url = f"{SAGE_BRIDGE_URL}{mapping['bridge_path']}"
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(
                        url,
                        params={"limit": page_size, "offset": offset},
                        headers=_headers(),
                    )
                resp.raise_for_status()
                page = resp.json()
                if not isinstance(page, list) or not page:
                    break
                all_rows.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size

            count = _upsert_to_supabase(mapping["cache_table"], all_rows, pk=mapping["pk"])
            summary[entity_type] = count
            logger.info("Historical migration: %s → %d rows", entity_type, count)
            _record_sync_timestamp(entity_type)

        except Exception as exc:
            logger.error("Historical migration failed for %s: %s", entity_type, exc)
            errors[entity_type] = str(exc)

    logger.info("=== Historical migration complete: %s ===", summary)
    return {"migrated": summary, "errors": errors}


def _record_sync_timestamp(entity_type: str) -> None:
    """Update the sync_timestamps table so we know when each entity was last synced."""
    try:
        import datetime
        db.table("placeware_sage_sync_timestamps").upsert({
            "entity_type": entity_type,
            "last_synced_at": datetime.datetime.utcnow().isoformat() + "Z",
        }, on_conflict="entity_type").execute()
    except Exception as exc:
        logger.debug("Could not record sync timestamp: %s", exc)


def _log_sync_error(entity_type: str, error_message: str) -> None:
    """Insert a failure record into the sync log."""
    try:
        db.table("placeware_sage_sync_log").insert({
            "entity_type": entity_type,
            "direction": "sage_to_synbot",
            "status": "failed",
            "error_message": error_message,
        }).execute()
    except Exception:
        pass
