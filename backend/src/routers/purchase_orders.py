from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Literal, Dict, Any
import datetime as _dt
import logging

from src.middleware import verify_jwt
from src.db import db, audit_event

log = logging.getLogger(__name__)

try:
    from src.services.sage_adapter.service import _latest_batch_for_table
except ImportError:
    def _latest_batch_for_table(table: str):
        return None

router = APIRouter(prefix="/procurement", tags=["procurement"])

_PROCUREMENT_ROLES = {"admin", "ops", "operations", "finance", "procurement", "management"}

# POs stuck at "open" for this long past their expected delivery (or order
# date, if that's missing too) are treated as stale/inactive rather than
# genuinely pending -- both because a real bulk historical PO export mapped
# every blank-status row to "open" (fixed going forward in
# sage_csv_import.py's _map_purchase_orders, but the defaulting already
# overwrote the signal on existing rows), and because a pharma-distribution
# PO normally resolves within weeks of its expected date under real ops.
_STALE_OPEN_DAYS = 180


def _require_procurement(request: Request) -> Dict[str, Any]:
    payload = verify_jwt(request)
    roles = {str(r).lower() for r in payload.get("roles", [])}
    if not roles & _PROCUREMENT_ROLES:
        raise HTTPException(status_code=403, detail="Procurement, ops, or finance role required")
    return payload


def _effective_date(r: Dict[str, Any]) -> Optional[_dt.date]:
    d = r.get("expected_delivery_date") or r.get("order_date")
    if not d:
        return None
    try:
        return _dt.date.fromisoformat(str(d)[:10])
    except Exception:
        return None


def _is_stale(r: Dict[str, Any], today: _dt.date) -> bool:
    eff = _effective_date(r)
    if eff is None:
        # No dates at all to judge by -- treat as stale rather than counting
        # an undateable row as a live pending order forever.
        return True
    return (today - eff).days > _STALE_OPEN_DAYS


def _is_open(r: Dict[str, Any], today: _dt.date) -> bool:
    status = r.get("status")
    if status in ("pending", "approved"):
        # Only ever set by an explicit business action, not the CSV import's
        # blank-status default -- no staleness disambiguation needed.
        return True
    if status == "open":
        # "open" is the ambiguous bucket: both genuinely fresh orders and
        # (for existing pre-fix data) the import's old blank-status default
        # land here, so it's the one that needs date-based disambiguation.
        return not _is_stale(r, today)
    return False


def _is_overdue(r: Dict[str, Any], today: _dt.date) -> bool:
    if not _is_open(r, today):
        return False
    eff = r.get("expected_delivery_date")
    if not eff:
        return False
    try:
        return _dt.date.fromisoformat(str(eff)[:10]) < today
    except Exception:
        return False


@router.get("/purchase-orders")
def list_purchase_orders(
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    limit: int = 200,
    _u=Depends(_require_procurement),
):
    try:
        batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
        q = db.table("sage_purchase_orders_snapshot").select(
            "po_id, po_number, vendor_id, order_date, expected_delivery_date, "
            "total_amount, tax_amount, discount_amount, net_amount, status, "
            "warehouse_id, created_by, closed_at, closed_by, close_reason"
        )
        if batch:
            q = q.eq("batch_id", batch)
        if status:
            q = q.eq("status", status)
        if vendor_id:
            q = q.eq("vendor_id", vendor_id)
        rows = q.order("order_date", desc=True).limit(limit).execute().data or []

        # Enrich with vendor names from sage_vendors_snapshot
        if rows:
            vendor_ids = list({r["vendor_id"] for r in rows if r.get("vendor_id")})
            vendor_batch = _latest_batch_for_table("sage_vendors_snapshot")
            vq = db.table("sage_vendors_snapshot").select("vendor_id, vendor_name")
            if vendor_batch:
                vq = vq.eq("batch_id", vendor_batch)
            vendor_rows = vq.in_("vendor_id", vendor_ids).execute().data or []
            vendor_map = {v["vendor_id"]: v["vendor_name"] for v in vendor_rows}
            for r in rows:
                r["vendor_name"] = vendor_map.get(r.get("vendor_id"), r.get("vendor_id"))

        return rows
    except Exception:
        log.exception("Failed to list purchase orders")
        raise HTTPException(status_code=500, detail="Internal server error")


