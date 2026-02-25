from __future__ import annotations

from typing import Dict, Any, List
from supabase import Client
from ..db import supabase
from ..cache import ttl_cache
from .forecasting import rolling_average
from .sage_adapter.service import get_sage_kpi_batch_id


MAX_ANALYTICS_ROWS = 3000


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",))
def kpis(client: Client = supabase) -> Dict[str, Any]:
    """Operations KPIs: avg order fulfillment days, total downtime minutes, stock turnover (simple).

    - fulfillment_days_avg: mean(fulfilled_at - created_at) over fulfilled orders
    - downtime_minutes_total: sum(minutes)
    - stock_turnover: sum(quantity_sold) / avg_inventory_qty (approx via latest inventory)
    """
    import datetime

    # Fulfillment time
    o = client.table("ops_orders_snapshot").select("created_at,fulfilled_at,quantity").order("created_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    orders = o.data or []
    def parse_dt(s: str | None):
        if not s:
            return None
        try:
            return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    deltas: List[float] = []
    qty_total = 0.0
    for r in orders:
        c = parse_dt(r.get("created_at"))
        f = parse_dt(r.get("fulfilled_at"))
        if c and f and f >= c:
            deltas.append((f - c).total_seconds() / 86400.0)
        qty_total += float(r.get("quantity") or 0)
    fulfillment_days_avg = (sum(deltas) / len(deltas)) if deltas else 0.0

    # Downtime minutes
    d = client.table("ops_downtime_snapshot").select("minutes").order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    downtime_minutes_total = sum(float(r.get("minutes") or 0) for r in (d.data or []))

    # Approximate avg inventory qty from latest inventory snapshot
    sage_batch_id = get_sage_kpi_batch_id()
    inv_q = client.table("sage_inventory_snapshot").select("quantity")
    if sage_batch_id:
        inv_q = inv_q.eq("batch_id", sage_batch_id)
    inv = inv_q.order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    inv_q = [float(r.get("quantity") or 0) for r in (inv.data or [])]
    avg_inventory_qty = (sum(inv_q) / len(inv_q)) if inv_q else 0.0
    stock_turnover = (qty_total / avg_inventory_qty) if avg_inventory_qty > 0 else 0.0

    explain = {
        "fulfillment_days_avg": "mean(fulfilled_at - created_at) in days",
        "downtime_minutes_total": "sum(minutes)",
        "stock_turnover": "sum(quantity_sold) / avg_inventory_qty",
        "sources": ["ops_orders_snapshot", "ops_downtime_snapshot", "sage_inventory_snapshot"],
    }
    return {
        "fulfillment_days_avg": fulfillment_days_avg,
        "downtime_minutes_total": downtime_minutes_total,
        "stock_turnover": stock_turnover,
        "explain": explain,
    }


def stock_turnover_series(client: Client = supabase, periods: int = 6) -> Dict[str, Any]:
    """Monthly stock turnover based on ops orders and avg inventory quantities."""
    # Orders by month
    o = client.table("ops_orders_snapshot").select("created_at,quantity").order("created_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    orders = o.data or []
    buckets: Dict[str, float] = {}
    for r in orders:
        dt = (r.get("created_at") or "")[:7]
        if not dt:
            continue
        buckets[dt] = buckets.get(dt, 0.0) + float(r.get("quantity") or 0)
    months = sorted(buckets.keys())[-periods:]
    # Approximate avg inventory per month from latest snapshot (constant baseline)
    sage_batch_id = get_sage_kpi_batch_id()
    inv_q = client.table("sage_inventory_snapshot").select("quantity")
    if sage_batch_id:
        inv_q = inv_q.eq("batch_id", sage_batch_id)
    inv = inv_q.order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    inv_q = [float(r.get("quantity") or 0) for r in (inv.data or [])]
    avg_inventory_qty = (sum(inv_q) / len(inv_q)) if inv_q else 1.0
    series = [{"period": m, "turnover": (buckets[m] / avg_inventory_qty) if avg_inventory_qty > 0 else 0.0} for m in months]
    return {"series": series}


def forecast_stock_turnover(client: Client = supabase, window: int = 3, horizon: int = 3) -> Dict[str, Any]:
    s = stock_turnover_series(client=client, periods=12)["series"]
    vals = [p["turnover"] for p in s]
    if not vals:
        return {"series": [], "rolling": [], "forecast": []}
    roll = rolling_average(vals, window=window)
    last = roll[-1]
    forecast = [last for _ in range(horizon)]
    return {"series": s, "rolling": roll, "forecast": forecast}
