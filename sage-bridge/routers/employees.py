"""routers/employees.py — Employee endpoints (read-only for now)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import verify_api_key
import sdk_client as sdk

router = APIRouter(prefix="/employees", tags=["employees"])
_auth = Depends(verify_api_key)


@router.get("", response_model=List[Dict[str, Any]])
def list_employees(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = _auth,
):
    """Return all employees from Sage 50."""
    try:
        return sdk.sdk_get_employees(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.get("/payroll", response_model=List[Dict[str, Any]])
def list_payroll_checks(
    request: Request,
    from_date: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = _auth,
):
    """Return payroll check records, optionally filtered by start date."""
    from datetime import date as _date
    try:
        fd = _date.fromisoformat(from_date) if from_date else None
        return sdk.sdk_get_payroll_checks(from_date=fd, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
