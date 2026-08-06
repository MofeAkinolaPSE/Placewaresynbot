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
from typing import Any, Dict, List, Optional, Set

import events as ev
import invoice_extract
import odbc_client as odbc
import sage_schema as schema
import sdk_client as sdk
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
        # Liveness/observability state. Without these a watcher that never
        # started — or one whose thread died — is indistinguishable from a
        # healthy one that simply has nothing to do: the outbox stays empty
        # either way. health() surfaces the difference.
        self._start_error: str = ""
        self._last_tick: float = 0.0
        self._last_scan_at: float = 0.0
        self._last_scan_error: str = ""
        self._total_enqueued: int = 0
        self._last_reconcile_at: float = 0.0
        self._last_reconcile_error: str = ""

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        settings = get_settings()

        if not settings.SAGE_MOCK and not os.path.isdir(settings.SAGE_COMPANY_PATH):
            self._start_error = (
                "Sage company path does not exist: {}".format(settings.SAGE_COMPANY_PATH)
            )
            logger.error(
                "%s — watcher NOT started. Set SAGE_COMPANY_PATH correctly and "
                "restart. /health will report status=degraded until then.",
                self._start_error,
            )
            return

        self._start_error = ""

        # Seed the reconcile clock so the first sweep lands one interval after
        # boot rather than immediately. A full enumeration on every service
        # restart would be punishing on the target hardware, and a restart is
        # not evidence that anything was deleted. Force one with POST
        # /sync/reconcile when it is actually wanted.
        self._last_reconcile_at = time.time()

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
                self._last_scan_error = ""
            except Exception as exc:
                # Never let a bug kill the thread: a dead watcher looks healthy
                # from outside while silently syncing nothing.
                self._last_scan_error = str(exc)[:300]
                logger.exception("Watcher tick failed (continuing)")

            # Stamped on every completed pass, success or failure. health()
            # compares it against now() to detect a wedged loop.
            self._last_tick = time.time()

            self._wake.wait(timeout=settings.WATCHER_POLL_SECONDS)
            self._wake.clear()

        logger.info("Watcher loop exited.")

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

        # Reconciliation is a full-table enumeration, so it runs on its own much
        # slower schedule (default daily) — it is the only thing that can see a
        # deletion, but it is far too expensive to run every poll.
        if settings.RECONCILE_ENABLED:
            due_reconcile = (
                (now - self._last_reconcile_at) >= settings.RECONCILE_INTERVAL_SECONDS
            )
            if due_reconcile:
                logger.info("Reconciliation sweep due — checking for voided/deleted invoices.")
                try:
                    self.reconcile()
                except Exception:
                    logger.exception("Reconcile failed (will retry next interval)")
                finally:
                    # Stamp even on failure so a persistently broken sweep does
                    # not re-run a full enumeration on every single poll.
                    self._last_reconcile_at = time.time()

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

            # One loaded invoice snapshot for the whole page. Without this each
            # extract_invoice() re-enumerates every invoice in the company —
            # quadratic, and unfinishable on a real company file. See
            # sdk_client.bulk_read.
            with sdk.bulk_read():
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
                            "Invoice %s not extractable — halting scan at this "
                            "point so it is retried rather than skipped.", sage_id,
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
                    # Register the IDs so the reconciliation sweep knows they
                    # exist and can notice if they later disappear. Best-effort:
                    # a failure here costs delete detection for these IDs until
                    # the next sweep re-observes them, never a lost invoice.
                    try:
                        ob.record_seen("invoice", [e["sage_id"] for e in batch])
                    except Exception:
                        logger.exception("Could not register scanned IDs (continuing)")
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

        self._last_scan_at = time.time()
        self._total_enqueued += total_enqueued

        if total_enqueued:
            logger.info(
                "Invoice scan enqueued %d event(s); cursor now %s",
                total_enqueued, cursor,
            )
            nudge_sender()
        return total_enqueued

    # ── reconciliation sweep (void / delete detection) ───────────────────────

    def reconcile(self) -> Dict[str, Any]:
        """
        Detect invoices that have disappeared from Sage and emit deletes.

        Why this exists
        ---------------
        The forward scan walks ARTRANS from a watermark upward, so it sees new
        and edited rows but structurally cannot see a row that is gone. A void
        that deletes the row left SynBot's cache showing an active invoice
        forever, with no mechanism that would ever correct it.

        (A void that *keeps* the row and flips a status column is already
        handled — the content fingerprint changes, so it looks like an edit.)

        How it stays safe
        -----------------
        Emitting a delete is destructive downstream, so a partial or failed
        enumeration must never be mistaken for "everything was deleted". Three
        guards, in order:

        1. **Abort on any read error.** A single failed page aborts the whole
           sweep with no deletes emitted. A half-read table looks exactly like
           mass deletion otherwise.
        2. **Empty-result guard.** If Sage returns zero invoices while we know
           of many, that is a connectivity or permissions fault, not a company
           that deleted its entire AR history. Abort and log loudly.
        3. **Bulk-delete ceiling.** If the diff exceeds
           ``RECONCILE_MAX_DELETE_RATIO`` of known records, abort and require an
           operator to look. Real voids trickle; a mass disappearance is a bug
           or a restored-from-backup company file.

        Returns a summary dict; also drives GET /sync/reconcile.
        """
        settings = get_settings()
        ob = get_outbox()
        known = set(ob.live_ids("invoice"))

        if not known:
            logger.debug("Reconcile: nothing known yet, nothing to compare.")
            self._last_reconcile_at = time.time()
            return {"status": "skipped", "reason": "no known records", "deleted": 0}

        # ── enumerate every invoice ID currently in Sage ─────────────────────
        present: Set[str] = set()
        cursor: Optional[str] = None
        pages = 0
        # Hard page ceiling: guards against a cursor that fails to advance
        # (duplicate keys) turning this into an infinite loop.
        max_pages = 10_000

        while pages < max_pages:
            try:
                rows = odbc.scan_after(
                    "ar_transactions",
                    schema.ARTrans.ROWID,
                    cursor,
                    limit=settings.WATCHER_SCAN_PAGE_SIZE,
                )
            except Exception as exc:
                # Guard 1.
                logger.error(
                    "Reconcile aborted: enumeration failed at cursor=%s (%s). "
                    "No deletes emitted — a partial read is indistinguishable "
                    "from mass deletion.", cursor, exc,
                )
                self._last_reconcile_error = str(exc)[:300]
                return {"status": "aborted", "reason": "enumeration failed", "deleted": 0}

            if not rows:
                break

            key_col = schema.ARTrans.ROWID.lower()
            page_ids = [
                str(r.get(key_col, r.get("sage_id", ""))).strip()
                for r in rows
            ]
            page_ids = [i for i in page_ids if i]
            if not page_ids:
                break

            present.update(page_ids)

            # Take the LAST row as the next cursor, not max(). scan_after emits
            # ORDER BY <key>, so the last row is the page's true high-water mark
            # under the DATABASE's collation. Python's max() applies string
            # ordering, which disagrees with a numeric key column the moment IDs
            # pass a digit boundary — max(["9","10"]) is "9", so the cursor goes
            # backwards, the next page repeats rows, and enumeration stops early
            # with `present` incomplete. In reconcile that means live invoices
            # look deleted.
            new_cursor = page_ids[-1]
            if new_cursor == cursor:
                # Cursor failed to advance — stop rather than spin.
                break
            cursor = new_cursor
            pages += 1

            if len(rows) < settings.WATCHER_SCAN_PAGE_SIZE:
                break

        # Guard 2.
        if not present:
            logger.error(
                "Reconcile aborted: Sage returned zero invoices but %d are known. "
                "Treating as a connectivity/permissions fault, not deletion.",
                len(known),
            )
            self._last_reconcile_error = "enumeration returned no rows"
            return {"status": "aborted", "reason": "empty enumeration", "deleted": 0}

        missing = sorted(known - present)

        # Guard 3.
        if missing:
            ratio = len(missing) / len(known)
            if ratio > settings.RECONCILE_MAX_DELETE_RATIO:
                logger.error(
                    "Reconcile aborted: %d of %d known invoices (%.0f%%) are "
                    "missing, above the %.0f%% ceiling. No deletes emitted. "
                    "This usually means the company file was swapped or "
                    "restored. Investigate, then raise "
                    "RECONCILE_MAX_DELETE_RATIO to override.",
                    len(missing), len(known), ratio * 100,
                    settings.RECONCILE_MAX_DELETE_RATIO * 100,
                )
                self._last_reconcile_error = (
                    "bulk-delete ceiling exceeded ({} of {})".format(len(missing), len(known))
                )
                return {
                    "status": "aborted",
                    "reason": "bulk delete ceiling exceeded",
                    "would_delete": len(missing),
                    "deleted": 0,
                }

        # Refresh last_seen for everything still there — cheap, and it keeps the
        # registry honest if an ID was tombstoned in error and has reappeared.
        try:
            ob.record_seen("invoice", sorted(present))
        except Exception:
            logger.exception("Reconcile: could not refresh seen records (continuing)")

        if not missing:
            self._last_reconcile_at = time.time()
            self._last_reconcile_error = ""
            logger.info("Reconcile: %d invoice(s) present, none missing.", len(present))
            return {"status": "ok", "present": len(present), "deleted": 0}

        batch = []
        for sid in missing:
            envelope = ev.build_delete_envelope("invoice", sid)
            batch.append({
                "event_id": envelope["event_id"],
                "entity_type": "invoice",
                "sage_id": sid,
                "payload": envelope,
            })

        try:
            ob.enqueue_batch(batch)
            ob.mark_deleted("invoice", missing)
        except Exception:
            logger.exception(
                "Reconcile: could not enqueue delete events — not tombstoned, "
                "so the next sweep retries them."
            )
            return {"status": "error", "reason": "enqueue failed", "deleted": 0}

        self._last_reconcile_at = time.time()
        self._last_reconcile_error = ""
        logger.warning(
            "Reconcile: %d invoice(s) no longer in Sage — delete events enqueued: %s",
            len(missing), missing[:20],
        )
        nudge_sender()
        return {"status": "ok", "present": len(present), "deleted": len(missing)}

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

    # ── liveness ─────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """
        Report whether detection is actually running.

        This is the check that distinguishes "no new invoices" from "nothing is
        looking for invoices". Both leave the outbox empty, so without this the
        service reports ok while syncing nothing — the single most dangerous
        failure mode for an unattended bridge.

        ``healthy`` is False when the thread was never started (bad company
        path), has died, or has not completed a pass in well over the poll
        interval.
        """
        settings = get_settings()
        now = time.time()
        alive = bool(self._thread and self._thread.is_alive())

        # Generous multiple of the poll interval: a slow ODBC scan on old
        # hardware must not be reported as a stall.
        stall_after = max(settings.WATCHER_POLL_SECONDS * 5, 300)
        since_tick = (now - self._last_tick) if self._last_tick else None
        stalled = bool(self._running and since_tick is not None and since_tick > stall_after)

        return {
            "running": self._running,
            "thread_alive": alive,
            "healthy": alive and self._running and not stalled and not self._start_error,
            "stalled": stalled,
            "start_error": self._start_error,
            "last_tick_age_seconds": round(since_tick, 1) if since_tick is not None else None,
            "last_scan_age_seconds": (
                round(now - self._last_scan_at, 1) if self._last_scan_at else None
            ),
            "last_scan_error": self._last_scan_error,
            "events_enqueued_since_start": self._total_enqueued,
            "reconcile_enabled": settings.RECONCILE_ENABLED,
            "last_reconcile_age_seconds": (
                round(now - self._last_reconcile_at, 1) if self._last_reconcile_at else None
            ),
            "last_reconcile_error": self._last_reconcile_error,
        }

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
