from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, validator
from typing import Dict, Any, List, Optional
from src.middleware import verify_jwt, require_role
from src.services.inventory import (
    record_inventory_event,
    get_realtime_stock,
    get_inventory_summary
)
from src.services.inventory_workspace import (
    get_workspace_cards,
    get_family_detail,
    get_top_selling_items,
)
from ..db import db
import logging

router = APIRouter(prefix="/inventory", tags=["inventory"])
audit_logger = logging.getLogger("audit")

# --- Models ---

class InventoryEventRequest(BaseModel):
    sku: str
    quantity_change: float = Field(..., description="Positive for add, negative for remove")
    event_type: str = Field(..., description="SALE, RESTOCK, DAMAGE, EXPIRY, ADJUSTMENT")
    reference: Optional[str] = None

    @validator('quantity_change')
    def change_must_be_nonzero(cls, v):
        if v == 0:
            raise ValueError('quantity_change cannot be zero')
        return v
    
    @validator('event_type')
    def validate_event_type(cls, v):
        allowed = {'SALE', 'RESTOCK', 'DAMAGE', 'EXPIRY', 'ADJUSTMENT'}
        if v.upper() not in allowed:
            raise ValueError(f'event_type must be one of {allowed}')
        return v.upper()

# --- Dependencies ---

def require_inventory_write(request: Request) -> Dict[str, Any]:
    """Roles allowed to mutate inventory: admin, ops."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "ops", "finance"} # Finance might need to correct adjustments
    
    if not any(r in allowed for r in roles):
        audit_logger.warning({"event": "inventory_write_denied", "user": payload.get("sub")})
        raise HTTPException(403, "Insufficient privileges for inventory mutation")
    return payload

def require_inventory_read(request: Request) -> Dict[str, Any]:
    """Roles allowed to view inventory: admin, ops, finance, sales."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "ops", "finance", "sales"}
    
    if not any(r in allowed for r in roles):
        raise HTTPException(403, "Insufficient privileges to view inventory")
    return payload

# --- Endpoints ---

@router.post("/event")
async def post_inventory_event(
    event: InventoryEventRequest,
    user: Dict[str, Any] = Depends(require_inventory_write)
):
    """
    Record an operational inventory movement (append-only).
    Does not touch Sage 2013 data.
    """
    try:
        result = record_inventory_event(
            sku=event.sku,
            change=event.quantity_change,
            event_type=event.event_type,
            reference=event.reference,
            user_id=user.get("sub") or "unknown"
        )
        
        # Audio Log
        audit_logger.info({
            "event": "inventory_mutation",
            "sku": event.sku,
            "type": event.event_type,
            "change": event.quantity_change,
            "user": user.get("sub")
        })
        
        return {"success": True, "event": result}
        
    except Exception as e:
        logging.error(f"Inventory event error: {e}")
        raise HTTPException(500, detail="Failed to record inventory event")

@router.get("/sku/{sku}")
async def get_sku_stock(
    sku: str,
    user: Dict[str, Any] = Depends(require_inventory_read)
):
    """
    Get authoritative live stock: Baseline (Sage) + Delta (Events).
    """
    try:
        data = get_realtime_stock(sku)
        return {"data": data}
    except Exception as e:
        logging.error(f"Stock lookup error for {sku}: {e}")
        raise HTTPException(500, detail="Failed to retrieve stock data")

@router.get("/summary")
async def get_summary_view(
    request: Request,
    user: Dict[str, Any] = Depends(require_inventory_read)
):
    """Get aggregated view of active inventory items."""
    try:
        data = get_inventory_summary(limit=50)
        return {"data": data}
    except Exception as e:
        logging.error(f"Inventory summary error: {e}")
        raise HTTPException(500, detail="Failed to retrieve inventory summary")


