from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, validator
from typing import Dict, Any, List, Optional
from src.middleware import verify_jwt, require_role
from src.services.inventory import (
    StockInBooksError,
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
import datetime as dt

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
    """Roles allowed to view inventory: the Inventory & Quality department (stock, QC, compliance),
    finance and sales. 'operations' and 'management' were missing though the page lets them in."""
    payload = verify_jwt(request)
    roles = payload.get("roles", [])
    allowed = {"admin", "ops", "operations", "procurement", "finance", "sales", "quality_assurance", "qa", "management"}
    
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

    except StockInBooksError as e:
        raise HTTPException(409, detail=str(e))
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


def _books_only_items(q: str, have: set) -> List[Dict[str, Any]]:
    """Lots ACE Books knows that the older Sage item snapshot behind v_inventory does not (a new
    lot code, e.g. 'Avaxim inj. Ped (R)'), with their stock and next batch from ACE Books."""
    try:
        from src.fin.db import q as fq, tx
        with tx() as conn:
            rows = fq(conn, """
                SELECT p.sku, p.name, NULL::text AS category, p.standard_price AS selling_price, NULL::text AS company_id,
                       COALESCE((SELECT SUM(l.qty_remaining) FROM fin_cost_layers l WHERE l.legal_entity_id=p.legal_entity_id
                                 AND l.sku=p.sku AND l.qty_remaining > 0), 0) AS current_stock,
                       nb.batch_number, COALESCE(nb.expiry_date, p.lot_expiry) AS expiry_date
                FROM fin_products p
                LEFT JOIN LATERAL (SELECT b.batch_number, b.expiry_date FROM fin_cost_layers l JOIN fin_batches b ON b.id=l.batch_id
                                   WHERE l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku AND l.qty_remaining > 0
                                   ORDER BY b.expiry_date NULLS LAST LIMIT 1) nb ON TRUE
                WHERE p.status='ACTIVE' AND p.product_type='INVENTORY' AND (p.name ILIKE %s OR p.sku ILIKE %s)
                LIMIT 300""", (f"%{q}%", f"%{q}%"))
        out = []
        for r in rows:
            if r["sku"] in have:
                continue
            r["current_stock"] = float(r["current_stock"] or 0)
            r["selling_price"] = float(r["selling_price"]) if r["selling_price"] is not None else None
            r["expiry_date"] = str(r["expiry_date"]) if r["expiry_date"] else None
            out.append(r)
        return out
    except Exception as exc:
        logging.warning("books item lookup for search failed: %s", exc)
        return []


def _rank_for_sale(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The client's Sage uses one item code per lot (HEXAXIM (A)…(Q)), so a name search returns
    many old, empty or expired lots. Sellable stock comes first, then a lot sold in Sage without
    its receipt (flagged - it is the newest stock, waiting for Finance to record the receipt),
    newest lot first; empty and expired lots last, labelled."""
    today = dt.date.today().isoformat()
    pending: Dict[str, Any] = {}
    try:
        skus = [r["sku"] for r in rows if r.get("sku")]
        if skus:
            pending = {p["key"]: p for p in (db.table("fin_data_exceptions").select("key,quantity")
                                               .eq("kind", "STOCK_SHORT_LOT").eq("status", "OPEN").in_("key", skus)
                                               .execute().data or [])}
    except Exception:
        pending = {}
    for r in rows:
        stock = float(r.get("current_stock") or 0)
        expired = bool(r.get("expiry_date")) and str(r["expiry_date"])[:10] < today
        r["sellable"] = stock > 0 and not expired
        r["receipt_pending"] = r.get("sku") in pending
        r["stock_note"] = ("receipt not yet recorded in the books - ask Finance" if r["receipt_pending"] and not r["sellable"]
                           else "expired" if expired and stock > 0 else "no stock" if stock <= 0 else None)
    return sorted(rows, key=lambda r: (not r["sellable"], not r["receipt_pending"],
                                       -(dt.date.fromisoformat(str(r["expiry_date"])[:10]).toordinal() if r.get("expiry_date") else 0),
                                       [-ord(ch) for ch in str(r.get("sku") or "")]))


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
    # one item code per lot: rank a wide set of matches, then return the best `limit`
    pool = max(limit, 300)
    try:
        rows = (
            db.table("v_inventory")
            .select("sku,name,category,current_stock,company_id,selling_price,batch_number,expiry_date")
            .ilike("name", f"%{q}%")
            .limit(pool)
            .execute()
            .data
            or []
        )
        if len(rows) < pool:
            sku_rows = (
                db.table("v_inventory")
                .select("sku,name,category,current_stock,company_id,selling_price,batch_number,expiry_date")
                .ilike("sku", f"%{q}%")
                .limit(pool - len(rows))
                .execute()
                .data
                or []
            )
            seen = {r["sku"] for r in rows}
            rows.extend(r for r in sku_rows if r["sku"] not in seen)
        rows.extend(_books_only_items(q, {r["sku"] for r in rows}))
        return {"data": _rank_for_sale(rows)[:limit]}
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


@router.get("/workspace/analytics")
async def workspace_analytics(
    company_id: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(require_inventory_read),
):
    """Decision-support overview for the inventory dashboard: risk tiers,
    expiry exposure by value, dead stock, reorder candidates and demand
    coverage. One call so the dashboard doesn't fan out per SKU."""
    try:
        from src.services.inventory_analytics import get_analytics_overview
        return {"data": get_analytics_overview(company_id=company_id)}
    except Exception as e:
        logging.error(f"Inventory analytics error: {e}")
        raise HTTPException(500, detail="Failed to compute inventory analytics")


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
