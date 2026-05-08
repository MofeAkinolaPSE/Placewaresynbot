"""routers/payments.py — Customer receipts and vendor payments."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from auth import verify_api_key
import sdk_client as sdk

router = APIRouter(prefix="/payments", tags=["payments"])
_auth = Depends(verify_api_key)


class CustomerReceiptCreate(BaseModel):
    customer_id: str
    date: str
    amount: float
    reference: str = ""
    invoice_id: Optional[str] = None
    deposit_ticket_id: str = ""


@router.get("/received", response_model=List[Dict[str, Any]])
def list_customer_receipts(
    request: Request,
    customer_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = Depends(verify_api_key),
):
    """List payments received from customers."""
    from datetime import date as _date
    try:
        fd = _date.fromisoformat(from_date) if from_date else None
        return sdk.sdk_get_customer_receipts(customer_id=customer_id, from_date=fd, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.post("/received", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def apply_customer_receipt(
    request: Request,
    body: CustomerReceiptCreate,
    _: None = Depends(verify_api_key),
):
    """Record a payment received from a customer and optionally apply to an invoice."""
    try:
        return sdk.sdk_apply_customer_receipt(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
