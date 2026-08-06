"""
routers/sync.py — Sync status, bulk historical pull, webhook registration,
                   and ODBC schema discovery endpoints.
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import verify_api_key
import odbc_client as odbc
import sdk_client as sdk
from config import get_settings
from outbox import get_outbox
from sender import nudge_sender
from watcher import WM_INVOICE, get_watcher

router = APIRouter(prefix="/sync", tags=["sync"])
_auth = Depends(verify_api_key)


@router.get("/status", response_model=Dict[str, Any])
def sync_status(request: Request, _: None = _auth):
    """
    Full operational status: connectivity, outbox depth, watermark, failures.

    This is the endpoint to check when asking "is the sync healthy?". Unlike
    the original it reads sync state from the durable outbox rather than an
    in-memory dict that reset to empty on every restart.
    """
    settings = get_settings()
    odbc_ok, odbc_error = odbc.check_connection()
    sdk_state = sdk.sdk_health()
    ob = get_outbox()
    stats = ob.stats()
    watcher_state = get_watcher().health()

    return {
        "bridge_version": "2.0.0",
        "sage_company_path": settings.SAGE_COMPANY_PATH,
        "sage_odbc_dsn": settings.SAGE_ODBC_DSN,
        "sage_odbc_conn_str_configured": bool(settings.SAGE_ODBC_CONN_STR),
        "mock_mode": settings.SAGE_MOCK,
        "odbc_connected": odbc_ok,
        "odbc_error": "" if odbc_ok else odbc_error,
        "sdk": sdk_state,
        "watcher": watcher_state,
        "outbox": stats,
        "invoice_watermark": ob.get_watermark(WM_INVOICE) or None,
        # Healthy means: Sage readable, detection actually running, and nothing
        # stuck undelivered. The watcher term matters — without it a bridge that
        # never started scanning reported healthy indefinitely.
        "healthy": odbc_ok and stats["failed"] == 0 and watcher_state["healthy"],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@router.get("/outbox", response_model=Dict[str, Any])
def outbox_status(request: Request, _: None = _auth):
    """Outbox counts and the age of the oldest undelivered event."""
    return get_outbox().stats()


@router.post("/outbox/replay", response_model=Dict[str, Any])
def replay_failed(request: Request, _: None = _auth):
    """
    Requeue every event parked as failed.

    Safe to call repeatedly: replayed events carry their original deterministic
    event_id, so SynBot deduplicates anything it already applied. Use this
    after fixing whatever caused the failures (bad webhook key, SynBot down
    past the retry window).
    """
    n = get_outbox().requeue_failed()
    nudge_sender()
    return {"requeued": n}


@router.post("/scan", response_model=Dict[str, Any])
def force_scan(request: Request, _: None = _auth):
    """
    Run an invoice scan immediately instead of waiting for the next poll.

    Useful after a config fix, or to confirm end-to-end flow during setup.
    """
    try:
        enqueued = get_watcher().force_scan()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Scan failed: {}".format(exc)) from exc
    return {"enqueued": enqueued}


@router.post("/reconcile", response_model=Dict[str, Any])
def force_reconcile(request: Request, _: None = _auth):
    """
    Run the void/delete reconciliation sweep immediately.

    Enumerates every invoice ID in Sage and diffs it against what the bridge
    has synced; anything missing gets a ``record_deleted`` event. This is the
    only path that detects an invoice deleted outright — the forward scan
    cannot see deletions.

    Expensive (full table enumeration), so it normally runs on
    RECONCILE_INTERVAL_SECONDS. Use this after a suspected void, or during
    setup to confirm the sweep works.

    Safe: guarded against partial reads, empty results and bulk deletion — see
    SageDataWatcher.reconcile. A guard trip returns status="aborted" and emits
    nothing.
    """
    try:
        return get_watcher().reconcile()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Reconcile failed: {}".format(exc)
        ) from exc


@router.post("/watermark/reset", response_model=Dict[str, Any])
def reset_watermark(request: Request, value: str = "", _: None = _auth):
    """
    Rewind the invoice scan cursor so the next scan re-reads from ``value``.

    Empty value = re-read the entire AR table. Safe: regenerated events reuse
    their deterministic IDs and are deduplicated by SynBot. Intended for use
    after correcting a sage_schema.py mapping.
    """
    get_watcher().reset_watermark(value)
    return {"watermark": value, "note": "next scan re-reads from this cursor"}


@router.get("/company", response_model=Dict[str, Any])
def company_info(request: Request, _: None = _auth):
    """Return Sage company information."""
    try:
        return sdk.sdk_get_company_info()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.get("/schema/tables", response_model=List[str])
def list_odbc_tables(request: Request, _: None = _auth):
    """
    Return all ODBC-visible table names from the Pervasive DSN.
    Use this during initial setup to verify the DSN is connected and
    to confirm the exact table names in this company's DDF files.
    """
    try:
        return odbc.list_odbc_tables()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc


@router.get("/historical/{entity_type}", response_model=List[Dict[str, Any]])
def bulk_historical_pull(
    request: Request,
    entity_type: str,
    limit: int = 2000,
    offset: int = 0,
    _: None = _auth,
):
    """
    Bulk-pull historical records for a given entity type.
    entity_type must be one of the keys in odbc_client.TABLE_MAP.
    Used for the one-time migration job to seed SynBot's Supabase cache.
    """
    if entity_type not in odbc.TABLE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown entity_type '{entity_type}'. Valid: {sorted(odbc.TABLE_MAP.keys())}",
        )
    try:
        rows = odbc.fetch_all(entity_type, limit=limit, offset=offset)
        # Durable, unlike the previous in-memory dict which reset on restart.
        get_outbox().set_watermark(
            "historical_pull:" + entity_type,
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        return rows
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc


@router.get("/quotes", response_model=List[Dict[str, Any]])
def list_quotes(request: Request, limit: int = 500, _: None = _auth):
    """Return all sales quotes."""
    try:
        return sdk.sdk_get_quotes(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.get("/jobs", response_model=List[Dict[str, Any]])
def list_jobs(request: Request, limit: int = 500, _: None = _auth):
    """Return all job costing records."""
    try:
        return sdk.sdk_get_jobs(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
