from typing import Optional
from .db import supabase
import datetime

def get_lead_order_conversion(days: int = 30) -> dict:
    """Return simple lead->order conversion metrics over the past `days` days."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).replace(microsecond=0).isoformat() + "Z"
    # Count leads
    leads_resp = supabase.table("placeware_leads").select("id,created_at").gte("created_at", cutoff).execute()
    leads = leads_resp.data or []
    leads_count = len(leads)
    # Count orders linked to leads in same period
    orders_resp = supabase.table("placeware_orders").select("id,lead_id,created_at").gte("created_at", cutoff).execute()
    orders = orders_resp.data or []
    orders_with_leads = [o for o in orders if o.get("lead_id")]
    order_count = len(orders)
    linked_order_count = len(orders_with_leads)
    conversion_rate = (linked_order_count / leads_count * 100.0) if leads_count else 0.0
    return {
        "days": days,
        "leads": leads_count,
        "orders": order_count,
        "orders_linked_to_leads": linked_order_count,
        "conversion_rate_percent": round(conversion_rate, 2),
    }
