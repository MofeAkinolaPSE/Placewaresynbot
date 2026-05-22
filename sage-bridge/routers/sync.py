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

router = APIRouter(prefix="/sync", tags=["sync"])
_auth = Depends(verify_api_key)

# In-memory record of last sync timestamps per entity type
_last_sync: Dict[str, str] = {}


@router.get("/status", response_model=Dict[str, Any])
def sync_status(request: Request, _: None = _auth):
    """Return connectivity status, Sage company path, and last sync timestamps."""
    settings = get_settings()
    odbc_ok = False
    sdk_ok = False
    odbc_error = ""
    sdk_error = ""
    try:
        odbc.fetch_all("company", limit=1)
        odbc_ok = True
    except Exception as exc:
        odbc_error = str(exc)
    try:
        sdk.sdk_get_company_info()
        sdk_ok = True
    except Exception as exc:
        sdk_error = str(exc)

    return {
        "bridge_version": "1.0.0",
        "sage_company_path": settings.SAGE_COMPANY_PATH,
        "sage_odbc_dsn": settings.SAGE_ODBC_DSN,
        "sage_odbc_conn_str_configured": bool(settings.SAGE_ODBC_CONN_STR),
        "odbc_connected": odbc_ok,
        "sdk_connected": sdk_ok,
        "odbc_error": odbc_error,
        "sdk_error": sdk_error,
        "last_sync": _last_sync,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


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
        _last_sync[entity_type] = datetime.datetime.utcnow().isoformat() + "Z"
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
