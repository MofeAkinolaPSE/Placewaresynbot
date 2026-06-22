from __future__ import annotations

import logging
import re
from typing import List, Dict, Any, Optional
from typing import Any as DBClient
from src.constants import (
    TABLE_STOCK_CACHE,
    CASH_GL_ACCOUNT_CODE,
    REVENUE_GL_ACCOUNT_MIN,
    REVENUE_GL_ACCOUNT_MAX,
    COST_GL_ACCOUNT_MIN,
    COST_GL_ACCOUNT_MAX,
)
from src.db import db, get_promoted_kpi_batch  # reuse configured client
from src.cache import ttl_cache


def get_sage_kpi_batch_id() -> str | None:
    """Return the currently promoted Sage KPI batch id, or None.

    Deliberately returns None (never the latest import-job batch) so every
    service falls back to its own per-table _latest_batch_for_table() resolver.
    This prevents a GL / AR CSV upload batch_id from being applied to
    sage_inventory_snapshot queries (which would match 0 rows).
    """
    promoted = get_promoted_kpi_batch("sage")
    if promoted and promoted.get("batch_id"):
        return promoted.get("batch_id")
    return None


def _latest_batch_for_table(table: str, client: DBClient = db) -> str | None:
    """Return the most recent batch_id written to a specific snapshot table.

    Used as a per-table fallback when the global promoted batch_id doesn't
    exist in that table (i.e., each CSV upload creates its own batch_id).
    """
    try:
        resp = client.table(table).select("batch_id").order("imported_at", desc=True).limit(1).execute()
        rows = resp.data or []
        return rows[0].get("batch_id") if rows else None
    except Exception:
        return None