def compute_po_summary(client=db) -> Dict[str, Any]:
    """PO KPI summary -- extracted so the ACE Workstation aggregator
    (services/intelligence.py's get_workstation_summary()) can call it
    directly instead of duplicating this query/status logic.

    Once ACE Books is live the "purchase orders" are the stock orders
    (services/stock_orders.py): the Sage snapshot this used to count is the
    supplier-invoice history, not orders."""
    from src.fin.readmodel import live
    if live():
        from src.services import stock_orders
        orders = [o for o in stock_orders.list_orders(limit=2000) if o["status"] in ("recommended", "approved", "ordered")]
        overdue = [o for o in orders if o["overdue"]]
        return {
            "total_pos": len(orders),
            "open_pos": len(orders),
            "total_value": sum(float(o["est_value"] or 0) for o in orders),
            "open_value": sum(float(o["est_value"] or 0) for o in orders),
            "overdue_pos": len(overdue),
            "overdue_value": sum(float(o["est_value"] or 0) for o in overdue),
        }
    today = _dt.date.today()
    batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
    q = client.table("sage_purchase_orders_snapshot").select(
        "status, net_amount, expected_delivery_date, order_date"
    )
    if batch:
        q = q.eq("batch_id", batch)
    rows = q.execute().data or []

    total = len(rows)
    open_count = sum(1 for r in rows if _is_open(r, today))
    total_value = sum(float(r.get("net_amount") or 0) for r in rows)
    open_value = sum(float(r.get("net_amount") or 0) for r in rows if _is_open(r, today))
    overdue_count = sum(1 for r in rows if _is_overdue(r, today))
    overdue_value = sum(float(r.get("net_amount") or 0) for r in rows if _is_overdue(r, today))
    return {
        "total_pos": total,
        "open_pos": open_count,
        "total_value": total_value,
        "open_value": open_value,
        "overdue_pos": overdue_count,
        "overdue_value": overdue_value,
    }


@router.get("/purchase-orders/summary")
def purchase_orders_summary(_u=Depends(_require_procurement)):
    try:
        return compute_po_summary()
    except Exception:
        log.exception("Failed to get PO summary")
        raise HTTPException(status_code=500, detail="Internal server error")


class PoStatusUpdate(BaseModel):
    status: Literal["closed", "cancelled"]
    reason: Optional[str] = None


@router.patch("/purchase-orders/{po_id}/status")
def update_po_status(po_id: str, payload: PoStatusUpdate, user=Depends(_require_procurement)):
    """Close or cancel a PO. Restricted to these two target values -- this is
    the specific human action requested (closing stale/fulfilled orders), not
    a full PO lifecycle state machine."""
    try:
        batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
        q = db.table("sage_purchase_orders_snapshot").select("po_id, status").eq("po_id", po_id)
        if batch:
            q = q.eq("batch_id", batch)
        existing = q.limit(1).execute().data or []
        if not existing:
            raise HTTPException(status_code=404, detail=f"Purchase order {po_id} not found")
        previous_status = existing[0].get("status")

        now = _dt.datetime.utcnow().isoformat()
        update_q = db.table("sage_purchase_orders_snapshot").update({
            "status": payload.status,
            "closed_at": now,
            "closed_by": user.get("sub") or "unknown",
            "close_reason": payload.reason,
        }).eq("po_id", po_id)
        if batch:
            update_q = update_q.eq("batch_id", batch)
        update_q.execute()

        audit_event(
            "close_purchase_order",
            {"po_id": po_id, "previous_status": previous_status, "new_status": payload.status, "reason": payload.reason},
            actor_id=user.get("sub"),
            event_class="procurement",
            action="close" if payload.status == "closed" else "cancel",
            subject_type="purchase_order",
            subject_id=po_id,
        )
        return {"success": True, "po_id": po_id, "status": payload.status}
    except HTTPException:
        raise
    except Exception:
        log.exception(f"Failed to update PO {po_id} status")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/purchase-orders/backfill-close-stale")
