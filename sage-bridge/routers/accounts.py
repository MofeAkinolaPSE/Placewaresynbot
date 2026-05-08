"""routers/accounts.py — Chart of Accounts endpoints."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import verify_api_key
import sdk_client as sdk

router = APIRouter(prefix="/accounts", tags=["accounts"])
_auth = Depends(verify_api_key)


@router.get("", response_model=List[Dict[str, Any]])
def list_accounts(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = _auth,
):
    """Return full Chart of Accounts from Sage 50."""
    try:
        return sdk.sdk_get_accounts(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
