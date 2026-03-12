from __future__ import annotations
from typing import Dict, Any
from datetime import datetime, timezone
from src.db import db


def create_replenishment_request(sku: str, product_id: str | None, requested_qty: float, created_by: str | None = None) -> Dict[str, Any]:
    payload = {"sku": sku, "product_id": product_id, "requested_qty": requested_qty, "created_by": created_by}
    db.table("replenishment_requests").insert(payload).execute()
    return {"ok": True}


def approve_replenishment(request_id: str, approver: str | None = None) -> Dict[str, Any]:
    db.table("replenishment_requests").update({"status": "approved", "approved_by": approver}).eq("id", request_id).execute()
    return {"ok": True}


def create_po_for_request(request_id: str, po_id: str, created_by: str | None = None) -> Dict[str, Any]:
    db.table("replenishment_requests").update({"po_id": po_id, "status": "ordered"}).eq("id", request_id).execute()
    return {"ok": True}


def mark_replenishment_received(
    request_id: str,
    received_qty: float | None = None,
    actor: str | None = None,
) -> Dict[str, Any]:
    req_resp = db.table("replenishment_requests").select("id,sku,status").eq("id", request_id).limit(1).execute()
    req_rows = req_resp.data if hasattr(req_resp, "data") else []
    if not req_rows:
        return {"ok": False, "error": "request_not_found"}

    req = req_rows[0]
    sku = req.get("sku")

    note_parts = ["Auto-marked received"]
    if received_qty is not None:
        note_parts.append(f"qty={received_qty}")
    if actor:
        note_parts.append(f"by={actor}")

    db.table("replenishment_requests").update(
        {
            "status": "received",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "notes": "; ".join(note_parts),
        }
    ).eq("id", request_id).execute()

    # Best-effort: clear related low-stock alerts from alert feed.
    if sku:
        try:
            db.table("placeware_alerts").update({"status": "archived"}).eq("category", "inventory").ilike("title", f"%{sku}%").execute()
        except Exception:
            pass

    return {"ok": True, "request_id": request_id, "sku": sku, "status": "received"}
