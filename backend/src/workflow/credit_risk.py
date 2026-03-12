from __future__ import annotations
from typing import Dict, Any
from src.db import db


def apply_credit_action(customer_id: str, action: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = {"customer_id": customer_id, "action": action, "details": details or {}}
    db.table("credit_risk_actions").insert(payload).execute()
    return {"ok": True}


def list_credit_actions(customer_id: str):
    resp = db.table("credit_risk_actions").select("*").eq("customer_id", customer_id).order("executed_at", desc=True).execute()
    return resp.data or []


def is_customer_flagged(customer_id: str) -> bool:
    """Simple heuristic: if there's any recent action of type 'limit_reduce' or 'flagged', consider flagged."""
    resp = db.table("credit_risk_actions").select("action, executed_at").eq("customer_id", customer_id).order("executed_at", desc=True).limit(10).execute()
    rows = resp.data or []
    for r in rows:
        a = str(r.get("action") or "").lower()
        if a in ("limit_reduce", "flagged", "hold"):
            return True
    return False
