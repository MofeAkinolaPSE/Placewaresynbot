"""
main.py — Sage Bridge Service entry point.

This FastAPI application runs on the Windows 7 machine where Sage 50 2013
is installed.  It exposes a REST API (port 7070) that SynBot (running in
the Ubuntu VirtualBox VM on the LAN) calls for all Sage read/write operations.

Startup sequence:
  1. Load settings from .env
  2. Load Sage.Peachtree.API.dll via pythonnet
  3. Open Sage company session (SDK)
  4. Start file-system watcher for change detection
  5. Start uvicorn HTTP server

Usage (Windows command prompt / PowerShell, on the Sage machine):
  pip install -r requirements.txt
  uvicorn main:app --host 0.0.0.0 --port 7070
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
import sdk_client as sdk
from watcher import start_watcher, stop_watcher

from routers.customers import router as customers_router
from routers.invoices import router as invoices_router
from routers.vendors import router as vendors_router
from routers.inventory import router as inventory_router
from routers.employees import router as employees_router
from routers.accounts import router as accounts_router
from routers.sales_orders import router as sales_orders_router
from routers.purchase_orders import router as purchase_orders_router
from routers.payments import router as payments_router
from routers.journal import router as journal_router
from routers.sync import router as sync_router

# ── Logging setup ─────────────────────────────────────────────────────────────

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sage_bridge.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("bridge.main")


# ── Application lifecycle ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: load SDK, open Sage session, start watcher."""
    logger.info("=== Sage Bridge starting (MOCK MODE: %s) ===", settings.SAGE_MOCK)

    if settings.SAGE_MOCK:
        logger.info("SAGE_MOCK=true — skipping SDK/ODBC initialisation. All responses use mock data.")
        start_watcher()
        yield
        stop_watcher()
        logger.info("=== Sage Bridge stopped ===")
        return

    # Live mode — load SDK and open company session
    try:
        sdk.load_sdk(settings.SAGE_API_DLL_PATH)
        logger.info("Sage SDK loaded.")
    except RuntimeError as exc:
        logger.error("SDK load failed: %s", exc)
        logger.warning("Bridge will run in ODBC-read-only mode (SDK write operations disabled).")

    try:
        sdk.init_session(settings.SAGE_COMPANY_PATH)
        logger.info("Sage company session opened: %s", settings.SAGE_COMPANY_PATH)
    except RuntimeError as exc:
        logger.error("Sage company session failed: %s", exc)
        logger.warning("Bridge will run without an active SDK session.")

    start_watcher()

    yield

    # Shutdown
    stop_watcher()
    try:
        if sdk._sage_session:
            sdk._sage_session.close()
    except Exception:
        pass
    logger.info("=== Sage Bridge stopped ===")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sage Bridge",
    description=(
        "Middleware service connecting SynBot (Ubuntu/Docker) to Sage 50 2013 "
        "(Windows 7 local server).  Runs on the same machine as Sage."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Disable /docs in production if needed; keep enabled for setup/debug
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow calls from the VM (SynBot) on the LAN.
# In production, restrict origins to the VM's specific LAN IP.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # TODO: tighten to VM IP once deployed
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ── Global error handler ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal bridge error", "detail": str(exc)},
    )


# ── Health check (no auth required) ──────────────────────────────────────────

@app.get("/health", tags=["health"])
def health():
    """Liveness probe — no auth required."""
    return {"status": "ok", "service": "sage-bridge", "version": "1.0.0"}


# ── Register routers ──────────────────────────────────────────────────────────

app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(vendors_router)
app.include_router(inventory_router)
app.include_router(employees_router)
app.include_router(accounts_router)
app.include_router(sales_orders_router)
app.include_router(purchase_orders_router)
app.include_router(payments_router)
app.include_router(journal_router)
app.include_router(sync_router)


# ── Direct run ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.BRIDGE_HOST,
        port=settings.BRIDGE_PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )
