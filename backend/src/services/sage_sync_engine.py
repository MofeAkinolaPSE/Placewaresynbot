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


async def apply_record_event(envelope: Dict[str, Any]) -> None:
    """
    Apply a full record pushed by the bridge (event=record_upserted).

    This replaces the old "ping then re-pull everything" flow for invoices. The
    bridge now sends the complete invoice — header, lines, tax, payment and
    inventory movement — so we apply it directly instead of fetching up to 2000
    invoices back over the LAN on every single change.

    Idempotent: keyed on sage_id, so replaying an event is a no-op rather than a
    duplicate. Combined with the event_id gate in the webhook handler, a record
    is applied at most once even though the bridge may deliver it several times.
    """
    entity_type = envelope.get("entity_type") or ""
    record = envelope.get("data") or {}
    sage_id = envelope.get("sage_id") or record.get("sage_id")

    if not sage_id:
        logger.error("record_upserted with no sage_id — ignoring: %s", envelope)
        return

    if entity_type != "invoice":
        logger.warning(
            "apply_record_event received unsupported entity_type=%s; falling back "
            "to a pull-based sync.", entity_type,
        )
        await schedule_entity_sync(entity_type)
        return

    meta = record.get("_meta") or {}
    if meta.get("completeness") == "partial":
        # Visible rather than silent: downstream figures are being derived from
        # a degraded extraction (usually the SDK being unavailable).
        logger.warning(
            "Invoice %s arrived with completeness=partial (source=%s, missing=%s). "
            "Tax and related fields may be incomplete.",
            sage_id, meta.get("source"), meta.get("missing"),
        )

    try:
        payment = record.get("payment") or {}
        cache_row = {
            "sage_id": str(sage_id),
            "invoice_number": record.get("invoice_number") or "",
            "customer_id": record.get("customer_id") or "",
            "customer_name": record.get("customer_name") or "",
            "date": record.get("date"),
            "due_date": record.get("due_date"),
            "subtotal": record.get("subtotal") or 0,
            "total_tax": (record.get("tax") or {}).get("total_tax") or 0,
            "total_amount": payment.get("total_amount") or 0,
            "amount_paid": payment.get("amount_paid") or 0,
            "amount_due": payment.get("amount_due") or 0,
            "payment_status": payment.get("payment_status") or "unknown",
            "line_count": record.get("line_count") or 0,
            "lines": record.get("lines") or [],
            "po_number": record.get("po_number") or "",
            "note": record.get("note") or "",
            "source": meta.get("source") or "sage_bridge",
            "completeness": meta.get("completeness") or "unknown",
            # An invoice present in Sage is by definition not voided. Set
            # explicitly so a reappearing invoice clears a previous tombstone.
            "is_voided": False,
            "voided_at": None,
            "synced_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        _upsert_to_supabase("sage_invoices_cache", [cache_row], pk="sage_id")

        _apply_inventory_movement(sage_id, record.get("inventory_movement") or [])

        # Downstream surfaces beyond inventory. Each is keyed so a replay
        # overwrites its own rows rather than accumulating duplicates, which is
        # what lets the bridge retry an event safely.
        _apply_sales_lines(sage_id, record)
        _apply_gl_entries(sage_id, record)
        _refresh_customer_rollup(record.get("customer_id"))

        audit_event(
            action="sage_invoice_synced",
            actor="sage_bridge",
            resource="sage_invoices_cache/{}".format(sage_id),
            metadata={
                "sage_id": str(sage_id),
                "invoice_number": cache_row["invoice_number"],
                "total_amount": cache_row["total_amount"],
                "payment_status": cache_row["payment_status"],
                "line_count": cache_row["line_count"],
                "event_id": envelope.get("event_id"),
                "completeness": cache_row["completeness"],
            },
        )
        _record_sync_timestamp("ar_transaction")
        logger.info(
            "Invoice %s applied (%s lines, %s).",
            sage_id, cache_row["line_count"], cache_row["payment_status"],
        )

        await _run_invoice_workflow([{
            "sage_id": sage_id,
            "due_date": record.get("due_date"),
            "balance": payment.get("amount_due"),
            "customer_id": record.get("customer_id"),
        }])

    except Exception as exc:
        logger.error("Failed applying invoice %s: %s", sage_id, exc)
        _log_sync_error("ar_transaction", "invoice {}: {}".format(sage_id, exc))
        # Re-raise. The webhook handler awaits this call, so the raise turns
        # into a 503 and the event_id is NOT recorded — the bridge keeps the
        # event pending and retries it with backoff. Swallowing here would
        # silently lose the invoice.
        raise


async def apply_delete_event(envelope: Dict[str, Any]) -> None:
    """
    Apply a ``record_deleted`` event — an invoice that vanished from Sage.

    Emitted only by the bridge's reconciliation sweep, which is the sole path
    that can observe a deletion. Before this existed, an invoice voided in Sage
    stayed live in the cache indefinitely, inflating AR and overstating stock
    movement, with nothing that would ever correct it.

    Soft delete, never hard: rows are flagged ``is_voided`` and retained. A hard
    delete would erase the audit trail for a transaction that genuinely happened
    and was genuinely reversed — exactly the history an accounting integration
    must not lose. Every consumer of live figures filters on ``is_voided``.

    Idempotent: applying a delete twice sets the same flags.
    """
    entity_type = envelope.get("entity_type") or ""
    sage_id = envelope.get("sage_id") or (envelope.get("data") or {}).get("sage_id")

    if not sage_id:
        logger.error("record_deleted with no sage_id — ignoring: %s", envelope)
        return

    if entity_type != "invoice":
        logger.warning(
            "apply_delete_event received unsupported entity_type=%s — ignoring. "
            "Only invoice deletion is modelled.", entity_type,
        )
        return

    source_doc = "sage_invoice:{}".format(sage_id)
    now = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        # Read the customer first: the rollup refresh below needs to know whose
        # balance changed, and after the void the invoice no longer contributes.
        existing = (
            db.table("sage_invoices_cache")
            .select("customer_id")
            .eq("sage_id", str(sage_id))
            .limit(1)
            .execute()
        )
        customer_id = (existing.data or [{}])[0].get("customer_id")

        db.table("sage_invoices_cache").update(
            {"is_voided": True, "voided_at": now, "payment_status": "voided"}
        ).eq("sage_id", str(sage_id)).execute()

        # The goods never left — stock must not stay decremented.
        db.table("sage_inventory_movements").update(
            {"is_voided": True}
        ).eq("source_document", source_doc).execute()

        db.table("sage_sales_lines").update(
            {"is_voided": True}
        ).eq("source_document", source_doc).execute()

        db.table("sage_gl_entries").update(
            {"is_voided": True}
        ).eq("source_document", source_doc).execute()

        _refresh_customer_rollup(customer_id)

        audit_event(
            action="sage_invoice_voided",
            actor="sage_bridge",
            resource="sage_invoices_cache/{}".format(sage_id),
            metadata={
                "sage_id": str(sage_id),
                "customer_id": customer_id,
                "event_id": envelope.get("event_id"),
                "detected_by": "reconciliation_sweep",
            },
        )
        logger.warning(
            "Invoice %s voided — no longer present in Sage. Cache, stock, sales "
            "and GL rows flagged is_voided.", sage_id,
        )

    except Exception as exc:
        logger.error("Failed applying deletion for invoice %s: %s", sage_id, exc)
        _log_sync_error("ar_transaction", "delete {}: {}".format(sage_id, exc))
        # Raise so the webhook returns 503 and the bridge retries. A swallowed
        # failure here leaves a voided invoice live in SynBot permanently.
        raise


def _apply_sales_lines(sage_id: str, record: Dict[str, Any]) -> None:
    """
    Persist invoice lines at line grain (downstream: sales + reporting).

    The invoice cache stores lines as JSONB, which displays fine but cannot
    answer "units of item X sold last quarter" without scanning and unpacking
    every invoice. This is the queryable grain.

    Keyed on (source_document, line_no) so a replay overwrites its own rows.
    """
    lines = record.get("lines") or []
    if not lines:
        return

    source_doc = "sage_invoice:{}".format(sage_id)
    invoice_date = record.get("date")
    customer_id = record.get("customer_id") or ""

    rows = []
    for idx, line in enumerate(lines):
        rows.append({
            "source_document": source_doc,
            "line_no": line.get("line_no") or idx + 1,
            "sage_id": str(sage_id),
            "customer_id": customer_id,
            "item_id": line.get("item_id") or "",
            "description": line.get("description") or "",
            "quantity": line.get("quantity") or 0,
            "unit_price": line.get("unit_price") or 0,
            "amount": line.get("amount") or 0,
            "gl_account": line.get("gl_account") or "",
            "tax_amount": line.get("tax_amount") or 0,
            "invoice_date": invoice_date,
            "is_voided": False,
            "recorded_at": datetime.datetime.utcnow().isoformat() + "Z",
        })

    try:
        db.table("sage_sales_lines").upsert(
            rows, on_conflict="source_document,line_no"
        ).execute()
        logger.debug("Sales: %d line(s) for invoice %s", len(rows), sage_id)
    except Exception as exc:
        logger.error("Could not record sales lines for invoice %s: %s", sage_id, exc)
        raise


def _apply_gl_entries(sage_id: str, record: Dict[str, Any]) -> None:
    """
    Mirror the invoice's ledger impact (downstream: finance).

    Sage performs the real posting — this is the reporting mirror, and it is
    deliberately simple: revenue per GL account from the lines, tax as its own
    entry, and the receivable as the balancing side.

    It is NOT a general-purpose double-entry engine and does not try to be. It
    reproduces the standard sales-invoice shape so finance reporting in SynBot
    has account-level figures instead of only invoice totals. Anything more
    exotic (multi-currency, deferred revenue, job costing splits) must be read
    from Sage directly.

    Keyed on (source_document, gl_account, entry_type) so replay is idempotent.
    """
    lines = record.get("lines") or []
    payment = record.get("payment") or {}
    tax = record.get("tax") or {}
    invoice_date = record.get("date")
    customer_id = record.get("customer_id") or ""
    source_doc = "sage_invoice:{}".format(sage_id)

    # Revenue, aggregated per account: several lines commonly share one.
    by_account: Dict[str, float] = {}
    for line in lines:
        account = (line.get("gl_account") or "").strip()
        if not account:
            continue
        by_account[account] = by_account.get(account, 0.0) + float(line.get("amount") or 0)

    rows = []
    for account, amount in sorted(by_account.items()):
        rows.append({
            "source_document": source_doc, "gl_account": account,
            "entry_type": "revenue", "amount": round(amount, 4),
            "customer_id": customer_id, "entry_date": invoice_date,
            "is_voided": False,
        })

    total_tax = float(tax.get("total_tax") or 0)
    if total_tax:
        rows.append({
            "source_document": source_doc,
            "gl_account": (tax.get("tax_code") or "TAX").strip() or "TAX",
            "entry_type": "tax", "amount": round(total_tax, 4),
            "customer_id": customer_id, "entry_date": invoice_date,
            "is_voided": False,
        })

    total_amount = float(payment.get("total_amount") or 0)
    if total_amount:
        rows.append({
            "source_document": source_doc, "gl_account": "AR",
            "entry_type": "receivable", "amount": round(total_amount, 4),
            "customer_id": customer_id, "entry_date": invoice_date,
            "is_voided": False,
        })

    if not rows:
        return

    try:
        db.table("sage_gl_entries").upsert(
            rows, on_conflict="source_document,gl_account,entry_type"
        ).execute()
        logger.debug("Finance: %d GL entry row(s) for invoice %s", len(rows), sage_id)
    except Exception as exc:
        logger.error("Could not record GL entries for invoice %s: %s", sage_id, exc)
        raise


def _refresh_customer_rollup(customer_id: Optional[str]) -> None:
    """
    Recompute one customer's AR rollup from their non-voided invoices
    (downstream: customer records).

    Recomputed rather than incremented. An increment would drift on every
    replay, and replays are routine here — the bridge retries, operators
    trigger rescans, and the watermark can be reset. Recomputing from the cache
    is idempotent by construction and costs one indexed query per invoice sync.

    Non-fatal: a failure leaves the customer balance stale but the invoice
    itself correctly applied, and the next invoice for that customer — or
    refresh_customer_ar_rollup() — repairs it. Failing the whole event over a
    derived rollup would be the wrong trade.
    """
    if not customer_id:
        return

    try:
        result = (
            db.table("sage_invoices_cache")
            .select("amount_due,payment_status,date")
            .eq("customer_id", customer_id)
            .eq("is_voided", False)
            .execute()
        )
        invoices = result.data or []

        open_invoices = [
            i for i in invoices if (i.get("payment_status") or "") != "paid"
        ]
        balance = sum(float(i.get("amount_due") or 0) for i in open_invoices)
        dates = [i.get("date") for i in invoices if i.get("date")]

        db.table("sage_customers_cache").update({
            "ar_balance": round(balance, 4),
            "open_invoice_count": len(open_invoices),
            "last_invoice_date": max(dates) if dates else None,
            "last_invoice_at": datetime.datetime.utcnow().isoformat() + "Z",
        }).eq("id", customer_id).execute()

        logger.debug(
            "Customer %s rollup: balance=%.2f open=%d",
            customer_id, balance, len(open_invoices),
        )
    except Exception as exc:
        logger.warning(
            "Could not refresh AR rollup for customer %s: %s — balance is stale "
            "until the next invoice for this customer or a call to "
            "refresh_customer_ar_rollup().", customer_id, exc,
        )


def _apply_inventory_movement(
    sage_id: str, movements: List[Dict[str, Any]]
) -> None:
    """
    Record stock movement implied by an invoice.

    ``quantity_delta`` is negative for a sale (see the bridge's
    invoice_extract._derive_inventory_movement). Rows are keyed on
    (source_document, item_id) so replaying an invoice overwrites its own
    movement rather than double-decrementing stock.
    """
    if not movements:
        return
    rows = []
    for m in movements:
        rows.append({
            "source_document": "sage_invoice:{}".format(sage_id),
            "item_id": m.get("item_id"),
            "quantity_delta": m.get("quantity_delta"),
            "direction": m.get("direction") or "out",
            "unit_price": m.get("unit_price"),
            # Explicitly cleared: if this invoice was previously voided and has
            # reappeared in Sage, re-applying it must un-void the movement
            # rather than leave stock permanently written off.
            "is_voided": False,
            "recorded_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    try:
        db.table("sage_inventory_movements").upsert(
            rows, on_conflict="source_document,item_id"
        ).execute()
        logger.info("Inventory: %d movement row(s) for invoice %s", len(rows), sage_id)
    except Exception as exc:
        # Raise rather than log-and-continue. This used to be swallowed, which
        # let an invoice be marked applied while its stock movement was missing
        # — inventory silently diverging from Sage with nothing to replay from.
        # The upsert is keyed on (source_document, item_id), so retrying the
        # whole event is safe and cannot double-decrement.
        logger.error(
            "Could not record inventory movement for invoice %s: %s", sage_id, exc
        )
        raise


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
