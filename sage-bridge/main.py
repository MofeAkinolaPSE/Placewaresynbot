"""
main.py — Sage Bridge Service entry point.

Runs on the Windows 7 machine where Sage 50 2013 is installed. Exposes a REST
API (default port 7070) that SynBot calls for Sage read/write operations, and
runs two background threads that push new invoices to SynBot:

    SageDataWatcher  — detects new/changed invoices, enqueues durable events
    OutboxSender     — delivers queued events, retrying until acknowledged

See ARCHITECTURE section of INSTALL.md for how those two interact.

Startup sequence:
  1. Load and validate settings (refuses placeholder secrets)
  2. Open the durable outbox (SQLite) — recovers anything pending from before
  3. Load Sage.Peachtree.API.dll via pythonnet, open the company session
  4. Start the outbox sender, then the watcher
  5. Serve HTTP

Degraded start is deliberate: if the SDK fails to load the service still starts
in ODBC-read-only mode and still drains any pending outbox events, rather than
refusing to run and stranding queued invoices.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import odbc_client as odbc
import sdk_client as sdk
from config import get_settings
from outbox import get_outbox
from sender import start_sender, stop_sender
from watcher import get_watcher, start_watcher, stop_watcher

from routers.accounts import router as accounts_router
from routers.customers import router as customers_router
from routers.employees import router as employees_router
from routers.inventory import router as inventory_router
from routers.invoices import router as invoices_router
from routers.journal import router as journal_router
from routers.payments import router as payments_router
from routers.purchase_orders import router as purchase_orders_router
from routers.sales_orders import router as sales_orders_router
from routers.sync import router as sync_router
from routers.vendors import router as vendors_router

BRIDGE_VERSION = "2.0.0"


# ── Logging ──────────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    """
    Configure rotating file + console logging.

    Two fixes over the original:
      * The path was relative, so under NSSM (CWD = C:\\Windows\\system32) the
        log landed somewhere unexpected or failed to open. Paths now resolve
        against the bridge directory — see config._resolve_relative.
      * There was no rotation at all. On a machine running unattended for
        months that grows without bound until the disk fills.
    """
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.LOG_FILE), exist_ok=True)

    handlers: list = [
        logging.handlers.RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=settings.LOG_MAX_BYTES,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    ]
    # A service has no console; only add one when running interactively.
    if sys.stdout is not None and sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=handlers,
    )
    # httpx logs every request at INFO; that is one line per delivered event.
    logging.getLogger("httpx").setLevel(logging.WARNING)


_setup_logging()
settings = get_settings()
logger = logging.getLogger("bridge.main")


# ── Lifecycle ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "=== Sage Bridge %s starting (mock=%s) ===", BRIDGE_VERSION, settings.SAGE_MOCK
    )

    # Outbox first: it may already hold undelivered events from a previous run,
    # and we want the sender draining them even if Sage itself is unavailable.
    outbox = get_outbox()
    stats = outbox.stats()
    if stats["pending"]:
        logger.warning(
            "Recovered %d undelivered event(s) from the previous run "
            "(oldest %.0fs). They will be delivered now.",
            stats["pending"], stats["oldest_pending_age_seconds"] or 0,
        )
    if stats["failed"]:
        logger.error(
            "%d event(s) are parked as FAILED and need attention. "
            "Inspect via GET /sync/status, replay via POST /sync/outbox/replay.",
            stats["failed"],
        )

    if not settings.SAGE_MOCK:
        try:
            sdk.load_sdk(settings.SAGE_API_DLL_PATH, settings.SAGE_INSTALL_DIR)
            logger.info("Sage SDK loaded.")
        except RuntimeError as exc:
            logger.error("SDK load failed: %s", exc)
            logger.warning(
                "Continuing in ODBC-read-only mode. Invoice extraction will fall "
                "back to ODBC and records will be marked completeness=partial."
            )

        try:
            sdk.init_session(
                settings.SAGE_COMPANY_PATH, settings.SAGE_APPLICATION_ID
            )
            logger.info("Sage company session opened: %s", settings.SAGE_COMPANY_PATH)
        except Exception as exc:
            logger.error("Sage company session failed: %s", exc)
            logger.warning(
                "Continuing without an SDK session. If this is a fresh install, "
                "the SDK authorization prompt may still be pending — see INSTALL.md."
            )

        ok, msg = odbc.check_connection()
        if ok:
            logger.info("ODBC connection verified.")
        else:
            logger.error(
                "ODBC connection FAILED: %s — invoice detection cannot run until "
                "this is fixed. Common cause: 64-bit Python against the 32-bit "
                "Pervasive driver. Run verify_onsite.py to diagnose.", msg,
            )

    # Sender before watcher, so a scan's events start draining immediately.
    start_sender()
    start_watcher()

    try:
        yield
    finally:
        logger.info("Shutting down...")
        stop_watcher()
        stop_sender()          # finishes the in-flight request, leaves rest pending
        try:
            outbox.purge_sent(settings.OUTBOX_RETAIN_SENT_DAYS)
        except Exception:
            logger.debug("Outbox purge on shutdown failed", exc_info=True)
        odbc.close_all()
        try:
            if sdk._sage_session:
                sdk._sage_session.close()
        except Exception:
            pass
        final = outbox.stats()
        if final["pending"]:
            logger.warning(
                "%d event(s) still pending at shutdown — they are durably stored "
                "and will be delivered on next start.", final["pending"],
            )
        logger.info("=== Sage Bridge stopped ===")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sage Bridge",
    description="Middleware connecting SynBot to Sage 50 2013 on Windows 7.",
    version=BRIDGE_VERSION,
    lifespan=lifespan,
    # Off by default: these expose the full API surface unauthenticated.
    docs_url="/docs" if settings.BRIDGE_ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.BRIDGE_ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.BRIDGE_ENABLE_DOCS else None,
)

# CORS: this is a server-to-server bridge with no browser client, so the
# default is no origins at all. The original allowed "*", which let any page
# the operator visited probe the bridge from inside the LAN.
_origins = [o.strip() for o in settings.BRIDGE_CORS_ORIGINS.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["X-Bridge-API-Key", "Content-Type"],
    )
    logger.info("CORS enabled for: %s", _origins)


# ── Error handling ───────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Return an opaque error to the caller and keep the detail in the log.

    The original returned str(exc) in the response body, leaking driver
    messages, filesystem paths and connection strings to anything that could
    reach port 7070.
    """
    logger.error(
        "Unhandled exception on %s %s", request.method, request.url.path, exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal bridge error",
            "detail": "See the bridge log for details.",
            "path": request.url.path,
        },
    )


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
def health():
    """
    Liveness + readiness probe. No auth, so it stays usable for monitoring.

    Reports only booleans and counts — no paths, versions of Sage, or error
    strings that would help an unauthenticated caller.
    """
    odbc_ok, _ = odbc.check_connection()
    sdk_state = sdk.sdk_health()
    stats = get_outbox().stats()
    watcher_state = get_watcher().health()

    # watcher_healthy is part of the degraded test on purpose: a watcher that
    # never started leaves the outbox permanently empty, which otherwise looks
    # identical to "no new invoices" and reported ok forever.
    degraded = (
        (not odbc_ok)
        or stats["failed"] > 0
        or not watcher_state["healthy"]
    )
    return {
        "status": "degraded" if degraded else "ok",
        "service": "sage-bridge",
        "version": BRIDGE_VERSION,
        "odbc_connected": odbc_ok,
        "sdk_healthy": bool(sdk_state.get("healthy")),
        "watcher_healthy": watcher_state["healthy"],
        "watcher_last_scan_age_seconds": watcher_state["last_scan_age_seconds"],
        "outbox_pending": stats["pending"],
        "outbox_failed": stats["failed"],
    }


# ── Routers ──────────────────────────────────────────────────────────────────

for _r in (
    customers_router, invoices_router, vendors_router, inventory_router,
    employees_router, accounts_router, sales_orders_router,
    purchase_orders_router, payments_router, journal_router, sync_router,
):
    app.include_router(_r)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.BRIDGE_HOST,
        port=settings.BRIDGE_PORT,
        reload=False,
        log_config=None,      # keep our rotating handlers
        access_log=False,     # one line per request fills the disk over months
    )
