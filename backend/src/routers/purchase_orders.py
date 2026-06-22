from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Optional
from src.middleware import verify_jwt
from src.db import db
import logging

log = logging.getLogger(__name__)

try:
    from src.services.sage_adapter.service import _latest_batch_for_table
except ImportError:
    def _latest_batch_for_table(table: str):
        return None

router = APIRouter(prefix="/procurement", tags=["procurement"])


@router.get("/purchase-orders")
async def list_purchase_orders(
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    limit: int = 200,
    _u=Depends(verify_jwt),
):
    try:
        batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
        q = db.table("sage_purchase_orders_snapshot").select(
            "po_id, po_number, vendor_id, order_date, expected_delivery_date, "
            "total_amount, tax_amount, discount_amount, net_amount, status, "
            "warehouse_id, created_by"
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


@router.get("/purchase-orders/summary")
async def purchase_orders_summary(_u=Depends(verify_jwt)):
    try:
        batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
        q = db.table("sage_purchase_orders_snapshot").select("status, net_amount")
        if batch:
            q = q.eq("batch_id", batch)
        rows = q.execute().data or []
        total = len(rows)
        open_count = sum(1 for r in rows if r.get("status") in ("open", "pending", "approved"))
        total_value = sum(float(r.get("net_amount") or 0) for r in rows)
        open_value = sum(
            float(r.get("net_amount") or 0)
            for r in rows
            if r.get("status") in ("open", "pending", "approved")
        )
        return {
            "total_pos": total,
            "open_pos": open_count,
            "total_value": total_value,
            "open_value": open_value,
        }
    except Exception:
        log.exception("Failed to get PO summary")
        raise HTTPException(status_code=500, detail="Internal server error")
