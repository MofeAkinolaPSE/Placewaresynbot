"""routers/invoices.py — Sales Invoice endpoints (AR)."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from auth import verify_api_key
import sdk_client as sdk
import odbc_client as odbc

router = APIRouter(prefix="/invoices", tags=["invoices"])
_auth = Depends(verify_api_key)


class InvoiceLine(BaseModel):
    description: str = ""
    quantity: float = 1.0
    unit_price: float = 0.0
    gl_account: str = ""
    item_id: str = ""


class InvoiceCreate(BaseModel):
    customer_id: str
    date: str = Field(..., description="ISO date YYYY-MM-DD")
    due_date: str = Field(..., description="ISO date YYYY-MM-DD")
    lines: List[InvoiceLine]
    invoice_number: str = ""
    ship_date: Optional[str] = None
    po_number: str = ""
    reference: str = ""
    note: str = ""


@router.get("", response_model=List[Dict[str, Any]])
def list_invoices(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    customer_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    to_date: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    _: None = _auth,
):
    """
    Return sales invoices.  Filter by customer_id and/or date range.
    Reads via ODBC for speed.
    """
    where_parts = []
    params: List[Any] = []

    if customer_id:
        where_parts.append("ACCTID = ?")
        params.append(customer_id)
    if from_date:
        where_parts.append("DATE >= ?")
        params.append(from_date)
    if to_date:
        where_parts.append("DATE <= ?")
        params.append(to_date)

    where = " AND ".join(where_parts) if where_parts else None
    try:
        rows = odbc.fetch_all(
            "ar_transactions",
            where=where,
            params=tuple(params) if params else None,
            limit=limit,
            offset=offset,
        )
        return rows
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc


@router.get("/{invoice_id}", response_model=Dict[str, Any])
def get_invoice(
    request: Request,
    invoice_id: str,
    _: None = _auth,
):
    """Return a single invoice by Sage ID (uses SDK for full line-level detail)."""
    try:
        result = sdk.sdk_get_invoice(invoice_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")
    return result


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_invoice(
    request: Request,
    body: InvoiceCreate,
    _: None = _auth,
):
    """
    Create a Sales Invoice in Sage 50 via the official SDK.
    This triggers Sage's full business logic: ledger postings, tax calc, AR update.
    Returns the created invoice including its Sage ID.
    """
    try:
        result = sdk.sdk_create_invoice(body.model_dump())
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def void_invoice(
    request: Request,
    invoice_id: str,
    _: None = _auth,
):
    """Void (delete) a sales invoice in Sage. Use with caution."""
    try:
        found = sdk.sdk_void_invoice(invoice_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
    if not found:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")
