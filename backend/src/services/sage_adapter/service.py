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

# Sage aged-debtor exports carry no due_date; standard trade terms applied to the
# invoice date let AR aging still be computed. Keep in sync with agents_exec.py.
DEFAULT_AR_TERMS_DAYS = 30


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


def _enrich_with_items_metadata(rows: List[Dict[str, Any]], client: DBClient = db) -> List[Dict[str, Any]]:
    """Merge sage_items_snapshot catalog fields (expiry_date, batch_number, category,
    reorder_level) onto inventory rows keyed by sku == item_id.

    sage_inventory_snapshot (stock qty/cost/valuation) and sage_items_snapshot
    (catalog metadata incl. pharmaceutical expiry_date/batch_number) are separate
    import pipelines with no FK between them — callers of latest_inventory_snapshot/
    inventory_by_skus previously never saw expiry or batch data at all.
    """
    if not rows:
        return rows
    skus = {r.get("sku") for r in rows if r.get("sku")}
    if not skus:
        return rows
    try:
        items_resp = (
            client.table("sage_items_snapshot")
            .select("item_id, item_name, category, reorder_level, expiry_date, batch_number")
            .in_("item_id", list(skus))
            .order("imported_at", desc=True)
            .execute()
        )
    except Exception as e:
        logging.warning(f"_enrich_with_items_metadata query failed (non-fatal): {e}")
        return rows
    # Keep the earliest expiry per SKU (most operationally relevant — the batch
    # that runs out first), not just the latest-imported row.
    meta_by_sku: Dict[str, Dict[str, Any]] = {}
    for r in (items_resp.data or []):
        sku = r.get("item_id")
        if not sku:
            continue
        existing = meta_by_sku.get(sku)
        if existing is None:
            meta_by_sku[sku] = r
            continue
        new_exp, cur_exp = r.get("expiry_date"), existing.get("expiry_date")
        if new_exp and (not cur_exp or str(new_exp) < str(cur_exp)):
            meta_by_sku[sku] = r
    for row in rows:
        meta = meta_by_sku.get(row.get("sku") or "")
        if meta:
            row["category"] = meta.get("category") or None
            row["reorder_level"] = meta.get("reorder_level")
            row["expiry_date"] = meta.get("expiry_date")
            row["batch_number"] = meta.get("batch_number") or None
        else:
            row.setdefault("expiry_date", None)
            row.setdefault("batch_number", None)
    return rows


def latest_inventory_snapshot(client: DBClient = db, limit: int = 200) -> List[Dict[str, Any]]:
    """Return latest inventory rows from snapshot table, aggregated per SKU.

    Multiple warehouse rows for the same SKU are merged: quantity and valuation
    are summed across warehouses so each SKU appears exactly once.

    NOTE: We do NOT use get_sage_kpi_batch_id() here. The globally promoted KPI
    batch_id belongs to finance/GL imports and will never match rows in
    sage_inventory_snapshot, returning 0 rows. Go directly to the table instead.
    Once ACE Books is live, stock comes from v_inventory (ACE Books FIFO stock);
    the Sage stock batch lists every item twice and would double every quantity.
    """
    from src.fin.readmodel import live
    if live():
        return _books_stock(client, limit=limit)
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
        return _enrich_with_items_metadata(result, client)

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
    return _enrich_with_items_metadata(result, client)


