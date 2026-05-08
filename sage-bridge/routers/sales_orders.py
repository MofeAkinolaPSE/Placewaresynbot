"""routers/sales_orders.py — Sales Order endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from auth import verify_api_key
import sdk_client as sdk

router = APIRouter(prefix="/sales-orders", tags=["sales-orders"])
_auth = Depends(verify_api_key)


class SOLine(BaseModel):
    description: str = ""
    quantity: float = 1.0
    unit_price: float = 0.0
    item_id: str = ""


class SalesOrderCreate(BaseModel):
    customer_id: str
    date: str
    good_through_date: Optional[str] = None
    ship_date: Optional[str] = None
    po_number: str = ""
    reference: str = ""
    lines: List[SOLine]


@router.get("", response_model=List[Dict[str, Any]])
def list_sales_orders(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    _: None = _auth,
):
    try:
        return sdk.sdk_get_sales_orders(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_sales_order(request: Request, body: SalesOrderCreate, _: None = _auth):
    try:
        return sdk.sdk_create_sales_order(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