@router.get("/items")
async def list_items(
    limit: int = 200,
    company_id: Optional[str] = Query(None, description="Filter by company: PlacewareNig or PlacewarePha"),
    user: Dict[str, Any] = Depends(require_inventory_read),
):
    """
    Return the full Sage 50 item catalogue with current stock quantities.
    Reads from v_inventory (Silver layer view) which deduplicates sage_items_snapshot
    and joins sage_inventory_snapshot, summing warehouse quantities per SKU.
    Optional company_id filter for multi-company setups.
    """
    try:
        q = db.table("v_inventory").select("*").limit(limit)
        if company_id:
            q = q.eq("company_id", company_id)
        rows = q.execute().data or []
        return {"data": rows, "total": len(rows)}
    except Exception as e:
        logging.error(f"Inventory items error: {e}")
        raise HTTPException(500, detail="Failed to retrieve inventory items")


@router.get("/search")
async def search_items(
    q: str = Query(..., min_length=1),
    limit: int = 20,
    user: Dict[str, Any] = Depends(require_inventory_read),
):
    """
    Item-name/SKU typeahead search, used by EntityAutocomplete pickers
    (Add Stock, Log Adjustment, walk-in item selection). This is the fix for
    api.inventory.search()'s previously-nonexistent GET /inventory?query=
    call, which silently 404'd on every keystroke for every caller.
    """
    try:
        rows = (
            db.table("v_inventory")
            .select("sku,name,category,current_stock,company_id,selling_price,batch_number,expiry_date")
            .ilike("name", f"%{q}%")
            .limit(limit)
            .execute()
            .data
            or []
        )
        if len(rows) < limit:
            sku_rows = (
                db.table("v_inventory")
                .select("sku,name,category,current_stock,company_id,selling_price,batch_number,expiry_date")
                .ilike("sku", f"%{q}%")
                .limit(limit - len(rows))
                .execute()
                .data
                or []
            )
            seen = {r["sku"] for r in rows}
            rows.extend(r for r in sku_rows if r["sku"] not in seen)
        return {"data": rows}
    except Exception as e:
        logging.error(f"Inventory search error: {e}")
        raise HTTPException(500, detail="Failed to search inventory")


@router.get("/workspace/cards")
async def workspace_cards(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(require_inventory_read),
):
    """Grouped, live-stock-only cards for the Inventory Workspace's main grid."""
    try:
        cards = get_workspace_cards(company_id=company_id, search=search)
        return {"data": cards, "total": len(cards)}
    except Exception as e:
        logging.error(f"Workspace cards error: {e}")
        raise HTTPException(500, detail="Failed to retrieve inventory workspace cards")


@router.get("/workspace/families/detail")
async def workspace_family_detail(
    family: str = Query(...),
    company_id: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(require_inventory_read),
):
    """Full member/batch breakdown + open reorder requests + top customers
    for one vaccine family -- the workspace's detail-popup payload."""
    try:
        return {"data": get_family_detail(company_id=company_id, family=family)}
    except Exception as e:
        logging.error(f"Workspace family detail error: {e}")
        raise HTTPException(500, detail="Failed to retrieve family detail")


@router.get("/workspace/top-sellers")
async def workspace_top_sellers(
    limit: int = 10,
    company_id: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(require_inventory_read),
):
    """All-time top movers by lifetime quantity sold. Deliberately not
    labeled "recently popular" -- there is no dated sales signal to build
    that on (see get_top_selling_items's docstring)."""
    try:
        return {"data": get_top_selling_items(limit=limit, company_id=company_id)}
    except Exception as e:
        logging.error(f"Workspace top-sellers error: {e}")
        raise HTTPException(500, detail="Failed to retrieve top sellers")


@router.get("/workspace/pending-reorders-count")
async def workspace_pending_reorders_count(user: Dict[str, Any] = Depends(require_inventory_read)):
    """Count of not-yet-received replenishment requests, for the workspace
    KPI strip. replenishment_requests has no list endpoint of its own today
    (only create/approve/create_po/received action endpoints in
    replenishment.py) -- this is a minimal read, not a full list surface."""
    try:
        rows = (
            db.table("replenishment_requests")
            .select("id")
            .neq("status", "received")
            .limit(5000)
            .execute()
            .data
            or []
        )
        return {"count": len(rows)}
    except Exception as e:
        logging.error(f"Pending reorders count error: {e}")
        raise HTTPException(500, detail="Failed to count pending reorders")
