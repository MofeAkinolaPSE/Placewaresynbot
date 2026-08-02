"""
watcher.py — Detects new/changed Sage records and enqueues them durably.

Detection strategy: two layers
------------------------------
1. **File-mtime trigger (cheap).** Stat the company folder's .DAT files every
   WATCHER_POLL_SECONDS. A changed mtime says "something happened in this area"
   — cheap enough to run often, but it does NOT say what changed.

2. **Table scan (authoritative).** When AR files look touched — or every
   WATCHER_FULL_SCAN_SECONDS regardless — walk ARTRANS from the durable
   watermark forward and enqueue one complete event per invoice found.

Layer 2 is what makes the guarantee hold. mtime is an unreliable trigger on
Pervasive (files are held open and flushed lazily, so mtime may not move when
a transaction commits, or may move at an unrelated checkpoint). The periodic
scan runs regardless of mtime, so a missed mtime change delays an invoice by at
most one full-scan interval — it never loses it.

Ordering of operations (this is the whole fix)
----------------------------------------------
Original::

    self._mtimes[filename] = mtime   # watermark advanced FIRST
    _push_webhook(entity_type)       # delivery attempted, may fail -> LOST

Now::

    rows = scan_after(watermark)                    # find work
    events = [extract(r) for r in rows]             # build complete records
    outbox.enqueue_batch(events, watermark=...)     # events + watermark commit
                                                    #   in ONE transaction
    sender.nudge()                                  # delivery happens later,
                                                    #   retried until 2xx

The watermark can never advance past an event that was not durably stored. A
crash between enqueue and send leaves the event pending, so it is retried on
restart rather than lost.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, List, Optional, Set

import events as ev
import invoice_extract
import odbc_client as odbc
import sage_schema as schema
from config import get_settings
from outbox import get_outbox
from sender import nudge_sender

logger = logging.getLogger("bridge.watcher")

#: Watermark key for the AR invoice scan cursor.
WM_INVOICE = "invoice_scan_cursor"

#: .DAT filename → entity label. Used only as a cheap "look here" hint.
DAT_ENTITY_MAP: Dict[str, str] = {
    "CUSTOMER.DAT":  "customer",
    "VENDOR.DAT":    "vendor",
    "EMPLOYEE.DAT":  "employee",
    "INVENTRY.DAT":  "inventory",
    "ACCOUNT.DAT":   "account",
    "ARTRANS.DAT":   "ar_transaction",
    "ARDETAIL.DAT":  "ar_transaction",
    "APTRANS.DAT":   "ap_transaction",
    "APDETAIL.DAT":  "ap_transaction",
    "SOHEADER.DAT":  "sales_order",
    "SODETAIL.DAT":  "sales_order",
    "POHEADER.DAT":  "purchase_order",
    "PODETAIL.DAT":  "purchase_order",
    "JRNLHDR.DAT":   "journal_entry",
    "JRNLROW.DAT":   "journal_entry",
    "PAYROLL.DAT":   "payroll",
}

#: Entity types the bridge extracts in full. Everything else gets a legacy
#: change-ping so SynBot's existing pull path still handles it.
FULLY_EXTRACTED = {"ar_transaction"}


class SageDataWatcher:
    """Polls Sage for changes and enqueues durable events."""

    def __init__(self) -> None:
        self._mtimes: Dict[str, float] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Event, not sleep(): shutdown is immediate rather than waiting out a
        # 60s poll interval. The original took up to 60s to notice a stop and
        # its join(timeout=5) gave up while the thread kept running.
        self._wake = threading.Event()
        self._last_full_scan = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        settings = get_settings()

        if not settings.SAGE_MOCK and not os.path.isdir(settings.SAGE_COMPANY_PATH):
            logger.error(
                "Sage company path does not exist: %s — watcher NOT started. "
                "Set SAGE_COMPANY_PATH correctly and restart.",
                settings.SAGE_COMPANY_PATH,
            )
            return

        # Seed mtimes so startup does not treat every file as freshly changed.
        # Unlike the original this is NOT how we avoid missing work: the
        # durable watermark drives correctness, and the first scan below picks
        # up everything created while we were down.
        self._seed_mtimes(settings.SAGE_COMPANY_PATH)

        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="SageDataWatcher"
        )
        self._thread.start()
        logger.info(
            "SageDataWatcher started — polling %s every %ds, full scan every %ds",
            settings.SAGE_COMPANY_PATH,
            settings.WATCHER_POLL_SECONDS,
            settings.WATCHER_FULL_SCAN_SECONDS,
        )

    def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                logger.warning("Watcher thread still running after 30s")
        logger.info("SageDataWatcher stopped.")

    def _seed_mtimes(self, company_path: str) -> None:
        for filename in DAT_ENTITY_MAP:
            fpath = os.path.join(company_path, filename)
            try:
                if os.path.isfile(fpath):
                    self._mtimes[filename] = os.path.getmtime(fpath)
            except OSError as exc:
                logger.debug("Cannot stat %s: %s", fpath, exc)

    # ── main loop ────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        settings = get_settings()

        # Catch-up scan on startup. This is what recovers invoices created
        # while the service was stopped — the case the original silently
        # discarded by re-seeding mtimes and moving on.
        logger.info("Startup catch-up scan — recovering anything missed while down.")
        try:
            self._scan_invoices()
        except Exception:
            logger.exception("Startup catch-up scan failed (will retry on next cycle)")

        while self._running:
            try:
                self._tick()
            except Exception:
                # Never let a bug kill the thread: a dead watcher looks healthy
                # from outside while silently syncing nothing.
                logger.exception("Watcher tick failed (continuing)")

            self._wake.wait(timeout=settings.WATCHER_POLL_SECONDS)
            self._wake.clear()

    def _tick(self) -> None:
        settings = get_settings()
        changed = self._detect_changed_entities()
        now = time.time()

        due_full_scan = (now - self._last_full_scan) >= settings.WATCHER_FULL_SCAN_SECONDS

        if "ar_transaction" in changed or due_full_scan:
            if due_full_scan:
                logger.debug("Periodic full scan due (mtime-independent).")
            self._scan_invoices()
            self._last_full_scan = now

        # Entity types we don't extract in full still get a change-ping so
        # SynBot's existing pull-based sync keeps working unchanged.
        for entity_type in sorted(changed - FULLY_EXTRACTED):
            self._enqueue_change_ping(entity_type)

    def _detect_changed_entities(self) -> Set[str]:
        """Return entity labels whose .DAT files changed since the last poll."""
        settings = get_settings()
        company_path = settings.SAGE_COMPANY_PATH
        changed: Set[str] = set()

        if settings.SAGE_MOCK:
            return changed

        for filename, entity_type in DAT_ENTITY_MAP.items():
            fpath = os.path.join(company_path, filename)
            try:
                if not os.path.isfile(fpath):
                    continue
                mtime = os.path.getmtime(fpath)
            except OSError as exc:
                logger.debug("Cannot stat %s: %s", fpath, exc)
                continue
            if mtime != self._mtimes.get(filename):
                self._mtimes[filename] = mtime
                changed.add(entity_type)

        if changed:
            logger.info("Sage .DAT change detected: %s", sorted(changed))
        return changed

    # ── invoice scan ─────────────────────────────────────────────────────────

    def _scan_invoices(self) -> int:
        """
        Scan ARTRANS forward from the durable watermark and enqueue events.

        Returns the number of new events enqueued.

        Correctness rests on two rules:
          1. Events and the watermark commit in ONE transaction.
          2. The watermark advances only over rows we successfully extracted.
             An invoice we could not read leaves the cursor behind it, so it is
             retried next cycle instead of being skipped.
        """
        settings = get_settings()
        ob = get_outbox()
        cursor = ob.get_watermark(WM_INVOICE) or None

        total_enqueued = 0
        pages = 0

        while self._running and pages < settings.WATCHER_MAX_PAGES_PER_TICK:
            try:
                rows = odbc.scan_after(
                    "ar_transactions",
                    schema.ARTrans.ROWID,
                    cursor,
                    limit=settings.WATCHER_SCAN_PAGE_SIZE,
                )
            except Exception as exc:
                logger.error(
                    "Invoice scan failed at cursor=%s: %s — watermark unchanged, "
                    "will retry next cycle.", cursor, exc,
                )
                return total_enqueued

            if not rows:
                break

            batch = []
            highest_ok: Optional[str] = None

            for row in rows:
                key_col = schema.ARTrans.ROWID.lower()
                sage_id = str(row.get(key_col, row.get("sage_id", ""))).strip()
                if not sage_id:
                    logger.warning("Invoice row with no ID — skipping: %r", row)
                    continue

                record = invoice_extract.extract_invoice(sage_id, header_row=row)
                if record is None:
                    # Stop advancing here. Everything before this invoice is
                    # committed; this one and everything after is retried.
                    logger.warning(
                        "Invoice %s not extractable — halting scan at this point "
                        "so it is retried rather than skipped.", sage_id,
                    )
                    break

                batch.append({
                    "event_id": ev.make_event_id("invoice", sage_id, record),
                    "entity_type": "invoice",
                    "sage_id": sage_id,
                    "payload": ev.build_envelope("invoice", sage_id, record),
                })
                highest_ok = sage_id

            if batch and highest_ok is not None:
                try:
                    n = ob.enqueue_batch(
                        batch,
                        watermark_name=WM_INVOICE,
                        watermark_value=highest_ok,
                    )
                    total_enqueued += n
                    cursor = highest_ok
                except Exception:
                    logger.exception(
                        "Enqueue failed — watermark NOT advanced, nothing lost."
                    )
                    return total_enqueued
            else:
                break

            pages += 1
            if len(rows) < settings.WATCHER_SCAN_PAGE_SIZE:
                break

        if total_enqueued:
            logger.info(
                "Invoice scan enqueued %d event(s); cursor now %s",
                total_enqueued, cursor,
            )
            nudge_sender()
        return total_enqueued

    # ── legacy change ping ───────────────────────────────────────────────────

    def _enqueue_change_ping(self, entity_type: str) -> None:
        """Enqueue a legacy 'data_changed' ping for a non-extracted entity."""
        ob = get_outbox()
        # Token derives from the observed mtimes, so an unchanged state
        # produces the same event_id and dedupes instead of spamming.
        token = str(sorted(
            (f, m) for f, m in self._mtimes.items()
            if DAT_ENTITY_MAP.get(f) == entity_type
        ))
        envelope = ev.build_change_ping(entity_type, token)
        try:
            ob.enqueue_batch([{
                "event_id": envelope["event_id"],
                "entity_type": entity_type,
                "sage_id": None,
                "payload": envelope,
            }])
            nudge_sender()
        except Exception:
            logger.exception("Could not enqueue change ping for %s", entity_type)

    # ── manual trigger ───────────────────────────────────────────────────────

    def force_scan(self) -> int:
        """Run an invoice scan now. Exposed via POST /sync/scan."""
        return self._scan_invoices()

    def reset_watermark(self, value: str = "") -> None:
        """
        Rewind the scan cursor to force a re-read.

        Safe: re-scanned invoices regenerate their existing deterministic
        event_ids, so SynBot dedupes them. Use after fixing a schema mapping.
        """
        get_outbox().set_watermark(WM_INVOICE, value)
        logger.warning("Invoice watermark reset to %r — next scan re-reads.", value)


# ── module-level singleton ───────────────────────────────────────────────────

_watcher = SageDataWatcher()


def start_watcher() -> None:
    _watcher.start()


def stop_watcher() -> None:
    _watcher.stop()


def get_watcher() -> SageDataWatcher:
    return _watcher
