"""routers/inventory.py — Inventory / stock item endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import verify_api_key
import odbc_client as odbc
import sdk_client as sdk

router = APIRouter(prefix="/inventory", tags=["inventory"])
_auth = Depends(verify_api_key)


@router.get("", response_model=List[Dict[str, Any]])
def list_inventory(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, description="Partial item description match"),
    _: None = _auth,
):
    """
    Return inventory items.  ODBC read for high-volume access.
    Use search param for partial description filter.
    """
    where = None
    params = None
    if search:
        where = "DESCRIPT LIKE ?"
        params = (f"%{search}%",)
    try:
        return odbc.fetch_all("inventory", where=where, params=params, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ODBC error: {exc}") from exc


@router.get("/{item_id}", response_model=Dict[str, Any])
def get_inventory_item(request: Request, item_id: str, _: None = _auth):
    """Return a single inventory item with full SDK detail (includes GL accounts, reorder qty)."""
    try:
        result = sdk.sdk_get_inventory_item(item_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    return result


@router.get("/low-stock", response_model=List[Dict[str, Any]])
def low_stock_items(request: Request, _: None = _auth):
    """Return inventory items where quantity on hand is below reorder quantity."""
    try:
        all_items = sdk.sdk_get_inventory(limit=5000)
        return [
            item for item in all_items
            if item.get("quantity_on_hand", 0) <= item.get("reorder_quantity", 0)
            and item.get("reorder_quantity", 0) > 0
        ]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SDK error: {exc}") from exc
