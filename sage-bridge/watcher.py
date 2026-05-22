"""
watcher.py — Monitor the Sage 50 company data folder for file changes.

When Sage writes a transaction (invoice, customer update, etc.) the
corresponding .DAT file's modification timestamp changes.  We watch those
timestamps and push change-event webhooks to SynBot.

Strategy
--------
* Poll every WATCHER_POLL_SECONDS (default 60 s).
* Compare mtime of each tracked .DAT file against its last-known mtime.
* On change, record which entity type changed and push to SynBot via
  webhook.py.

NOTE: For Windows 7 (the Sage host), the watchdog library's inotify backend
is unavailable; it falls back to polling automatically — which is fine for
our use case.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Dict

import httpx

from config import get_settings

logger = logging.getLogger("bridge.watcher")

# Map .DAT filename → entity type label sent in the webhook payload.
# These are the standard Pervasive file names for Sage 50 Peachtree 2013.
# Update if the client's DDF uses different filenames (verify on first visit).
DAT_ENTITY_MAP: Dict[str, str] = {
    "CUSTOMER.DAT":  "customer",
    "VENDOR.DAT":    "vendor",
    "EMPLOYEE.DAT":  "employee",
    "INVENTRY.DAT":  "inventory",
    "ACCOUNT.DAT":   "account",
    "ARTRANS.DAT":   "ar_transaction",   # Sales invoices / receipts
    "ARDETAIL.DAT":  "ar_transaction",
    "APTRANS.DAT":   "ap_transaction",   # Vendor bills / payments
    "APDETAIL.DAT":  "ap_transaction",
    "SOHEADER.DAT":  "sales_order",
    "SODETAIL.DAT":  "sales_order",
    "POHEADER.DAT":  "purchase_order",
    "PODETAIL.DAT":  "purchase_order",
    "JRNLHDR.DAT":   "journal_entry",
    "JRNLROW.DAT":   "journal_entry",
    "PAYROLL.DAT":   "payroll",
}


class SageDataWatcher:
    """
    Polls the Sage company data folder and emits webhook events when
    .DAT files change.
    """

    def __init__(self) -> None:
        self._mtimes: Dict[str, float] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        settings = get_settings()
        company_path = settings.SAGE_COMPANY_PATH

        if not settings.SYNBOT_WEBHOOK_URL:
            logger.info("SYNBOT_WEBHOOK_URL not configured — file watcher disabled.")
            return

        if not os.path.isdir(company_path):
            logger.warning(
                "Sage company path does not exist: %s — file watcher disabled.", company_path
            )
            return

        # Seed initial mtimes so we don't fire events on startup
        self._seed_mtimes(company_path)
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(company_path,),
            daemon=True,
            name="SageDataWatcher",
        )
        self._thread.start()
        logger.info(
            "SageDataWatcher started — polling %s every %ds",
            company_path, settings.WATCHER_POLL_SECONDS,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("SageDataWatcher stopped.")

    def _seed_mtimes(self, company_path: str) -> None:
        for filename in DAT_ENTITY_MAP:
            fpath = os.path.join(company_path, filename)
            if os.path.isfile(fpath):
                self._mtimes[filename] = os.path.getmtime(fpath)

    def _poll_loop(self, company_path: str) -> None:
        settings = get_settings()
        while self._running:
            changed_entities: set[str] = set()
            for filename, entity_type in DAT_ENTITY_MAP.items():
                fpath = os.path.join(company_path, filename)
                if not os.path.isfile(fpath):
                    continue
                mtime = os.path.getmtime(fpath)
                if mtime != self._mtimes.get(filename):
                    self._mtimes[filename] = mtime
                    changed_entities.add(entity_type)

            if changed_entities:
                logger.info("Sage data changed — entity types: %s", changed_entities)
                for entity_type in changed_entities:
                    _push_webhook(entity_type)

            time.sleep(settings.WATCHER_POLL_SECONDS)


def _push_webhook(entity_type: str) -> None:
    """
    POST a change-event webhook to SynBot with exponential backoff retry.

    Retries up to 3 times on network errors or non-2xx responses before
    giving up.  Total max wait: ~14s (1s + 4s + 8s delays + request time).
    """
    settings = get_settings()
    url = settings.SYNBOT_WEBHOOK_URL
    if not url:
        return

    verify_tls: bool | str = True
    if settings.BRIDGE_INSECURE_SKIP_VERIFY:
        verify_tls = False
    elif settings.BRIDGE_CA_CERT_PATH:
        verify_tls = settings.BRIDGE_CA_CERT_PATH

    payload = {
        "source": "sage_bridge",
        "event": "data_changed",
        "entity_type": entity_type,
    }
    headers: dict[str, str] = {}
    if settings.SYNBOT_WEBHOOK_KEY:
        headers["X-Webhook-Key"] = settings.SYNBOT_WEBHOOK_KEY

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=10, verify=verify_tls) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code in (200, 202, 204):
                if attempt > 1:
                    logger.info(
                        "Webhook for %s succeeded on attempt %d.", entity_type, attempt
                    )
                return
            logger.warning(
                "Webhook for %s returned HTTP %d (attempt %d/%d).",
                entity_type, resp.status_code, attempt, max_attempts,
            )
        except Exception as exc:
            logger.warning(
                "Webhook push failed for %s (attempt %d/%d): %s",
                entity_type, attempt, max_attempts, exc,
            )

        if attempt < max_attempts:
            delay = 2 ** attempt   # 2s, 4s
            logger.info("Retrying webhook for %s in %ds...", entity_type, delay)
            time.sleep(delay)

    logger.error(
        "Webhook for %s failed after %d attempts — SynBot may be down.",
        entity_type, max_attempts,
    )


# Module-level singleton
_watcher = SageDataWatcher()


def start_watcher() -> None:
    _watcher.start()


def stop_watcher() -> None:
    _watcher.stop()
