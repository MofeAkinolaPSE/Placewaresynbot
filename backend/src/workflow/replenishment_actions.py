from __future__ import annotations
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from src.db import db

logger = logging.getLogger(__name__)


def create_replenishment_request(sku: str, product_id: str | None, requested_qty: float, created_by: str | None = None) -> Dict[str, Any]:
    payload = {"sku": sku, "product_id": product_id, "requested_qty": requested_qty, "created_by": created_by}
    resp = db.table("replenishment_requests").insert(payload).execute()
    row = (resp.data or [{}])[0] if hasattr(resp, "data") else {}
    # Return the created row so callers can reference the new request --
    # returning a bare {"ok": true} left the UI unable to act on what it had
    # just raised.
    return {"ok": True, "id": row.get("id"), "sku": sku,
            "requested_qty": requested_qty, "status": row.get("status", "recommended")}


def approve_replenishment(request_id: str, approver: str | None = None) -> Dict[str, Any]:
    db.table("replenishment_requests").update({"status": "approved", "approved_by": approver}).eq("id", request_id).execute()
    return {"ok": True}


def cancel_replenishment(request_id: str, actor: str | None = None, reason: str | None = None) -> Dict[str, Any]:
    """Cancel a request that hasn't been received yet.

    Cancelling is a status update, not a delete -- the row stays for audit
    (who raised it, when, why it was dropped) instead of disappearing. A
    request already marked 'received' has already added stock; cancelling it
    afterwards would be misleading (the delivery happened) so that's refused.
    """
    req_resp = (
        db.table("replenishment_requests")
        .select("id,sku,status")
        .eq("id", request_id).limit(1).execute()
    )
    req_rows = req_resp.data if hasattr(req_resp, "data") else []
    if not req_rows:
        return {"ok": False, "error": "request_not_found"}

    req = req_rows[0]
    if (req.get("status") or "").lower() == "received":
        return {"ok": False, "error": "already_received",
                "detail": "This request was already received; cancelling it now would not be accurate."}
    if (req.get("status") or "").lower() == "cancelled":
        return {"ok": True, "request_id": request_id, "sku": req.get("sku"),
                "status": "cancelled", "already_cancelled": True}

    note = "Cancelled"
    if reason:
        note += f": {reason}"
    if actor:
        note += f" (by {actor})"

    db.table("replenishment_requests").update(
        {"status": "cancelled", "notes": note}
    ).eq("id", request_id).execute()

    return {"ok": True, "request_id": request_id, "sku": req.get("sku"), "status": "cancelled"}


def create_po_for_request(request_id: str, po_id: str, created_by: str | None = None) -> Dict[str, Any]:
    db.table("replenishment_requests").update({"po_id": po_id, "status": "ordered"}).eq("id", request_id).execute()
    return {"ok": True}


def mark_replenishment_received(
    request_id: str,
    received_qty: float | None = None,
    actor: str | None = None,
) -> Dict[str, Any]:
    # requested_qty is needed as the fallback when a caller receipts a request
    # without stating a quantity -- omitting it here silently restocked zero.
    req_resp = (
        db.table("replenishment_requests")
        .select("id,sku,status,requested_qty")
        .eq("id", request_id).limit(1).execute()
    )
    req_rows = req_resp.data if hasattr(req_resp, "data") else []
    if not req_rows:
        return {"ok": False, "error": "request_not_found"}

    req = req_rows[0]
    sku = req.get("sku")

    # Receiving a request that was already received must not add the stock
    # twice. The status check is the guard; without it a double-click or a
    # retried request would inflate inventory.
    if (req.get("status") or "").lower() == "received":
        return {"ok": True, "request_id": request_id, "sku": sku,
                "status": "received", "already_received": True, "stock_added": 0}

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

    # Put the delivered units into stock. Marking a request received used to
    # change nothing but a status column, so a completed reorder left
    # inventory exactly where it was -- the mirror image of the dispatch path
    # that never decremented it.
    stock_added = 0.0
    qty = received_qty if received_qty is not None else req.get("requested_qty")
    try:
        qty = float(qty or 0)
    except (TypeError, ValueError):
        qty = 0.0

    if sku and qty > 0:
        try:
            from src.services.inventory import record_inventory_event

            record_inventory_event(
                sku=sku,
                change=abs(qty),
                event_type="RESTOCK",
                reference=f"Replenishment {request_id}",
                user_id=actor or "system",
            )
            stock_added = abs(qty)
        except Exception as exc:
            # The delivery physically arrived and the request is receipted;
            # surface the stock failure rather than rolling that back.
            logger.error("Replenishment %s: stock not added for %s: %s", request_id, sku, exc)

    # Best-effort: clear related low-stock alerts from alert feed.
    if sku:
        try:
            db.table("placeware_alerts").update({"status": "archived"}).eq("category", "inventory").ilike("title", f"%{sku}%").execute()
        except Exception:
            pass

    return {
        "ok": True, "request_id": request_id, "sku": sku,
        "status": "received", "stock_added": stock_added,
    }
