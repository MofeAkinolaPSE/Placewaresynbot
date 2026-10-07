from __future__ import annotations

from typing import Dict, Any, List
from typing import Any as DBClient
from ..db import db
from ..cache import ttl_cache
from .forecasting import rolling_average
from .sage_adapter.service import get_sage_kpi_batch_id
import datetime as _datetime_mod


def _dt_to_str(val: object) -> str:
    """Coerce psycopg2 datetime/date to ISO string; passthrough for str/None."""
    if val is None:
        return ""
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


MAX_ANALYTICS_ROWS = 3000


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",), tags=("logistics", "ops_kpis", "executive"))
def kpis(client: DBClient = db) -> Dict[str, Any]:
    """Operations KPIs: avg order fulfillment days, stock turnover.

    - fulfillment_days_avg: mean(expected_delivery_date - order_date) for closed POs
    - downtime_minutes_total: null (no data source available from Sage CSV package)
    - stock_turnover: total_sold_qty / avg_inventory_qty (approx via inventory snapshot)
    """
    import datetime

    def parse_date(s: str | None) -> datetime.date | None:
        if not s:
            return None
        try:
            return datetime.date.fromisoformat(str(s)[:10])
        except Exception:
            return None

    from src.fin.readmodel import live
    if live():
        # Real operational timings (Frontdesk order -> dispatch) and ACE Books stock economics,
        # instead of the Sage "PO" dates (order_date + 30 by construction) and the doubled stock view.
        ov = logistics_overview()
        return {
            "fulfillment_days_avg": round(ov["orders"]["avg_hours_to_dispatch"] / 24, 2) if ov["orders"]["avg_hours_to_dispatch"] is not None else None,
            "downtime_minutes_total": None,
            "stock_turnover": ov["stock"]["turnover"],
            "explain": {
                "fulfillment_days_avg": "Frontdesk invoice created -> dispatched",
                "downtime_minutes_total": "not recorded",
                "stock_turnover": "cost of sales, last 12 months / stock value at cost (ACE Books)",
                "sources": ["frontdesk_invoices", "v_sales_lines", "fin_cost_layers"],
            },
        }

    # Fulfillment time — derived from purchase orders (order_date → expected_delivery_date)
    po_batch: str | None = None
    try:
        _b = client.table("sage_purchase_orders_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
        po_batch = (_b.data or [{}])[0].get("batch_id")
    except Exception:
        pass

    po_q = client.table("sage_purchase_orders_snapshot").select("order_date,expected_delivery_date,status")
    if po_batch:
        po_q = po_q.eq("batch_id", po_batch)
    po_data = (po_q.order("order_date", desc=True).limit(MAX_ANALYTICS_ROWS).execute().data or [])

    deltas: List[float] = []
    for r in po_data:
        # Only count closed/received POs where delivery actually occurred
        status = str(r.get("status") or "").lower()
        if status not in ("closed", "received", "complete", "completed"):
            continue
        od = parse_date(r.get("order_date"))
        ed = parse_date(r.get("expected_delivery_date"))
        if od and ed and ed >= od:
            deltas.append((ed - od).days)
    fulfillment_days_avg = round(sum(deltas) / len(deltas), 2) if deltas else 0.0

    # Approximate avg inventory qty from latest inventory snapshot
    sage_batch_id = get_sage_kpi_batch_id()
    if not sage_batch_id:
        try:
            _ib = client.table("sage_inventory_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
            sage_batch_id = (_ib.data or [{}])[0].get("batch_id")
        except Exception:
            pass
    inv_q = client.table("sage_inventory_snapshot").select("quantity")
    if sage_batch_id:
        inv_q = inv_q.eq("batch_id", sage_batch_id)
    inv = inv_q.order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    inv_vals = [float(r.get("quantity") or 0) for r in (inv.data or [])]
    avg_inventory_qty = (sum(inv_vals) / len(inv_vals)) if inv_vals else 0.0

    # Stock turnover: total_sold_qty ÷ avg_inventory_qty
    # Approximated using invoice line quantities as proxy for sold qty
    sold_qty = 0.0
    try:
        il_batch: str | None = None
        _ilb = client.table("sage_invoice_lines_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
        il_batch = (_ilb.data or [{}])[0].get("batch_id")
        il_q = client.table("sage_invoice_lines_snapshot").select("quantity")
        if il_batch:
            il_q = il_q.eq("batch_id", il_batch)
        il_rows = il_q.limit(MAX_ANALYTICS_ROWS).execute().data or []
        sold_qty = sum(float(r.get("quantity") or 0) for r in il_rows)
    except Exception:
        pass
    stock_turnover = round(sold_qty / avg_inventory_qty, 4) if avg_inventory_qty > 0 else 0.0

    return {
        "fulfillment_days_avg": fulfillment_days_avg,
        "downtime_minutes_total": None,  # No Sage CSV source for downtime
        "stock_turnover": stock_turnover,
        "explain": {
            "fulfillment_days_avg": "mean(expected_delivery_date - order_date) for closed POs",
            "downtime_minutes_total": "unavailable — no downtime data source in Sage CSV package",
            "stock_turnover": "sum(invoice_line_quantity) / avg_inventory_qty",
            "sources": ["sage_purchase_orders_snapshot", "sage_invoice_lines_snapshot", "sage_inventory_snapshot"],
        },
    }


def stock_turnover_series(client: DBClient = db, periods: int = 6) -> Dict[str, Any]:
    """Monthly stock turnover based on invoice lines and avg inventory quantities."""
    from src.fin.readmodel import live
    if live():
        # annualised monthly cost of sales / stock value at cost (ACE Books)
        ov = logistics_overview(months=periods)
        value = ov["stock"]["value"] or 0.0
        return {"series": [{"period": m["period"], "turnover": round(m["cost"] * 12 / value, 2) if value else 0.0}
                           for m in ov["monthly"]]}
    # Sold quantity by month from invoice lines
    il_batch: str | None = None
    try:
        _b = client.table("sage_invoice_lines_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
        il_batch = (_b.data or [{}])[0].get("batch_id")
    except Exception:
        pass
    il_q = client.table("sage_invoice_lines_snapshot").select("imported_at,invoice_id,quantity")
    if il_batch:
        il_q = il_q.eq("batch_id", il_batch)
    orders = (il_q.order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute().data or [])

    # Build invoice_id → YYYY-MM map from AR snapshot (carries actual invoice business date)
    inv_date_map: Dict[str, str] = {}
    try:
        ar_batch: str | None = None
        _ab = client.table("sage_ar_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
        ar_batch = (_ab.data or [{}])[0].get("batch_id")
        ar_q = client.table("sage_ar_snapshot").select("invoice_id,date")
        if ar_batch:
            ar_q = ar_q.eq("batch_id", ar_batch)
        for ar_row in (ar_q.limit(MAX_ANALYTICS_ROWS).execute().data or []):
            iid = ar_row.get("invoice_id")
            if iid:
                inv_date_map[iid] = _dt_to_str(ar_row.get("date"))[:7]
    except Exception:
        pass

    buckets: Dict[str, float] = {}
    for r in orders:
        invoice_id = r.get("invoice_id") or ""
        month = inv_date_map.get(invoice_id) or _dt_to_str(r.get("imported_at"))[:7]
        if not month:
            continue
        buckets[month] = buckets.get(month, 0.0) + float(r.get("quantity") or 0)
    months = sorted(buckets.keys())[-periods:]
    # Approximate avg inventory per month from latest snapshot (constant baseline)
    sage_batch_id = get_sage_kpi_batch_id()
    if not sage_batch_id:
        try:
            _ib = client.table("sage_inventory_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
            sage_batch_id = (_ib.data or [{}])[0].get("batch_id")
        except Exception:
            pass
    inv_q = client.table("sage_inventory_snapshot").select("quantity")
    if sage_batch_id:
        inv_q = inv_q.eq("batch_id", sage_batch_id)
    inv = inv_q.order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    inv_vals = [float(r.get("quantity") or 0) for r in (inv.data or [])]
    avg_inventory_qty = (sum(inv_vals) / len(inv_vals)) if inv_vals else 1.0
    series = [{"period": m, "turnover": round(buckets[m] / avg_inventory_qty, 4) if avg_inventory_qty > 0 else 0.0} for m in months]
    return {"series": series}


def forecast_stock_turnover(client: DBClient = db, window: int = 3, horizon: int = 3) -> Dict[str, Any]:
    s = stock_turnover_series(client=client, periods=12)["series"]
    vals = [p["turnover"] for p in s]
    if not vals:
        return {"series": [], "rolling": [], "forecast": []}
    roll = rolling_average(vals, window=window)
    last = roll[-1]
    forecast = [last for _ in range(horizon)]
    return {"series": s, "rolling": roll, "forecast": forecast}


def logistics_overview(months: int = 12) -> Dict[str, Any]:
    """Operations overview from real records: Frontdesk orders -> dispatch, deliveries,
    and stock economics from ACE Books (dated sales and FIFO stock at cost)."""
    from src.fin.db import q, q1, tx
    from src.services import books_analytics

    with tx() as conn:
        orders = q1(conn, """SELECT COUNT(*) AS total,
                                    COUNT(*) FILTER (WHERE dispatched_at IS NOT NULL) AS dispatched,
                                    COUNT(*) FILTER (WHERE dispatched_at IS NULL AND status IN ('finance_approved','qc_passed','pending_finance','pending_qc','created'))
                                        AS awaiting_dispatch,
                                    AVG(EXTRACT(EPOCH FROM dispatched_at - created_at) / 3600) FILTER (WHERE dispatched_at IS NOT NULL) AS avg_hours_to_dispatch,
                                    AVG(EXTRACT(EPOCH FROM finance_decided_at - created_at) / 3600) FILTER (WHERE finance_decided_at IS NOT NULL) AS avg_hours_to_approval
                             FROM frontdesk_invoices""")
        deliveries = q1(conn, """SELECT COUNT(*) AS total,
                                        COUNT(*) FILTER (WHERE status='delivered') AS delivered,
                                        COUNT(*) FILTER (WHERE status IN ('in_transit','picked_up')) AS in_transit,
                                        COUNT(*) FILTER (WHERE status='assigned') AS assigned,
                                        COUNT(*) FILTER (WHERE status='unassigned') AS unassigned,
                                        AVG(EXTRACT(EPOCH FROM delivered_at - created_at) / 3600) FILTER (WHERE delivered_at IS NOT NULL) AS avg_hours_to_deliver
                                 FROM deliveries""")
        as_of = q1(conn, "SELECT MAX(invoice_date) AS d FROM v_sales_lines")["d"] or _datetime_mod.date.today()
        monthly = q(conn, """SELECT to_char(invoice_date, 'YYYY-MM') AS period, SUM(quantity) FILTER (WHERE sku IS NOT NULL) AS units,
                                    SUM(amount) AS sales, SUM(cost) AS cost
                             FROM v_sales_lines WHERE invoice_date >= (date_trunc('month', %s::date) - interval '1 month' * (%s - 1))::date AND invoice_date <= %s
                             GROUP BY 1 ORDER BY 1""", (as_of, months, as_of))
        cogs12 = float(q1(conn, "SELECT COALESCE(SUM(cost),0) AS c FROM v_sales_lines WHERE invoice_date > %s::date - 365 AND invoice_date <= %s",
                          (as_of, as_of))["c"] or 0)
        expiring = q1(conn, """SELECT COUNT(*) AS items, COALESCE(SUM(current_stock * cost_price), 0) AS value FROM v_inventory
                               WHERE current_stock > 0 AND expiry_date IS NOT NULL AND expiry_date <= current_date + 90""")
    stock = books_analytics.stock_totals()
    value = stock["value"]
    turnover = round(cogs12 / value, 2) if value else None

    def _num(v):
        return round(float(v), 1) if v is not None else None

    return {
        "as_of": as_of,
        "orders": {k: (_num(v) if k.startswith("avg") else int(v or 0)) for k, v in orders.items()},
        "deliveries": {k: (_num(v) if k.startswith("avg") else int(v or 0)) for k, v in deliveries.items()},
        "stock": {"value": round(value, 2), "units": stock["units"], "items_in_stock": stock["skus_in_stock"],
                  "cogs_12m": round(cogs12, 2), "turnover": turnover,
                  "days_of_stock": round(365 / turnover) if turnover else None,
                  "expiring_90d_items": int(expiring["items"] or 0), "expiring_90d_value": round(float(expiring["value"] or 0), 2)},
        "monthly": [{"period": m["period"], "units": float(m["units"] or 0), "sales": float(m["sales"] or 0),
                     "cost": float(m["cost"] or 0)} for m in monthly],
    }
