"""
routers/customers.py — Customer endpoints.

READ  : ODBC (fast, stateless)
WRITE : SDK (safe, transactional)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field

from auth import verify_api_key
import odbc_client as odbc
import sdk_client as sdk

router = APIRouter(prefix="/customers", tags=["customers"])

_auth = Depends(verify_api_key)


# ── Request / Response models ────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    id: str = Field(..., description="Sage customer ID/code (must be unique)")
    name: str
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    phone: str = ""
    fax: str = ""
    email: str = ""
    contact: str = ""
    credit_limit: float = 0.0
    sales_rep: str = ""


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    credit_limit: Optional[float] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[Dict[str, Any]])
def list_customers(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, description="Filter by name (partial match)"),
    _: None = _auth,
):
    """
    Return all customers from Sage via ODBC.
    Supports pagination (limit/offset) and partial name search.
    """
    where = None
    params = None
    if search:
        where = "NAME LIKE ?"
        params = (f"%{search}%",)
    try:
        rows = odbc.fetch_all("customers", where=where, params=params, limit=limit, offset=offset)
        return rows
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc


@router.get("/{customer_id}", response_model=Dict[str, Any])
def get_customer(
    request: Request,
    customer_id: str,
    _: None = _auth,
):
    """Return a single customer by Sage ID."""
    try:
        row = odbc.fetch_one("customers", where="CUSTID = ?", params=(customer_id,))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc
    if not row:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found")
    return row


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_customer(
    request: Request,
    body: CustomerCreate,
    _: None = _auth,
):
    """
    Create a new customer in Sage 50 via the official SDK.
    This is the safe write path — goes through Sage's own business logic.
    """
    try:
        result = sdk.sdk_create_customer(body.model_dump())
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.put("/{customer_id}", response_model=Dict[str, Any])
def update_customer(
    request: Request,
    customer_id: str,
    body: CustomerUpdate,
    _: None = _auth,
):
    """Update an existing customer in Sage 50 via the SDK."""
    # Only pass non-None fields
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    try:
        result = sdk.sdk_update_customer(customer_id, updates)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