def _books_stock(client: DBClient = db, limit: int = 200, skus: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Legacy inventory-snapshot shape, from ACE Books (v_inventory + FIFO valuation)."""
    from src.fin.db import q as _q, tx as _tx
    with _tx() as conn:
        rows = _q(conn, """SELECT v.sku, v.name, v.current_stock AS quantity, v.expiry_date, v.batch_number, v.category, v.reorder_level,
                                  CASE WHEN v.current_stock > 0 THEN ROUND(val.v / v.current_stock, 2) END AS unit_cost,
                                  COALESCE(val.v, 0) AS valuation, now() AS imported_at, v.stock_source
                           FROM v_inventory v
                           LEFT JOIN (SELECT sku, SUM(qty_remaining*unit_cost) v FROM fin_cost_layers GROUP BY sku) val ON val.sku=v.sku
                           WHERE (%s::text[] IS NULL OR v.sku = ANY(%s)) AND (%s::text[] IS NOT NULL OR v.current_stock <> 0)
                           ORDER BY valuation DESC LIMIT %s""", (skus, skus, skus, limit if not skus else len(skus)))
    return [{**r, "quantity": float(r["quantity"] or 0), "valuation": float(r["valuation"] or 0),
             "unit_cost": float(r["unit_cost"]) if r["unit_cost"] is not None else None} for r in rows]


def inventory_by_skus(skus: List[str], client: DBClient = db) -> List[Dict[str, Any]]:
    if not skus:
        return []
    from src.fin.readmodel import live
    if live():
        return _books_stock(client, skus=list(skus))
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
    return _enrich_with_items_metadata(list(latest.values()), client)


@ttl_cache(ttl_seconds=600, ignore_kwargs=("client",), tags=("finance", "finance_trend"))
def ar_trend_summary(client: DBClient = db, periods: int = 6) -> Dict[str, Any]:
    """Compute simple AR totals per period (last N periods).
    Groups by Month (YYYY-MM). Once ACE Books is live: invoiced and still-open
    amounts per invoice month from v_customer_invoices (Sage history + ACE Books).
    """
    from src.fin.readmodel import live
    if live():
        from src.services import books_analytics
        return {"periods": books_analytics.ar_by_month(periods), "source": "ACE Books"}
    ar_batch = _latest_batch_for_table("sage_ar_snapshot", client)
    q = client.table("sage_ar_snapshot").select("date,amount,balance").gt("amount", 0)
    if ar_batch:
        q = q.eq("batch_id", ar_batch)
    resp = q.order("date", desc=True).limit(50000).execute()
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
    # ACE Books is the system of record once live; Sage snapshots freeze at the cut-over.
    from src.fin import readmodel
    if readmodel.live():
        return readmodel.kpis()

    import datetime
    today = datetime.date.today()
    # Resolve batch per table to avoid cross-table mismatches when CSV files
    # are imported independently with different batch ids.

    def parse_date(d):
        try:
            return datetime.date.fromisoformat(d)
        except Exception:
            return None

    def effective_due(r):
        """Due date with standard-terms fallback from the invoice date."""
        dd = parse_date(str(r.get("due_date") or ""))
        if dd is not None:
            return dd
        inv = parse_date(str(r.get("date") or ""))
        return (inv + datetime.timedelta(days=DEFAULT_AR_TERMS_DAYS)) if inv else today

    # --- AR ---
    ar_batch = _latest_batch_for_table("sage_ar_snapshot", client)
    ar_q = client.table("sage_ar_snapshot").select("amount,balance,due_date,date").gt("amount", 0)
    if ar_batch:
        ar_q = ar_q.eq("batch_id", ar_batch)
    ar_data = (ar_q.limit(50000).execute().data or [])
    ar_total_amount = sum(float(r.get("amount") or 0) for r in ar_data)
    ar_total_balance = sum(float(r.get("balance") or 0) for r in ar_data)
    ar_overdue = sum(
        1 for r in ar_data
        if effective_due(r) < today
        and float(r.get("balance") or 0) > 0
    )

    # --- AP ---
    ap_batch = _latest_batch_for_table("sage_ap_snapshot", client)
    ap_q = client.table("sage_ap_snapshot").select("amount,balance,due_date,date")
    if ap_batch:
        ap_q = ap_q.eq("batch_id", ap_batch)
    ap_data = (ap_q.limit(50000).execute().data or [])
    ap_total_amount = sum(float(r.get("amount") or 0) for r in ap_data)
    ap_total_balance = sum(float(r.get("balance") or 0) for r in ap_data)
    ap_overdue = sum(
        1 for r in ap_data
        if effective_due(r) < today
        and float(r.get("balance") or 0) > 0
    )

    # --- GL: cash position, revenue, and cost ---
    # Uses account_type from sage_coa_snapshot for robust classification
    # (Nigerian Sage 50 account codes don't follow US GAAP 4000-6999 ranges).
    cash: float | None = None
    total_revenue = 0.0
    total_cost = 0.0
    try:
        from src.constants import CASH_ACCOUNT_TYPE, REVENUE_ACCOUNT_TYPES, COST_ACCOUNT_TYPES

        # Build account_code → account_type lookup from CoA snapshot
        coa_res = client.table("sage_coa_snapshot").select("account_code,account_type").limit(2000).execute()
        acct_type_map: Dict[str, str] = {
            str(r.get("account_code") or "").strip(): (r.get("account_type") or "")
            for r in (coa_res.data or [])
            if r.get("account_code")
        }

        gl_batch = _latest_batch_for_table("sage_gl_snapshot", client)
        gl_q = client.table("sage_gl_snapshot").select("account_code,debit,credit")
        if gl_batch:
            gl_q = gl_q.eq("batch_id", gl_batch)
        gl_data = (gl_q.limit(50000).execute().data or [])

        if gl_data:
            cash_credits = 0.0
            cash_debits = 0.0
            for row in gl_data:
                code_raw = str(row.get("account_code") or "").strip()
                acct_type = acct_type_map.get(code_raw, "")
                debit = float(row.get("debit") or 0)
                credit = float(row.get("credit") or 0)

                if acct_type == CASH_ACCOUNT_TYPE:
                    cash_debits += debit
                    cash_credits += credit

                if acct_type in REVENUE_ACCOUNT_TYPES:
                    total_revenue += credit - debit

                if acct_type in COST_ACCOUNT_TYPES:
                    total_cost += debit - credit

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

    Uses due_date when present. Sage aged-debtor exports carry no due_date, so
    invoice date + DEFAULT_AR_TERMS_DAYS standard trade terms is used as the
    fallback; rows without either date are treated as current.
    """
    # ACE Books is the system of record once live; Sage snapshots freeze at the cut-over.
    from src.fin import readmodel
    if readmodel.live():
        return readmodel.ar_aging_buckets()

    import datetime
    today = datetime.date.today()
    def parse_date(d):
        try:
            return datetime.date.fromisoformat(d)
        except Exception:
            return None
    batch_id = _latest_batch_for_table("sage_ar_snapshot", client)
    q = client.table("sage_ar_snapshot").select("due_date,date,balance").gt("balance", 0)
    if batch_id:
        q = q.eq("batch_id", batch_id)
    resp = q.limit(50000).execute()
    buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_plus": 0.0}
    for r in resp.data or []:
        bal = float(r.get("balance") or 0)
        dd = parse_date(str(r.get("due_date") or ""))
        if dd is None:
            inv = parse_date(str(r.get("date") or ""))
            dd = (inv + datetime.timedelta(days=DEFAULT_AR_TERMS_DAYS)) if inv else today
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
    # ACE Books is the system of record once live; Sage snapshots freeze at the cut-over.
    from src.fin import readmodel
    if readmodel.live():
        return readmodel.ar_aging_customers(bucket)

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

    # Fetch AR invoices (real balances only — aged-summary rows carry 0)
    batch_id = _latest_batch_for_table("sage_ar_snapshot", client)
    ar_q = client.table("sage_ar_snapshot").select(
        "invoice_id,customer_id,due_date,date,amount,balance,status"
    ).gt("balance", 0)
    if batch_id:
        ar_q = ar_q.eq("batch_id", batch_id)
    ar_resp = ar_q.limit(50000).execute()
    rows = ar_resp.data or []

    # Aggregate by customer within bucket range
    per_cust: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = r.get("customer_id") or ""
        if not cid:
            continue
        dd = parse_date(str(r.get("due_date") or ""))
        if dd is None:
            import datetime as _dt
            inv = parse_date(str(r.get("date") or ""))
            dd = (inv + _dt.timedelta(days=DEFAULT_AR_TERMS_DAYS)) if inv else today
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
                "customer_name": meta.get("name") or cid,
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
    """Return latest GL rows (ACE Books monthly ledger movement once live, else the Sage snapshot)."""
    from src.fin.readmodel import live
    if live():
        from src.services import books_analytics
        return books_analytics.gl_rows(limit=limit)
    # Always use the truly most-recent GL batch, matching kpis()'s resolution —
    # the promoted batch pointer is a single, coarse cross-table marker that
    # isn't guaranteed to be re-promoted on every import, so preferring it here
    # risked silently serving stale GL data even though newer rows existed.
    batch_id = _latest_batch_for_table("sage_gl_snapshot", client)
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
        fallback_batch = get_sage_kpi_batch_id()
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
    Once ACE Books is live: every invoice from v_customer_invoices.
    """
    from src.fin.readmodel import live
    if live():
        from src.fin.db import q as _q, tx as _tx
        with _tx() as conn:
            rows = _q(conn, """SELECT invoice_id AS invoice_number, customer_id, customer_name, date AS invoice_date, due_date,
                                      amount AS total_amount, balance AS balance_due, status, source
                               FROM v_customer_invoices WHERE (%s::text IS NULL OR status=%s)
                               ORDER BY date DESC LIMIT %s""", (status, status, limit))
        return {"invoices": rows, "total": len(rows), "note": "ACE Books (Sage history to 30 Jun 2026 + ACE Books invoices)"}
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
