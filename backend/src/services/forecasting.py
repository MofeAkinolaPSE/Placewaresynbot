from __future__ import annotations

from typing import List, Dict, Any
from supabase import Client
from ..db import supabase
from .sage_adapter.service import get_sage_kpi_batch_id


def rolling_average(values: List[float], window: int = 3) -> List[float]:
    if window <= 0:
        return []
    out: List[float] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_vals = values[start : i + 1]
        out.append(sum(window_vals) / len(window_vals))
    return out


def ar_balance_series(client: Client = supabase, max_points: int = 12) -> List[Dict[str, Any]]:
    batch_id = get_sage_kpi_batch_id()
    q = client.table("sage_ar_snapshot").select("date,balance")
    if batch_id:
        q = q.eq("batch_id", batch_id)
    resp = q.order("date", desc=True).limit(10000).execute()
    data = resp.data or []
    buckets: Dict[str, float] = {}
    for r in data:
        d = r.get("date")
        if not d:
            continue
        buckets[d] = buckets.get(d, 0.0) + float(r.get("balance") or 0)
    # sort ascending for time series
    points = sorted(({"date": k, "balance": v} for k, v in buckets.items()), key=lambda x: x["date"])[:max_points]
    return points


def forecast_ar_balance(client: Client = supabase, window: int = 3, horizon: int = 3) -> Dict[str, Any]:
    series = ar_balance_series(client=client, max_points=12)
    balances = [p["balance"] for p in series]
    if not balances:
        return {"series": [], "rolling": [], "forecast": []}
    roll = rolling_average(balances, window=window)
    # naive forecast: extend last rolling average for horizon steps
    last = roll[-1]
    forecast = [last for _ in range(horizon)]
    return {"series": series, "rolling": roll, "forecast": forecast}
