from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from typing import Any as DBClient
from ..db import db
from ..constants import TABLE_INVENTORY_EVENTS
from .sage_adapter.service import get_sage_kpi_batch_id, _latest_batch_for_table

# Use the literal table name used in the adapter for consistency until migrated
TABLE_SAGE_SNAPSHOT = "sage_inventory_snapshot"

logger = logging.getLogger("inventory")

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
        return resp.data[0] if resp.data else {}
    except Exception as e:
        logger.error(f"Failed to record inventory event: {e}")
        raise e

def get_realtime_stock(sku: str, client: DBClient = db) -> Dict[str, Any]:
    """
    Calculate current stock deterministically:
    Current = Last Sage Snapshot + Sum(Events since Snapshot)
    """
    # 1. Fetch Baseline (Last Sage Snapshot)
    # limit=1 + order desc ensures we get the very latest import entry for this SKU
    sage_batch_id = get_sage_kpi_batch_id() or _latest_batch_for_table(TABLE_SAGE_SNAPSHOT, client)
    snap_q = client.table(TABLE_SAGE_SNAPSHOT)\
        .select("sku, name, quantity, imported_at, unit_cost")\
        .eq("sku", sku)
    if sage_batch_id:
        snap_q = snap_q.eq("batch_id", sage_batch_id)
    snap_resp = snap_q.order("imported_at", desc=True).limit(1).execute()

    snapshot = snap_resp.data[0] if snap_resp.data else None
    
    baseline_qty = 0.0
    baseline_ts = None
    sku_name = "Unknown Product"

    if snapshot:
        baseline_qty = float(snapshot.get("quantity", 0))
        baseline_ts = snapshot.get("imported_at")
        sku_name = snapshot.get("name", sku)
    
    # 2. Fetch Delta (Events since baseline timestamp)
    query = client.table(TABLE_INVENTORY_EVENTS)\
        .select("quantity_change, event_type, created_at")\
        .eq("sku", sku)
        
    if baseline_ts:
        query = query.gt("created_at", baseline_ts)
        
    events_resp = query.execute()
    events = events_resp.data or []

    # 3. Calculate Operational Stock
    delta_qty = sum(float(e["quantity_change"]) for e in events)
    current_qty = baseline_qty + delta_qty

    return {
        "sku": sku,
        "name": sku_name,
        "baseline": {
            "quantity": baseline_qty,
            "source": "Sage 2013",
            "as_of": baseline_ts
        },
        "events": {
            "count": len(events),
            "net_change": delta_qty
        },
        "current_stock": current_qty,
        "status": "In Stock" if current_qty > 0 else "Out of Stock"
    }

def get_inventory_summary(limit: int = 50, client: DBClient = db) -> List[Dict[str, Any]]:
    """
    Bulk inventory summary directly from sage_inventory_snapshot.

    Strategy:
      1. Pull latest rows from sage_inventory_snapshot ordered by imported_at DESC.
         Deduplicate by SKU in Python — keeps the freshest row per SKU.
         No batch_id filter: we always surface whatever is in the table.
      2. Fetch all inventory_events in one shot and merge deltas in Python.
      3. Fall back to inventory_items + stock_levels only if the snapshot is empty.

    This replaces the previous N+1 loop (get_realtime_stock per SKU) which
    fired 2 DB queries per SKU and caused timeouts with 500+ rows.
    """
    # ── Step 1: bulk snapshot read (no batch_id filter) ──────────────────────
    try:
        snap_resp = (
            client.table(TABLE_SAGE_SNAPSHOT)
            .select("sku, name, quantity, unit_cost, imported_at")
            .order("imported_at", desc=True)
            .limit(limit * 10)   # over-fetch to cover duplicate warehouse rows per SKU
            .execute()
        )
    except Exception as e:
        logger.error(f"sage_inventory_snapshot bulk query failed: {e}")
        snap_resp = type("_R", (), {"data": []})()  # empty sentinel

    # Deduplicate: keep first (latest) row per SKU
    seen_skus: set = set()
    snapshots: Dict[str, Dict[str, Any]] = {}
    for row in (snap_resp.data or []):
        sku = row.get("sku")
        if not sku:
            continue
        if sku not in seen_skus:
            seen_skus.add(sku)
            snapshots[sku] = row
        else:
            # Sum warehouse quantities for the same SKU / same import batch
            snapshots[sku]["quantity"] = (
                float(snapshots[sku].get("quantity") or 0)
                + float(row.get("quantity") or 0)
            )

    if not snapshots:
        # ── Fallback: inventory_items + stock_levels ──────────────────────────
        logger.info("sage_inventory_snapshot empty; falling back to inventory_items + stock_levels")
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
                })
        except Exception as e:
            logger.error(f"Inventory module fallback failed: {e}")
        return results

    # ── Step 2: bulk events read — ONE query for all SKUs ────────────────────
    events_by_sku: Dict[str, List[Dict[str, Any]]] = {s: [] for s in snapshots}
    try:
        ev_resp = (
            client.table(TABLE_INVENTORY_EVENTS)
            .select("sku, quantity_change, event_type, created_at")
            .in_("sku", list(snapshots.keys()))
            .order("created_at", desc=False)
            .execute()
        )
        for ev in (ev_resp.data or []):
            s = ev.get("sku")
            if s and s in events_by_sku:
                events_by_sku[s].append(ev)
    except Exception as e:
        logger.warning(f"Inventory events bulk fetch failed (non-fatal): {e}")

    # ── Step 3: merge snapshot + events ─────────────────────────────────────
    results = []
    for sku, snap in list(snapshots.items())[:limit]:
        baseline_qty = float(snap.get("quantity") or 0)
        baseline_ts  = snap.get("imported_at")
        sku_name     = snap.get("name") or sku

        # Only count events that occurred AFTER the snapshot timestamp
        relevant_events = [
            e for e in events_by_sku.get(sku, [])
            if not baseline_ts or (e.get("created_at") or "") > str(baseline_ts)
        ]
        delta_qty = sum(float(e.get("quantity_change") or 0) for e in relevant_events)
        current_qty = baseline_qty + delta_qty

        results.append({
            "sku": sku,
            "name": sku_name,
            "baseline": {
                "quantity": baseline_qty,
                "source": "sage_inventory_snapshot",
                "as_of": baseline_ts,
            },
            "events": {
                "count": len(relevant_events),
                "net_change": delta_qty,
            },
            "current_stock": current_qty,
            "status": "In Stock" if current_qty > 0 else "Out of Stock",
        })

    logger.info(f"get_inventory_summary: returned {len(results)} SKUs from sage_inventory_snapshot")
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


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Prefer ISO 8601 (YYYY-MM-DD or full timestamp)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
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
        # If expiry_date column is missing, skip gracefully
        return {"items": [], "summary": {"batch_id": batch_id, "count": 0, "note": "expiry_date column missing"}}
    rows = resp.data or []
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
