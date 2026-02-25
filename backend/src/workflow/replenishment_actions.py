from __future__ import annotations
from typing import Dict, Any
from src.db import supabase


def create_replenishment_request(sku: str, product_id: str | None, requested_qty: float, created_by: str | None = None) -> Dict[str, Any]:
    payload = {"sku": sku, "product_id": product_id, "requested_qty": requested_qty, "created_by": created_by}
    supabase.table("replenishment_requests").insert(payload).execute()
    return {"ok": True}


def approve_replenishment(request_id: str, approver: str | None = None) -> Dict[str, Any]:
    supabase.table("replenishment_requests").update({"status": "approved", "approved_by": approver}).eq("id", request_id).execute()
    return {"ok": True}


def create_po_for_request(request_id: str, po_id: str, created_by: str | None = None) -> Dict[str, Any]:
    supabase.table("replenishment_requests").update({"po_id": po_id, "status": "ordered"}).eq("id", request_id).execute()
    return {"ok": True}
