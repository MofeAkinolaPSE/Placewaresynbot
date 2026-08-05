"""routers/vendors.py — Vendor / AP endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from auth import verify_api_key
import odbc_client as odbc
import sdk_client as sdk

router = APIRouter(prefix="/vendors", tags=["vendors"])
_auth = Depends(verify_api_key)


class VendorCreate(BaseModel):
    id: str
    name: str
    address1: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    phone: str = ""
    email: str = ""
    contact: str = ""


class VendorBillLine(BaseModel):
    description: str = ""
    quantity: float = 1.0
    unit_price: float = 0.0
    gl_account: str = ""
    item_id: str = ""


class VendorBillCreate(BaseModel):
    vendor_id: str
    date: str
    due_date: Optional[str] = None
    reference: str = ""
    lines: List[VendorBillLine]


@router.get("", response_model=List[Dict[str, Any]])
def list_vendors(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    _: None = _auth,
):
    where = None
    params = None
    if search:
        where = "NAME LIKE ?"
        params = (f"%{search}%",)
    try:
        return odbc.fetch_all("vendors", where=where, params=params, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc


@router.get("/{vendor_id}", response_model=Dict[str, Any])
def get_vendor(request: Request, vendor_id: str, _: None = _auth):
    try:
        row = odbc.fetch_one("vendors", where="VENDID = ?", params=(vendor_id,))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc
    if not row:
        raise HTTPException(status_code=404, detail=f"Vendor '{vendor_id}' not found")
    return row


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_vendor(request: Request, body: VendorCreate, _: None = _auth):
    try:
        return sdk.sdk_create_vendor(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.get("/bills", response_model=List[Dict[str, Any]])
def list_vendor_bills(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = _auth,
):
    """List all vendor bills (AP transactions)."""
    try:
        return sdk.sdk_get_vendor_invoices(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.post("/bills", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_vendor_bill(request: Request, body: VendorBillCreate, _: None = _auth):
    """
    Record a vendor bill (AP invoice) in Sage.

    Returns **501** in live mode: the Sage 50 2013 SDK exposes no Save() on
    PurchaseInvoice, so vendor bills cannot be created through it. 501 rather
    than 503 because retrying will never help — see KNOWN_LIMITATIONS.md.
    """
    try:
        return sdk.sdk_create_vendor_invoice(body.model_dump())
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