def latest_inventory_snapshot(client: DBClient = db, limit: int = 200) -> List[Dict[str, Any]]:
    """Return latest inventory rows from snapshot table, aggregated per SKU.

    Multiple warehouse rows for the same SKU are merged: quantity and valuation
    are summed across warehouses so each SKU appears exactly once.
    """
    """Return latest inventory rows from snapshot table, aggregated per SKU.

    Multiple warehouse rows for the same SKU are merged: quantity and valuation
    are summed across warehouses so each SKU appears exactly once.

    NOTE: We do NOT use get_sage_kpi_batch_id() here. The globally promoted KPI
    batch_id belongs to finance/GL imports and will never match rows in
    sage_inventory_snapshot, returning 0 rows. Go directly to the table instead.
    """
    try:
        resp = (
            client.table("sage_inventory_snapshot")
            .select("sku,name,quantity,unit_cost,valuation,imported_at")
            .order("imported_at", desc=True)
            .order("id", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as e:
        logging.error(f"latest_inventory_snapshot query failed: {e}")
        resp = type("_R", (), {"data": []})()
    # Aggregate across warehouses: sum quantity + valuation, keep first occurrence for other fields
    aggregated: Dict[str, Dict[str, Any]] = {}
    for row in resp.data or []:
        sku = row.get("sku")
        if not sku:
            continue
        if sku not in aggregated:
            aggregated[sku] = dict(row)
        else:
            aggregated[sku]["quantity"] = float(aggregated[sku].get("quantity") or 0) + float(row.get("quantity") or 0)
            aggregated[sku]["valuation"] = float(aggregated[sku].get("valuation") or 0) + float(row.get("valuation") or 0)

    result = list(aggregated.values())
    if result:
        return result

    # Fallback: sage_inventory_snapshot is empty — read from inventory_items + stock_levels so
    # the public /stock endpoint stays populated when data was entered via the inventory module.
    try:
        items_resp = client.table("inventory_items").select("id, sku, name").limit(limit).execute()
        for item in (items_resp.data or []):
            item_id = item.get("id")
            sku = item.get("sku") or str(item_id)
            if not sku:
                continue
            stock_resp = client.table("stock_levels").select("quantity").eq("item_id", item_id).execute()
            total_qty = sum(float(s.get("quantity") or 0) for s in (stock_resp.data or []))
            result.append({
                "sku": sku,
                "name": item.get("name") or "Unknown",
                "quantity": total_qty,
                "unit_cost": None,
                "valuation": None,
                "imported_at": None,
            })
    except Exception:
        pass
    return result


def inventory_by_skus(skus: List[str], client: DBClient = db) -> List[Dict[str, Any]]:
    if not skus:
        return []
    resp = (
        client.table("sage_inventory_snapshot")
        .select("sku,name,quantity,unit_cost,valuation,imported_at")
        .in_("sku", skus)
        .order("imported_at", desc=True)
        .order("id", desc=True)
        .execute()
    )
    # Deduplicate by SKU keeping latest
    latest: Dict[str, Dict[str, Any]] = {}
    for row in resp.data or []:
        s = row.get("sku")
        if s and s not in latest:
            latest[s] = row
    return list(latest.values())


@ttl_cache(ttl_seconds=600, ignore_kwargs=("client",), tags=("finance", "finance_trend"))
def ar_trend_summary(client: DBClient = db, periods: int = 6) -> Dict[str, Any]:
    """Compute simple AR totals per period (last N periods).
    Groups by Month (YYYY-MM).
    """
    ar_batch = get_sage_kpi_batch_id() or _latest_batch_for_table("sage_ar_snapshot", client)
    q = client.table("sage_ar_snapshot").select("date,amount,balance")
    if ar_batch:
        q = q.eq("batch_id", ar_batch)
    resp = q.order("date", desc=True).limit(10000).execute()
    data = resp.data or []
    buckets: Dict[str, Dict[str, float]] = {}
    
    for r in data:
        raw_date = r.get("date")
        if not raw_date:
            continue
        try:
            # Coerce date/datetime to ISO string, then extract YYYY-MM
            month_key = (raw_date.isoformat() if hasattr(raw_date, 'isoformat') else str(raw_date))[:7]
            b = buckets.setdefault(month_key, {"amount": 0.0, "balance": 0.0})
            b["amount"] += float(r.get("amount") or 0)
            b["balance"] += float(r.get("balance") or 0)
        except Exception:
            continue

    # Sort periods asc (chronological) for charts
    sorted_periods = sorted(buckets.keys())[-periods:] # take last N
    return {"periods": [{"period": p, **buckets[p]} for p in sorted_periods]}


@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",), tags=("finance", "finance_kpis"))
def kpis(client: DBClient = db) -> Dict[str, Any]:
    """Compute basic KPIs from snapshots: AR/AP totals, overdue counts, cash and P&L from GL.

    Cash is derived from the GL cash account (CASH_GL_ACCOUNT_CODE).
    total_revenue sums credit-side rows for revenue accounts (4000-4999).
    total_cost sums debit-side rows for cost/expense accounts (5000-6999).
    """
    import datetime
    today = datetime.date.today()
    # Resolve batch per table to avoid cross-table mismatches when CSV files
    # are imported independently with different batch ids.

    def parse_date(d):
        try:
            return datetime.date.fromisoformat(d)
        except Exception:
            return None

    # --- AR ---
    ar_batch = _latest_batch_for_table("sage_ar_snapshot", client)
    ar_q = client.table("sage_ar_snapshot").select("amount,balance,due_date")
    if ar_batch:
        ar_q = ar_q.eq("batch_id", ar_batch)
    ar_data = (ar_q.order("imported_at", desc=True).limit(10000).execute().data or [])
    ar_total_amount = sum(float(r.get("amount") or 0) for r in ar_data)
    ar_total_balance = sum(float(r.get("balance") or 0) for r in ar_data)
    ar_overdue = sum(
        1 for r in ar_data
        if (parse_date(r.get("due_date") or "") or today) < today
        and float(r.get("balance") or 0) > 0
    )

    # --- AP ---
    ap_batch = _latest_batch_for_table("sage_ap_snapshot", client)
    ap_q = client.table("sage_ap_snapshot").select("amount,balance,due_date")
    if ap_batch:
        ap_q = ap_q.eq("batch_id", ap_batch)
    ap_data = (ap_q.order("imported_at", desc=True).limit(10000).execute().data or [])
    ap_total_amount = sum(float(r.get("amount") or 0) for r in ap_data)
    ap_total_balance = sum(float(r.get("balance") or 0) for r in ap_data)
    ap_overdue = sum(
        1 for r in ap_data
        if (parse_date(r.get("due_date") or "") or today) < today
        and float(r.get("balance") or 0) > 0
    )

    # --- GL: cash position, revenue, and cost ---
    cash: float | None = None
    total_revenue = 0.0
    total_cost = 0.0
    try:
        gl_batch = _latest_batch_for_table("sage_gl_snapshot", client)
        gl_q = client.table("sage_gl_snapshot").select("account_code,debit,credit")
        if gl_batch:
            gl_q = gl_q.eq("batch_id", gl_batch)
        gl_data = (gl_q.limit(50000).execute().data or [])

        if gl_data:
            cash_credits = 0.0
            cash_debits = 0.0
            for row in gl_data:
                code_raw = row.get("account_code") or ""
                try:
                    # Handle formats: "ACC-4001", "4001", "4001-01", "ACC-1000"
                    # Extract the first numeric segment as the account number
                    m = re.search(r'\d+', str(code_raw))
                    if not m:
                        continue
                    code = int(m.group())
                except (ValueError, TypeError):
                    continue
                debit = float(row.get("debit") or 0)
                credit = float(row.get("credit") or 0)

                # Cash account
                if str(code_raw).strip() == CASH_GL_ACCOUNT_CODE or code == int(CASH_GL_ACCOUNT_CODE):
                    cash_debits += debit
                    cash_credits += credit

                # Revenue accounts (credit-side income)
                if REVENUE_GL_ACCOUNT_MIN <= code <= REVENUE_GL_ACCOUNT_MAX:
                    total_revenue += credit - debit  # net revenue contribution

                # Cost / expense accounts (debit-side spend)
                if COST_GL_ACCOUNT_MIN <= code <= COST_GL_ACCOUNT_MAX:
                    total_cost += debit - credit  # net cost contribution

            # Cash = total debits – total credits on the cash account (bank balance style)
            if cash_debits > 0 or cash_credits > 0:
                cash = round(cash_debits - cash_credits, 2)

        total_revenue = round(max(total_revenue, 0.0), 2)
        total_cost = round(max(total_cost, 0.0), 2)
    except Exception as exc:
        logging.warning(f"kpis(): GL query failed, cash/revenue/cost unavailable: {exc}")

    return {
        "ar": {"total_amount": ar_total_amount, "total_balance": ar_total_balance, "overdue_count": ar_overdue},
        "ap": {"total_amount": ap_total_amount, "total_balance": ap_total_balance, "overdue_count": ap_overdue},
        "cash": cash,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
    }


def ar_aging_buckets(client: DBClient = db) -> Dict[str, Any]:
    """Return AR aging buckets (0-30, 31-60, 61-90, 91+ days) by outstanding balance.

    Uses due_date compared to today; entries without due_date are treated as current.
    """
    import datetime
    today = datetime.date.today()
    def parse_date(d):
        try:
            return datetime.date.fromisoformat(d)
        except Exception:
            return None
    batch_id = get_sage_kpi_batch_id() or _latest_batch_for_table("sage_ar_snapshot", client)
    q = client.table("sage_ar_snapshot").select("due_date,balance")
    if batch_id:
        q = q.eq("batch_id", batch_id)
    resp = q.order("imported_at", desc=True).limit(10000).execute()
    buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_plus": 0.0}
    for r in resp.data or []:
        bal = float(r.get("balance") or 0)
        dd = parse_date(r.get("due_date") or "") or today
        delta = (today - dd).days
        if delta <= 30:
            buckets["0_30"] += bal
        elif delta <= 60:
            buckets["31_60"] += bal
        elif delta <= 90:
            buckets["61_90"] += bal
        else:
            buckets["91_plus"] += bal
    return buckets


def ar_aging_customers(bucket: str, client: DBClient = db) -> List[Dict[str, Any]]:
    """Return customer-level AR aging details for a given bucket.

    Bucket may be provided as "0_30", "0-30", "0-30 days" etc.
    Output aggregates invoices per customer with total balances and metadata.
    """
    import datetime

    today = datetime.date.today()

    def parse_date(d: str | None):
        if not d:
            return None
        try:
            return datetime.date.fromisoformat(d)
        except Exception:
            return None

    # Normalize bucket label
    raw = (bucket or "").strip().lower().replace("_", "-")
    if raw.startswith("0-30"):
        key = "0_30"
        min_days, max_days = 0, 30
    elif raw.startswith("31-60"):
        key = "31_60"
        min_days, max_days = 31, 60
    elif raw.startswith("61-90"):
        key = "61_90"
        min_days, max_days = 61, 90
    elif raw.startswith("90+") or raw.startswith("91+"):
        key = "91_plus"
        min_days, max_days = 91, 10_000
    else:
        # Unknown bucket; return empty list
        return []

    # Fetch AR invoices
    batch_id = get_sage_kpi_batch_id() or _latest_batch_for_table("sage_ar_snapshot", client)
    ar_q = client.table("sage_ar_snapshot").select(
        "invoice_id,customer_id,due_date,amount,balance,status"
    )
    if batch_id:
        ar_q = ar_q.eq("batch_id", batch_id)
    ar_resp = ar_q.order("imported_at", desc=True).limit(10000).execute()
    rows = ar_resp.data or []

    # Aggregate by customer within bucket range
    per_cust: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = r.get("customer_id") or ""
        if not cid:
            continue
        dd = parse_date(r.get("due_date")) or today
        bal = float(r.get("balance") or 0)
        amt = float(r.get("amount") or 0)
        delta = (today - dd).days
        # Normalise negative deltas (not yet due) into 0-30 bucket
        if delta < 0:
            bucket_days = 0
        else:
            bucket_days = delta

        if not (min_days <= bucket_days <= max_days):
            continue

        entry = per_cust.setdefault(
            cid,
            {
                "customer_id": cid,
                "total_balance": 0.0,
                "total_amount": 0.0,
                "invoices_count": 0,
                "max_days_overdue": 0,
                "earliest_due_date": None,
                "bucket": key,
            },
        )
        entry["total_balance"] += bal
        entry["total_amount"] += amt
        entry["invoices_count"] += 1
        if bucket_days > entry["max_days_overdue"]:
            entry["max_days_overdue"] = bucket_days
        if not entry["earliest_due_date"] or dd < entry["earliest_due_date"]:
            entry["earliest_due_date"] = dd

    if not per_cust:
        return []

    # Fetch latest customer metadata for names/contact
    cust_q = client.table("sage_customers_snapshot").select(
        "customer_id,name,email,phone,status,imported_at"
    )
    if batch_id:
        cust_q = cust_q.eq("batch_id", batch_id)
    cust_resp = cust_q.order("imported_at", desc=True).limit(10000).execute()
    cust_rows = cust_resp.data or []

    latest_meta: Dict[str, Dict[str, Any]] = {}
    for r in cust_rows:
        cid = r.get("customer_id") or ""
        if not cid or cid in latest_meta:
            continue
        latest_meta[cid] = r

    out: List[Dict[str, Any]] = []
    for cid, agg in per_cust.items():
        meta = latest_meta.get(cid, {})
        earliest = agg["earliest_due_date"]
        out.append(
            {
                "customer_id": cid,
                "customer_name": meta.get("name"),
                "email": meta.get("email"),
                "phone": meta.get("phone"),
                "status": meta.get("status"),
                "total_balance": agg["total_balance"],
                "total_amount": agg["total_amount"],
                "invoices_count": agg["invoices_count"],
                "max_days_overdue": agg["max_days_overdue"],
                "earliest_due_date": earliest.isoformat() if isinstance(earliest, datetime.date) else None,
                "bucket": agg["bucket"],
            }
        )

    # Sort by total_balance desc
    out.sort(key=lambda x: x["total_balance"], reverse=True)
    return out


@ttl_cache(ttl_seconds=120, ignore_kwargs=("client",), tags=("finance", "finance_gl"))
def get_latest_gl_snapshot(limit: int = 1000, client: DBClient = db) -> List[Dict[str, Any]]:
    """Return latest GL rows from snapshot table."""
    # Prefer promoted batch if configured, but fall back to latest table batch
    # when promoted batch has no rows (common with independent imports).
    batch_id = get_sage_kpi_batch_id()
    rows: List[Dict[str, Any]] = []

    if batch_id:
        resp = (
            client.table("sage_gl_snapshot")
            .select("*")
            .eq("batch_id", batch_id)
            .order("period", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []

    if not rows:
        fallback_batch = _latest_batch_for_table("sage_gl_snapshot", client)
        if fallback_batch:
            resp = (
                client.table("sage_gl_snapshot")
                .select("*")
                .eq("batch_id", fallback_batch)
                .order("period", desc=True)
                .limit(limit)
                .execute()
            )
            rows = resp.data or []

    # Final fallback: use directly-extracted sage_gl_transactions (Btrieve binary import)
    if not rows:
        try:
            resp = (
                client.table("sage_gl_transactions")
                .select("id, post_date, gl_account, description, source, imported_at")
                .order("post_date", desc=True)
                .limit(limit)
                .execute()
            )
            raw = resp.data or []
            # Normalise to the shape callers expect (account_code, account_name, period)
            rows = [
                {
                    "id": r.get("id"),
                    "account_code": r.get("gl_account") or "",
                    "account_name": r.get("description") or "",
                    "period": str(r.get("post_date") or "")[:7],  # YYYY-MM
                    "debit": 0.0,
                    "credit": 0.0,
                    "description": r.get("description") or "",
                    "post_date": r.get("post_date"),
                    "source": r.get("source") or "sage50",
                    "imported_at": r.get("imported_at"),
                }
                for r in raw
            ]
        except Exception:
            rows = []

    return rows


def get_invoices(
    client: DBClient = db,
    limit: int = 50,
    status: str | None = None,
) -> Dict[str, Any]:
    """Return Placeware AR invoices synced from Sage 50.

    Reads placeware_invoices (populated automatically when sales_invoices.csv
    is imported). Falls back to v_ar_invoices Silver view if the table is empty.
    """
    try:
        q = (
            client.table("placeware_invoices")
            .select("*")
            .order("invoice_date", desc=True)
            .limit(limit)
        )
        rows = q.execute().data or []

        # Fallback: Silver view (when placeware_invoices not yet populated)
        if not rows:
            vq = client.table("v_ar_invoices").select("*").limit(limit)
            rows = vq.execute().data or []

        if status:
            rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]

        return {
            "invoices": rows,
            "total": len(rows),
            "note": "Synced from Sage 50 via CSV import" if rows else "No invoices imported yet — export sales_invoices.csv from Sage 50 and upload via Settings > Sage Import.",
        }
    except Exception as e:
        logger.error(f"get_invoices error: {e}")
        return {"invoices": [], "total": 0, "error": str(e)}
