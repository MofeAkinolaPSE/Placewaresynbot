from __future__ import annotations
import logging
from typing import Dict, Any, List, Literal, Optional
from datetime import datetime, timedelta
from typing import Any as DBClient
from ..db import db
from ..cache import invalidate_cache_tags
from ..constants import TABLE_INVENTORY_EVENTS
from .sage_adapter.service import get_sage_kpi_batch_id, _latest_batch_for_table

# Use the literal table name used in the adapter for consistency until migrated
TABLE_SAGE_SNAPSHOT = "sage_inventory_snapshot"

logger = logging.getLogger("inventory")

class StockInBooksError(ValueError):
    """A stock change for an item ACE Books values must be posted in ACE Books."""


def _held_in_books(sku: str) -> bool:
    try:
        from src.fin.readmodel import live
        if not live():
            return False
        from src.fin.db import q1, tx
        with tx() as conn:
            return bool(q1(conn, "SELECT 1 FROM fin_products WHERE sku=%s LIMIT 1", (sku,)))
    except Exception:
        return False


def record_inventory_event(
    sku: str,
    change: float,
    event_type: str,
    reference: str | None,
    user_id: str,
    client: DBClient = db
) -> Dict[str, Any]:
    """
    Record an append-only inventory movement event.
    Does NOT mutate the Sage snapshot baseline.
    """
    if change == 0:
        raise ValueError("Quantity change cannot be zero")
    # Once ACE Books is live, stock for items the books hold is valued there and
    # v_inventory reads it from there: a direct stock write here would be ignored.
    # Frontdesk's dispatch SALE stays as an operational record (the books already
    # took the stock at Finance approval).
    if event_type != "SALE" and _held_in_books(sku):
        raise StockInBooksError(
            f"Stock for {sku} is recorded in ACE Books: receive it with a supplier bill (Inventory > Receive stock) "
            f"or a stock adjustment (Inventory > Log adjustment)."
        )

    payload = {
        "sku": sku,
        "quantity_change": change,
        "event_type": event_type,
        "reference": reference,
        "performed_by": user_id,
        # created_at is handled by DB default
    }

    try:
        resp = client.table(TABLE_INVENTORY_EVENTS).insert(payload).execute()
        msg = f"Recorded {event_type} for {sku}: {change} (Ref: {reference})"
        logger.info(msg)
        # v_inventory folds in events as soon as they're recorded (migration 106),
        # but the 60s ttl_cache on get_inventory_dashboard() would otherwise still
        # serve a stale KPI count until it naturally expires.
        invalidate_cache_tags("inventory", "inventory_dashboard", "executive")
        return resp.data[0] if resp.data else {}
    except Exception as e:
        logger.error(f"Failed to record inventory event: {e}")
        raise e


def classify_stock_status(
    qty: float, reorder_level: float | None
) -> Literal["out_of_stock", "critical", "warning", "adequate"]:
    """
    One canonical stock-status classification, used everywhere a threshold
    decision is made (dashboard KPIs, workspace cards, alerts) instead of the
    three previously-independent, disagreeing threshold implementations.
    """
    if qty <= 0:
        return "out_of_stock"
    threshold = reorder_level if reorder_level and reorder_level > 0 else 10
    if qty <= threshold:
        return "critical"
    if qty <= threshold * 1.5:
        return "warning"
    return "adequate"