def backfill_close_stale(user=Depends(verify_jwt)):
    """Admin-only, idempotent: closes existing POs that have been sitting at
    'open' for more than _STALE_OPEN_DAYS past their expected delivery date --
    the real backlog created by the CSV importer's old blank-status-to-'open'
    default (fixed going forward, but the defaulting already overwrote the
    signal on existing rows, so this is a one-time-per-batch remediation, not
    an ongoing background sweep)."""
    roles = {str(r).lower() for r in user.get("roles", [])}
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    try:
        today = _dt.date.today()
        batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
        q = db.table("sage_purchase_orders_snapshot").select(
            "po_id, status, expected_delivery_date, order_date"
        ).eq("status", "open")
        if batch:
            q = q.eq("batch_id", batch)
        rows = q.execute().data or []

        stale_po_ids = [r["po_id"] for r in rows if _is_stale(r, today)]
        closed_count = 0
        now = _dt.datetime.utcnow().isoformat()
        for po_id in stale_po_ids:
            update_q = db.table("sage_purchase_orders_snapshot").update({
                "status": "closed",
                "closed_at": now,
                "closed_by": "system_backfill",
                "close_reason": f"Auto-closed: no confirmed activity, >{_STALE_OPEN_DAYS}d past expected delivery",
            }).eq("po_id", po_id)
            if batch:
                update_q = update_q.eq("batch_id", batch)
            update_q.execute()
            closed_count += 1

        audit_event(
            "backfill_close_stale_purchase_orders",
            {"closed_count": closed_count, "stale_cutoff_days": _STALE_OPEN_DAYS},
            actor_id=user.get("sub"),
            event_class="procurement",
            action="backfill_close",
        )
        return {"success": True, "closed_count": closed_count, "total_open_scanned": len(rows)}
    except Exception:
        log.exception("Failed to backfill-close stale purchase orders")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Stock orders, reorder plan, supplier purchases and directory (ACE Books)
# ---------------------------------------------------------------------------

from src.services import stock_orders as _so  # noqa: E402


def _fail(exc: Exception, what: str):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=409, detail=str(exc))
    log.exception(what)
    raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stock-orders/summary")
def stock_orders_summary(_u=Depends(_require_procurement)):
    try:
        return _so.summary()
    except Exception as exc:
        _fail(exc, "stock order summary failed")


@router.get("/reorder-plan")
def reorder_plan(_u=Depends(_require_procurement)):
    try:
        return _so.reorder_plan()
    except Exception as exc:
        _fail(exc, "reorder plan failed")


@router.get("/stock-orders")
def list_stock_orders(status: Optional[str] = None, limit: int = 300, _u=Depends(_require_procurement)):
    try:
        return {"data": _so.list_orders(status, min(max(limit, 1), 2000))}
    except Exception as exc:
        _fail(exc, "stock order list failed")


class StockOrderCreate(BaseModel):
    sku: str
    qty: float
    supplier_id: Optional[str] = None
    unit_cost: Optional[float] = None
    notes: Optional[str] = None


@router.post("/stock-orders")
def create_stock_order(payload: StockOrderCreate, user=Depends(_require_procurement)):
    try:
        row = _so.raise_order(payload.sku, payload.qty, user.get("sub"), payload.supplier_id, payload.unit_cost, payload.notes)
        audit_event("stock_order_raised", {"sku": payload.sku, "qty": payload.qty, "order_id": row["id"]}, actor_id=user.get("sub"),
                    event_class="procurement", action="raise_stock_order", subject_type="stock_order", subject_id=row["id"])
        return row
    except Exception as exc:
        _fail(exc, "stock order create failed")


class StockOrderAction(BaseModel):
    qty: Optional[float] = None
    supplier_id: Optional[str] = None
    po_reference: Optional[str] = None
    expected_date: Optional[_dt.date] = None
    unit_cost: Optional[float] = None
    reason: Optional[str] = None


@router.post("/stock-orders/{order_id}/{action}")
def stock_order_action(order_id: str, action: Literal["approve", "order", "cancel"], payload: StockOrderAction,
                             user=Depends(_require_procurement)):
    try:
        res = _so.update_order(order_id, action, user.get("sub"), **payload.dict())
        audit_event(f"stock_order_{action}", {"order_id": order_id, **payload.dict(exclude_none=True)}, actor_id=user.get("sub"),
                    event_class="procurement", action=f"{action}_stock_order", subject_type="stock_order", subject_id=order_id)
        return res
    except Exception as exc:
        _fail(exc, "stock order action failed")


@router.get("/purchases")
def supplier_purchases(search: str = "", supplier_id: Optional[str] = None, limit: int = 100, offset: int = 0,
                             _u=Depends(_require_procurement)):
    try:
        return _so.purchases(search, supplier_id, min(max(limit, 1), 500), max(offset, 0))
    except Exception as exc:
        _fail(exc, "purchases list failed")


@router.get("/suppliers")
def supplier_directory(_u=Depends(_require_procurement)):
    try:
        return _so.supplier_directory()
    except Exception as exc:
        _fail(exc, "supplier directory failed")
