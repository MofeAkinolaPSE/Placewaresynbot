"""routers/journal.py — General Journal Entry endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from auth import verify_api_key
import sdk_client as sdk

router = APIRouter(prefix="/journal", tags=["journal"])
_auth = Depends(verify_api_key)


class JournalLine(BaseModel):
    account_id: str
    debit: float = 0.0
    credit: float = 0.0
    description: str = ""


class JournalEntryCreate(BaseModel):
    date: str
    reference: str = ""
    lines: List[JournalLine]


@router.get("", response_model=List[Dict[str, Any]])
def list_journal_entries(
    request: Request,
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = _auth,
):
    """Return general journal entries, optionally filtered by date range."""
    from datetime import date as _date
    try:
        fd = _date.fromisoformat(from_date) if from_date else None
        td = _date.fromisoformat(to_date) if to_date else None
        return sdk.sdk_get_journal_entries(from_date=fd, to_date=td, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_journal_entry(
    request: Request,
    body: JournalEntryCreate,
    _: None = _auth,
):
    """
    Create a balanced general journal entry.
    The sum of debits must equal the sum of credits — validated before posting.
    """
    try:
        return sdk.sdk_create_journal_entry(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