def _row_to_summary_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Reshape a v_inventory row into the nested baseline/events/current_stock
    shape get_realtime_stock()/get_inventory_summary() have always returned,
    so existing consumers (intelligence.py, inventory.py router) don't need
    to change. No current caller reads baseline/events sub-fields (confirmed
    via repo-wide search) — kept only for response-shape stability; the view
    doesn't expose baseline-vs-delta separately, only the combined total.
    """
    current_stock = float(row.get("current_stock") or 0)
    return {
        "sku": row.get("sku"),
        "name": row.get("name") or row.get("sku"),
        "baseline": {
            "quantity": current_stock,
            "source": "v_inventory",
            "as_of": None,
        },
        "events": {
            "count": int(row.get("events_since_baseline") or 0),
            "net_change": None,
        },
        "current_stock": current_stock,
        "status": "In Stock" if current_stock > 0 else "Out of Stock",
        "stock_status": classify_stock_status(current_stock, row.get("reorder_level")),
        "category": row.get("category") or "",
        "unit": row.get("unit") or "",
        "cost_price": float(row.get("cost_price") or 0),
        "selling_price": float(row.get("selling_price") or 0),
        "reorder_level": float(row.get("reorder_level") or 0),
        "expiry_date": row.get("expiry_date"),
        "batch_number": row.get("batch_number") or "",
        "company_id": row.get("company_id"),
    }


def get_realtime_stock(sku: str, client: DBClient = db) -> Dict[str, Any]:
    """
    Authoritative current stock for one SKU: reads v_inventory directly, which
    already folds Sage-snapshot baseline + placeware_inventory_events deltas
    (migration 106) — the same computation this function used to do itself in
    Python, now a single canonical SQL view every consumer shares.
    """
    resp = client.table("v_inventory").select("*").eq("sku", sku).limit(1).execute()
    rows = resp.data or []
    if not rows:
        return {
            "sku": sku,
            "name": "Unknown Product",
            "baseline": {"quantity": 0.0, "source": "v_inventory", "as_of": None},
            "events": {"count": 0, "net_change": 0.0},
            "current_stock": 0.0,
            "status": "Out of Stock",
            "stock_status": "out_of_stock",
        }
    return _row_to_summary_dict(rows[0])


def get_inventory_summary(limit: int = 50, client: DBClient = db) -> List[Dict[str, Any]]:
    """
    Bulk inventory summary, reading v_inventory directly (migration 106) —
    replaces the previous bespoke dedup + bulk-events-merge + metadata-enrich
    pipeline, which duplicated exactly what the view now does once in SQL.
    """
    try:
        resp = (
            client.table("v_inventory")
            .select("*")
            .order("current_stock", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
    except Exception as e:
        logger.error(f"v_inventory bulk query failed: {e}")
        rows = []

    if rows:
        return [_row_to_summary_dict(r) for r in rows]

    # ── Fallback: inventory_items + stock_levels (only if v_inventory is
    # somehow empty, e.g. no Sage catalog imported yet) ──────────────────────
    logger.info("v_inventory empty; falling back to inventory_items + stock_levels")
    results: List[Dict[str, Any]] = []
    try:
        items_resp = client.table("inventory_items").select("id, sku, name").limit(limit).execute()
        for item in (items_resp.data or []):
            item_id = item.get("id")
            sku = item.get("sku") or str(item_id)
            name = item.get("name") or "Unknown"
            stock_resp = client.table("stock_levels").select("quantity").eq("item_id", item_id).execute()
            total_qty = sum(float(s.get("quantity") or 0) for s in (stock_resp.data or []))
            results.append({
                "sku": sku,
                "name": name,
                "baseline": {"quantity": total_qty, "source": "Inventory Module", "as_of": None},
                "events": {"count": 0, "net_change": 0.0},
                "current_stock": total_qty,
                "status": "In Stock" if total_qty > 0 else "Out of Stock",
                "stock_status": classify_stock_status(total_qty, None),
            })
    except Exception as e:
        logger.error(f"Inventory module fallback failed: {e}")
    return results


def get_recent_inventory_movements(limit: int = 20, client: DBClient = db) -> List[Dict[str, Any]]:
    """Fetch recent inventory movement events for dashboards."""
    try:
        resp = (
            client.table(TABLE_INVENTORY_EVENTS)
            .select("sku,quantity_change,event_type,reference,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "sku": r.get("sku"),
                    "change": float(r.get("quantity_change") or 0),
                    "event_type": r.get("event_type") or "movement",
                    "reference": r.get("reference"),
                    "created_at": r.get("created_at"),
                }
            )
        return out
    except Exception as e:
        logger.error(f"get_recent_inventory_movements failed: {e}")
        return []

def get_latest_batch_sku_count(client: DBClient = db) -> int:
    """
    Get the count of SKUs in the most recent import batch.
    """
    # 1. Get latest imported_at/batch_id
    batch_id = get_sage_kpi_batch_id()
    if not batch_id:
        latest = client.table(TABLE_SAGE_SNAPSHOT)\
            .select("batch_id")\
            .order("imported_at", desc=True)\
            .limit(1)\
            .execute()
        if not latest.data:
            return 0
        batch_id = latest.data[0]['batch_id']

    if not batch_id:
        return 0
    
    # 2. Count rows in that batch
    count_resp = client.table(TABLE_SAGE_SNAPSHOT)\
        .select("*", count="exact")\
        .eq("batch_id", batch_id)\
        .limit(1)\
        .execute()
        
    return count_resp.count or 0


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    import datetime as _dt
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d")
        except Exception:
            return None


def get_expiring_inventory(thresholds: List[int] | None = None, client: DBClient = db) -> Dict[str, Any]:
    """Compute expiring inventory tiers from the latest batch snapshot.

    thresholds: list of days [90, 60, 30] mapping to tiers medium/high/critical.
    Returns { items: [ {sku,name,quantity,expiry_date,days_to_expiry,tier} ], summary: {...} }.
    """
    thresholds = thresholds or [90, 60, 30]
    thresholds = sorted(set(int(x) for x in thresholds if int(x) > 0), reverse=True)

    # 1) Determine latest batch
    batch_id = get_sage_kpi_batch_id()
    if not batch_id:
        latest = client.table(TABLE_SAGE_SNAPSHOT)\
            .select("batch_id, imported_at")\
            .order("imported_at", desc=True)\
            .limit(1)\
            .execute()
        if not latest.data:
            return {"items": [], "summary": {"batch_id": None, "count": 0}}
        batch_id = latest.data[0]["batch_id"]

    if not batch_id:
        return {"items": [], "summary": {"batch_id": None, "count": 0}}

    # 2) Fetch rows in that batch
    try:
        resp = client.table(TABLE_SAGE_SNAPSHOT)\
            .select("sku,name,quantity,expiry_date,imported_at,batch_id")\
            .eq("batch_id", batch_id)\
            .limit(2000)\
            .execute()
    except Exception as e:
        logger.error(f"Expiring inventory query failed: {e}")
        return {"items": [], "summary": {"batch_id": batch_id, "count": 0, "note": "expiry_date column missing"}}
    rows = resp.data or []

    # 2b) If sage_inventory_snapshot lacks expiry data, pull from sage_items_snapshot
    # (expiry_date was added to sage_items_snapshot in Tier 2, not to sage_inventory_snapshot)
    rows_have_expiry = any(r.get("expiry_date") for r in rows)
    if not rows_have_expiry:
        try:
            items_resp = client.table("sage_items_snapshot")\
                .select("item_id, item_name, expiry_date, batch_number")\
                .order("imported_at", desc=True)\
                .limit(2000)\
                .execute()
            # Deduplicate by item_id
            seen_ids: set = set()
            fallback_rows = []
            for r in (items_resp.data or []):
                if not r.get("expiry_date"):
                    continue
                key = r.get("item_id") or ""
                if key and key not in seen_ids:
                    seen_ids.add(key)
                    fallback_rows.append({
                        "sku":         r.get("item_id") or "",
                        "name":        r.get("item_name") or "",
                        "quantity":    0,
                        "expiry_date": r.get("expiry_date"),
                        "batch_id":    batch_id,
                    })
            if fallback_rows:
                logger.info(f"Expiry fallback: using {len(fallback_rows)} rows from sage_items_snapshot")
                rows = fallback_rows
        except Exception as e:
            logger.warning(f"sage_items_snapshot expiry fallback failed (non-fatal): {e}")
    now = datetime.utcnow()
    items: List[Dict[str, Any]] = []

    for r in rows:
        exp = _parse_date(r.get("expiry_date"))
        if not exp:
            continue
        days = (exp.date() - now.date()).days
        if days < 0:
            tier = "expired"
        elif days <= min(thresholds):
            # map by thresholds
            if days <= 30:
                tier = "critical"
            elif days <= 60:
                tier = "high"
            else:
                tier = "medium"
        else:
            # Above the largest threshold → not flagged
            continue
        items.append({
            "sku": r.get("sku"),
            "name": r.get("name"),
            "quantity": float(r.get("quantity") or 0),
            "expiry_date": r.get("expiry_date"),
            "days_to_expiry": days,
            "tier": tier,
        })

    summary = {
        "batch_id": batch_id,
        "count": len(items),
        "by_tier": {
            "critical": sum(1 for i in items if i["tier"] == "critical"),
            "high": sum(1 for i in items if i["tier"] == "high"),
            "medium": sum(1 for i in items if i["tier"] == "medium"),
            "expired": sum(1 for i in items if i["tier"] == "expired"),
        }
    }
    return {"items": items, "summary": summary}


def scan_and_alert_expiring(thresholds: List[int] | None = None, client: DBClient = db) -> Dict[str, Any]:
    """Run expiring inventory scan and emit alerts for flagged items."""
    from .intelligence import create_alert
    res = get_expiring_inventory(thresholds=thresholds, client=client)
    for item in res.get("items", []):
        tier = item["tier"]
        sev = "critical" if tier == "critical" else ("high" if tier == "high" else ("medium" if tier == "medium" else "low"))
        title = f"Expiring Stock: {item['sku']} ({item['name']})"
        msg = f"{item['quantity']} units expire in {item['days_to_expiry']} days (tier: {tier})."
        meta = {k: item[k] for k in ("sku", "name", "quantity", "expiry_date", "days_to_expiry", "tier")}
        try:
            create_alert(title=title, message=msg, severity=sev, category="inventory", metadata=meta, client=client)
        except Exception as e:
            logger.error(f"Alert creation failed: {e}")
    return res


def schedule_expiry_monitor(interval_minutes: int = 360, thresholds: List[int] | None = None) -> None:
    """Start a lightweight background loop to scan and alert on a cadence.

    For production, prefer APScheduler or cloud-native cron. MVP uses a daemon thread.
    """
    import threading, time

    def _loop():
        while True:
            try:
                scan_and_alert_expiring(thresholds=thresholds)
            except Exception as e:
                logger.error(f"Expiry monitor error: {e}")
            # sleep
            try:
                time.sleep(max(60, int(interval_minutes * 60)))
            except Exception:
                time.sleep(3600)

    t = threading.Thread(target=_loop, name="expiry-monitor", daemon=True)
    t.start()
