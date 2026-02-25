from __future__ import annotations
from typing import Dict, Any
from src.db import supabase
from src.constants import TABLE_KPI_PROMOTIONS


def create_promotion(sku: str, batch_id: str | None, qty: float, discount_pct: float, created_by: str | None = None) -> Dict[str, Any]:
    payload = {
        "sku": sku,
        "batch_id": batch_id,
        "qty": qty,
        "discount_pct": float(discount_pct),
        "created_by": created_by,
    }
    supabase.table("promotions").insert(payload).execute()
    # record a promoted KPI entry
    supabase.table(TABLE_KPI_PROMOTIONS).insert({"sku": sku, "batch_id": batch_id, "qty": qty, "discount_pct": discount_pct, "created_by": created_by}).execute()
    return {"ok": True}


def list_promotions(limit: int = 50):
    resp = supabase.table("promotions").select("*").order("created_at", desc=True).limit(limit).execute()
    return resp.data or []
