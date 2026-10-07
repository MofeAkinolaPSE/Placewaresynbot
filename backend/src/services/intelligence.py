from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from typing import Any as DBClient
import json

from ..db import db
from ..constants import TABLE_ALERTS, TABLE_BRIEFINGS, EXEC_SUMMARY_AR_OVERDUE_THRESHOLD
from ..cache import ttl_cache, invalidate_cache_tags
from .realtime import realtime_hub
import asyncio
from .sage_adapter.service import kpis as finance_kpis, ar_trend_summary, ar_aging_buckets
from src.fin.readmodel import live as _books_live
from .inventory import get_inventory_summary, get_latest_batch_sku_count, get_recent_inventory_movements, classify_stock_status
from .ops import kpis as ops_kpis, stock_turnover_series
from .hr import payroll_and_absence_summary
from .crm import risk_scores as crm_risk_scores, get_crm_stats
from .staff_ops import get_timesheets
from .qc import get_qc_summary

logger = logging.getLogger("intelligence")


def _dt_to_str(val: object) -> str:
    """Coerce psycopg2 datetime/date to ISO string; passthrough for str/None."""
    if val is None:
        return ""
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


MAX_ANALYTICS_ROWS = 3000


def compute_change_pct(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 1.0
    return (current - previous) / abs(previous)


def trend_label(change_pct: float, positive_is_good: bool = True, flat_threshold: float = 0.02) -> str:
    if abs(change_pct) < flat_threshold:
        return "Flat"
    improving = change_pct > 0 if positive_is_good else change_pct < 0
    return "Improving" if improving else "Declining"

# --- Dashboard Aggregators ---

@ttl_cache(ttl_seconds=60, ignore_kwargs=("client",), tags=("inventory", "inventory_dashboard", "executive"))
def get_inventory_dashboard(limit: int = 50, client: DBClient = db) -> Dict[str, Any]:
    """
    Inventory Health Check:
    - Low stock items
    - Recent movements
    - Coverage risk
    """
    # KPI counts and the critical-items list must both come from the same
    # v_inventory read — previously the counts scanned up to 5000 v_inventory
    # rows while the critical_items list was independently derived from a
    # different, 100-row-limited get_inventory_summary() call using a flat
    # <10 rule that ignored reorder_level entirely, so the two numbers shown
    # together on one screen could disagree with each other.
    try:
        inv_rows = (
            client.table("v_inventory")
            .select("sku,name,current_stock,reorder_level,expiry_date")
            .limit(5000)
            .execute()
            .data
            or []
        )
    except Exception:
        inv_rows = []

    # "Out of stock" only counts items that are still commercially active —
    # zero-stock catalog entries that expired years ago and haven't traded
    # are dead history, not stockouts. Active = future expiry date OR traded
    # in the current fiscal period (unit-activity rows, transaction_id ACT_*).
    traded_skus: set = set()
    from src.fin.readmodel import live as _live
    if _live():
        import datetime as _d
        from src.services import books_analytics
        traded_skus = books_analytics.traded_skus(_d.date(_d.date.today().year, 1, 1))
    try:
        if traded_skus:
            raise StopIteration  # ACE Books already answered
        act_res = (
            client.table("sage_inv_transactions_snapshot")
            .select("item_id,quantity_in,quantity_out")
            .like("transaction_id", "ACT_%")
            .limit(5000)
            .execute()
        )
        traded_skus = {
            r.get("item_id")
            for r in (act_res.data or [])
            if r.get("item_id")
            and (float(r.get("quantity_in") or 0) > 0 or float(r.get("quantity_out") or 0) > 0)
        }
    except (Exception, StopIteration):
        pass

    if inv_rows:
        import datetime as _dt
        today = _dt.date.today()

        def _future_expiry(r) -> bool:
            raw = r.get("expiry_date")
            if not raw:
                return False
            try:
                return _dt.date.fromisoformat(str(raw)[:10]) >= today
            except Exception:
                return False

        total_active_skus = len(inv_rows)
        low_stock_count = 0
        out_of_stock_count = 0
        catalog_zero_stock_count = 0
        low_stock_rows: List[Dict[str, Any]] = []
        for r in inv_rows:
            qty = float(r.get("current_stock") or 0)
            status = classify_stock_status(qty, r.get("reorder_level"))
            if status == "out_of_stock":
                catalog_zero_stock_count += 1
                if _future_expiry(r) or r.get("sku") in traded_skus:
                    out_of_stock_count += 1
            elif status in ("critical", "warning"):
                low_stock_count += 1
                low_stock_rows.append({**r, "current_stock": qty, "stock_status": status})
        # Most urgent first: critical before warning, lowest stock first within each tier.
        low_stock_rows.sort(key=lambda r: (r["stock_status"] != "critical", r["current_stock"]))
        critical_items = low_stock_rows[:limit]
    else:
        summary = get_inventory_summary(limit=100, client=client)
        total_active_skus = get_latest_batch_sku_count(client=client) or len(summary)
        low_stock_count = sum(1 for i in summary if i.get("stock_status") in ("critical", "warning"))
        out_of_stock_count = sum(1 for i in summary if i.get("stock_status") == "out_of_stock")
        catalog_zero_stock_count = out_of_stock_count
        critical_items = [i for i in summary if i.get("stock_status") in ("critical", "warning")][:limit]

    recent_movements = get_recent_inventory_movements(limit=limit, client=client)

    return {
        "summary": {
            "total_active_skus": total_active_skus,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "catalog_zero_stock_count": catalog_zero_stock_count,
        },
        "critical_items": critical_items,
        "recent_movements": recent_movements,
    }

@ttl_cache(ttl_seconds=60, ignore_kwargs=("client",), tags=("staff", "workforce_dashboard", "executive", "hr_summary"))
def get_workforce_dashboard(client: DBClient = db) -> Dict[str, Any]:
    """
    Workforce Pulse:
    - Hours logged this week
    - Active staff count
    - Departmental breakdown
    """
    # Simple aggregations from Phase 2 tables
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    
    sheets = get_timesheets(start_date=week_start, limit=500, client=client)
    
    dept_hours = {}
    total_hours = 0
    active_staff = set()
    
    for s in sheets:
        h = float(s.get("hours_worked", 0))
        d = s.get("department", "Unknown")
        dept_hours[d] = dept_hours.get(d, 0) + h
        total_hours += h
        active_staff.add(s.get("staff_id"))
    
    active_count = len(active_staff)
    
    # Fallback: If no timesheets logged (Phase 2), show total registered staff (Phase 1).
    # No batch_id filter — the global KPI batch_id belongs to finance/GL, not staff snapshots.
    if active_count == 0:
        try:
            staff_q = client.table("sage_staff_snapshot").select("*", count="exact")
            staff_resp = staff_q.limit(1).execute()
            if staff_resp.count and staff_resp.count > 0:
                active_count = staff_resp.count

            # Fetch all departments for the headcount bar chart (1 person = 1 unit)
            all_staff = client.table("sage_staff_snapshot").select("department").limit(1000).execute()
            for s in all_staff.data:
                d = s.get("department") or "Unassigned"
                dept_hours[d] = dept_hours.get(d, 0) + 1

        except Exception as e:
            logger.warning(f"Workforce fallback failed: {e}")

    return {
        "period": "current_week",
        "total_hours": total_hours,
        "active_staff_count": active_count,
        "department_breakdown": dept_hours # now contains headcount if hours are empty
    }

# --- Alert Logic ---

def create_alert(
    title: str,
    message: str,
    severity: str,
    category: str,
    metadata: Optional[Dict] = None,
    client: DBClient = db
):
    """Event-driven notification log."""
    payload = {
        "title": title,
        "message": message,
        "severity": severity,
        "category": category,
        "metadata": metadata or {},
        "status": "unread"
    }
    client.table(TABLE_ALERTS).insert(payload).execute()
    invalidate_cache_tags("alerts", "executive", "risk_signals", "recommendations", "anomalies")

    # Best-effort realtime notification (non-blocking)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            realtime_hub.broadcast(
                "alerts_updates",
                {
                    "event": "alert_created",
                    "severity": severity,
                    "category": category,
                    "title": title,
                },
            )
        )
    except RuntimeError:
        pass

@ttl_cache(ttl_seconds=30, ignore_kwargs=("client",), tags=("alerts", "executive"))
def get_active_alerts(client: DBClient = db) -> List[Dict[str, Any]]:
    return client.table(TABLE_ALERTS)\
        .select("*")\
        .eq("status", "unread")\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute().data or []


def filter_alerts_by_category(alerts: List[Dict[str, Any]], viewer_roles: List[str]) -> List[Dict[str, Any]]:
    """Restrict a raw alert list to only the categories the viewer's roles
    may see, per constants.ALERT_CATEGORY_VISIBILITY. get_active_alerts()
    itself stays unfiltered/cached (role-variance doesn't belong inside a
    cached function's key) -- this is the actual boundary that stops e.g. an
    ops-role viewer of GET /dashboard/alerts from seeing finance-category
    "Treasury Alert" text with a real embedded ₦ figure, which the endpoint's
    role gate alone didn't prevent (ops is in that gate's allowed set)."""
    from ..constants import ALERT_CATEGORY_VISIBILITY
    roles = {str(r).lower() for r in viewer_roles}
    out = []
    for a in alerts:
        category = a.get("category")
        allowed_roles = ALERT_CATEGORY_VISIBILITY.get(category, {"admin", "management"})
        if allowed_roles is None or roles & allowed_roles:
            out.append(a)
    return out

# --- ACE Workstation (org-wide dashboard) Engine ---

def get_workstation_summary(roles: List[str], client: DBClient = db) -> Dict[str, Any]:
    """
    One shallow status card per department for the org-wide ACE Workstation
    (GET /dashboard/workstation) -- every authenticated user gets a response,
    but sensitive (₦-denominated) fields are only included in the dict for
    roles allowed to see them (constants.py's FINANCIAL_DATA_ROLES /
    CRM_PIPELINE_VALUE_ROLES / PROCUREMENT_VALUE_ROLES). Redaction happens
    here, server-side, before the response is built -- a role without access
    never receives the key at all, it isn't merely hidden client-side.

    Reuses each department's existing summary function rather than
    re-querying -- this is purely an aggregation + redaction layer.
    """
    from ..constants import FINANCIAL_DATA_ROLES, CRM_PIPELINE_VALUE_ROLES, PROCUREMENT_VALUE_ROLES, WORKSTATION_DRILL_IN_ROLES
    # Deferred import: purchase_orders.py is a router, not a service module
    # (compute_po_summary was extracted in-place there per this round's
    # plan, not into a new service file) -- importing at module load time
    # would be a backwards services->routers dependency; deferring avoids
    # any load-order coupling, matching the existing deferred-import
    # convention already used elsewhere in this codebase (e.g.
    # services/inventory.py's scan_and_alert_expiring importing create_alert).
    from ..routers.purchase_orders import compute_po_summary

    role_set = {str(r).lower() for r in roles}

    def can_drill_in(dept: str) -> bool:
        return bool(role_set & WORKSTATION_DRILL_IN_ROLES.get(dept, set()))

    # A bare count (unlike the raw alert title/message, which can embed a
    # real ₦ figure -- see filter_alerts_by_category's docstring) leaks
    # nothing on its own, so every department's card shows its own true
    # count regardless of viewer role -- deliberately NOT run through
    # filter_alerts_by_category, which would fail-closed to 0 for a
    # QC/HR/CRM/Operations viewer looking at their own department's card,
    # since only "finance"/"inventory"/"system" are mapped in
    # ALERT_CATEGORY_VISIBILITY.
    all_alerts = get_active_alerts(client=client)

    def alert_count(category: str) -> int:
        return sum(1 for a in all_alerts if a.get("category") == category)

    departments: Dict[str, Any] = {}

    # --- Inventory --- (no ₦ in this payload at all, no redaction needed)
    try:
        inv = get_inventory_dashboard(client=client)
        inv_summary = inv.get("summary", {})
        low = inv_summary.get("low_stock_count", 0)
        out = inv_summary.get("out_of_stock_count", 0)
        departments["inventory"] = {
            "total_active_skus": inv_summary.get("total_active_skus", 0),
            "low_stock_count": low,
            "out_of_stock_count": out,
            "status": "critical" if out > 0 else ("attention" if low > 0 else "healthy"),
            "alert_count": alert_count("inventory"),
            "can_drill_in": can_drill_in("inventory"),
            "drill_in_path": "/inventory",
        }
    except Exception as e:
        logger.warning(f"workstation: inventory card failed: {e}")
        departments["inventory"] = {"status": "unknown", "can_drill_in": can_drill_in("inventory"), "drill_in_path": "/inventory"}

    # --- Finance ---
    try:
        finance = finance_kpis(client)
        ar = finance.get("ar", {})
        overdue_ar = ar.get("overdue_count", 0)
        card = {
            # Matches risk_signals()'s existing >10 "at risk" threshold, for
            # consistency across every place this app frames AR as at-risk.
            "status": "at_risk" if overdue_ar > 10 else "healthy",
            "overdue_ar_count": overdue_ar,
            "alert_count": alert_count("finance"),
            "can_drill_in": can_drill_in("finance"),
            "drill_in_path": "/finance/analytics",
        }
        if role_set & FINANCIAL_DATA_ROLES:
            ap = finance.get("ap", {})
            card["ar_total_balance"] = ar.get("total_balance", 0)
            card["ap_total_balance"] = ap.get("total_balance", 0)
            card["ap_overdue_count"] = ap.get("overdue_count", 0)
        departments["finance"] = card
    except Exception as e:
        logger.warning(f"workstation: finance card failed: {e}")
        departments["finance"] = {"status": "unknown", "can_drill_in": can_drill_in("finance"), "drill_in_path": "/finance/analytics"}

    # --- HR --- (headcount/hours only, never pay -- no redaction needed)
    try:
        wf = get_workforce_dashboard(client=client)
        departments["hr"] = {
            "active_staff_count": wf.get("active_staff_count", 0),
            "total_hours_this_week": wf.get("total_hours", 0),
            "status": "healthy",
            "alert_count": alert_count("hr"),
            "can_drill_in": can_drill_in("hr"),
            "drill_in_path": "/hr",
        }
    except Exception as e:
        logger.warning(f"workstation: hr card failed: {e}")
        departments["hr"] = {"status": "unknown", "can_drill_in": can_drill_in("hr"), "drill_in_path": "/hr"}

    # --- Quality Control --- (already broadly visible, non-financial, correctly org-wide)
    try:
        qc = get_qc_summary(client=client)
        expiring = qc.get("expiring_critical_30d", 0)
        deviations = qc.get("open_deviations", 0)
        temp = qc.get("temp_alerts_today", 0)
        departments["quality_control"] = {
            "expiring_critical_30d": expiring,
            "open_deviations": deviations,
            "temp_alerts_today": temp,
            "status": "critical" if (expiring > 0 or deviations > 0 or temp > 0) else "healthy",
            "alert_count": alert_count("quality_control"),
            "can_drill_in": can_drill_in("quality_control"),
            "drill_in_path": "/quality-control",
        }
    except Exception as e:
        logger.warning(f"workstation: qc card failed: {e}")
        departments["quality_control"] = {"status": "unknown", "can_drill_in": can_drill_in("quality_control"), "drill_in_path": "/quality-control"}

    # --- CRM ---
    try:
        crm = get_crm_stats(client)
        card = {
            "open_prospects_count": crm.get("active_opps", 0),
            "win_rate_pct": crm.get("win_rate", 0),
            "status": "healthy",
            "alert_count": alert_count("crm"),
            "can_drill_in": can_drill_in("crm"),
            "drill_in_path": "/crm",
        }
        if role_set & CRM_PIPELINE_VALUE_ROLES:
            card["pipeline_value"] = crm.get("pipeline_value", 0)
        departments["crm"] = card
    except Exception as e:
        logger.warning(f"workstation: crm card failed: {e}")
        departments["crm"] = {"status": "unknown", "can_drill_in": can_drill_in("crm"), "drill_in_path": "/crm"}

    # --- Operations (Purchase Orders) ---
    try:
        po = compute_po_summary(client=client)
        overdue_po = po.get("overdue_pos", 0)
        card = {
            "open_po_count": po.get("open_pos", 0),
            "overdue_po_count": overdue_po,
            "status": "attention" if overdue_po > 0 else "healthy",
            "alert_count": alert_count("operations"),
            "can_drill_in": can_drill_in("operations"),
            "drill_in_path": "/operations",
        }
        if role_set & PROCUREMENT_VALUE_ROLES:
            card["total_value"] = po.get("total_value", 0)
            card["open_value"] = po.get("open_value", 0)
            card["overdue_value"] = po.get("overdue_value", 0)
        departments["operations"] = card
    except Exception as e:
        logger.warning(f"workstation: operations card failed: {e}")
        departments["operations"] = {"status": "unknown", "can_drill_in": can_drill_in("operations"), "drill_in_path": "/operations"}

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "departments": departments,
    }


# --- Executive Briefing Engine ---

@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",), tags=("executive", "executive_briefing"))
def generate_executive_briefing(client: DBClient = db) -> Dict[str, Any]:
    """
    Holistic Business Summary.
    Combines Finance, Inventory, and Ops into a single JSON report.
    """
    # 1. Gather Data
    finance = finance_kpis(client)
    inventory = get_inventory_dashboard(limit=5, client=client)
    workforce = get_workforce_dashboard(client=client)
    alerts = get_active_alerts(client=client)

    # 1b. Live counts: ACE Books / CRM once live, else the directly-imported Sage tables
    # (AR/AP snapshots are empty — invoices were not entered in Sage;
    #  these tables hold the real master data from DAT file extraction)
    try:
        cust_res = client.table("sage_customers_snapshot").select("customer_id").execute()
        customer_count = len(set(
            r.get("customer_id") for r in (cust_res.data or []) if r.get("customer_id")
        ))
    except Exception:
        customer_count = 0

    try:
        items_res = client.table("sage_items_snapshot").select("item_id").execute()
        seen_skus: set = set()
        for r in (items_res.data or []):
            k = r.get("item_id") or ""
            if k:
                seen_skus.add(k)
        inventory_sku_count = len(seen_skus)
    except Exception:
        inventory_sku_count = inventory["summary"].get("total_active_skus", 0)

    try:
        gl_count_res = client.table("sage_gl_detail_snapshot").select("id", count="exact").limit(1).execute()
        gl_transaction_count = gl_count_res.count or 0
    except Exception:
        gl_transaction_count = 0

    try:
        ar_count_res = client.table("sage_ar_snapshot").select("id", count="exact").gt("amount", 0).limit(1).execute()
        ar_invoice_count = ar_count_res.count or 0
    except Exception:
        ar_invoice_count = 0

    try:
        prospect_res = client.table("crm_prospects").select("id").execute()
        prospect_count = len(prospect_res.data or [])
    except Exception:
        prospect_count = 0
    if _books_live():
        from src.services import books_analytics
        _c = books_analytics.data_counts()
        customer_count, inventory_sku_count = _c["customers"], _c["products"]
        gl_transaction_count, ar_invoice_count = _c["gl_lines"], _c["invoices"]

    # 2. Synthesize Insights (Deterministic)
    critical_risks = []
    if finance['ar']['overdue_count'] > 5:
        critical_risks.append("High volume of overdue AR invoices.")
    if inventory['summary']['out_of_stock_count'] > 0:
        critical_risks.append(f"{inventory['summary']['out_of_stock_count']} critical SKUs out of stock.")

    briefing = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "health_score": "Stable" if customer_count > 0 else ("Requires Attention" if critical_risks else "Stable"),
            "critical_risks": critical_risks,
            "focus_area": "Collections" if finance['ar']['overdue_count'] > 10 else "Inventory"
        },
        "finance_brief": {
            "cash_outstanding": finance['ar']['total_balance'],
            "cash_payable": finance['ap']['total_balance']
        },
        "inventory_brief": {
            "low_stock_alerts": inventory['summary']['low_stock_count']
        },
        "workforce_brief": {
            "weekly_hours": workforce['total_hours'],
            "top_dept": max(workforce['department_breakdown'], key=workforce['department_breakdown'].get) if workforce['department_breakdown'] else "None"
        },
        "latest_alerts": [a['title'] for a in alerts[:3]],
        "live_data": {
            "customer_count": customer_count,
            "inventory_sku_count": inventory_sku_count,
            "gl_transaction_count": gl_transaction_count,
            "prospect_count": prospect_count,
            "ar_invoice_count": ar_invoice_count,
            "note": (
                f"Database contains {customer_count} customers, {inventory_sku_count} inventory SKUs, "
                f"{gl_transaction_count:,} GL journal entries, and {prospect_count} CRM prospects."
                + (
                    " AR/AP invoices are not yet entered in Sage — revenue figures will show once invoices are posted."
                    if ar_invoice_count == 0 and finance['ap']['total_balance'] == 0
                    else f" {ar_invoice_count:,} AR invoices on file."
                )
            )
        }
    }
    
    # Cache it
    try:
        client.table(TABLE_BRIEFINGS).upsert(
            {"report_date": datetime.now().date().isoformat(), "content": briefing},
            on_conflict="report_date"
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to cache briefing: {e}")
        
    return briefing


def _last_two(series: list[dict], key: str) -> tuple[float, float] | None:
    if len(series) < 2:
        return None
    prev = float(series[-2].get(key) or 0)
    curr = float(series[-1].get(key) or 0)
    return curr, prev


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",), tags=("executive", "executive_summary"))
def executive_summary(client: DBClient = db) -> Dict[str, Any]:
    """Executive business health summary using existing analytics and deterministic rules."""
    findings: list[str] = []
    focus: list[str] = []
    risk_count = 0

    # Finance
    finance = finance_kpis(client)
    ar_trend = ar_trend_summary(client=client, periods=6).get("periods", [])
    ar_pair = _last_two(ar_trend, "balance")
    if ar_pair:
        ar_curr, ar_prev = ar_pair
        ar_change = compute_change_pct(ar_curr, ar_prev)
        ar_trend_label = trend_label(ar_change, positive_is_good=False)
        if ar_trend_label == "Declining" and ar_change > 0.1:
            findings.append("AR balance is rising, increasing cashflow pressure.")
            focus.append("Collections")
            risk_count += 1
    ar_overdue_count = finance.get("ar", {}).get("overdue_count", 0)
    if ar_overdue_count > EXEC_SUMMARY_AR_OVERDUE_THRESHOLD:
        findings.append(f"{ar_overdue_count} overdue AR invoice(s) require attention.")
        focus.append("Collections")
        risk_count += 1

    # Liquidity blind spot: surface when GL cash data is unavailable
    if finance.get("cash") is None:
        findings.append("Cash position unavailable — GL import required to assess liquidity.")
        focus.append("Finance")
        risk_count += 1

    # Operations
    ops = ops_kpis(client)
    turnover_series = stock_turnover_series(client=client, periods=6).get("series", [])
    turn_pair = _last_two(turnover_series, "turnover")
    if turn_pair:
        t_curr, t_prev = turn_pair
        t_change = compute_change_pct(t_curr, t_prev)
        t_trend = trend_label(t_change, positive_is_good=True)
        if t_trend == "Declining" and abs(t_change) > 0.1:
            findings.append("Stock turnover is slowing, indicating capital drag.")
            focus.append("Inventory")
            risk_count += 1

    # Downtime trend (approx via last two months)
    downtime_rows = client.table("ops_downtime_snapshot").select("minutes,imported_at").order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute().data or []
    buckets: dict[str, float] = {}
    for r in downtime_rows:
        k = _dt_to_str(r.get("imported_at"))[:7]
        if not k:
            continue
        buckets[k] = buckets.get(k, 0.0) + float(r.get("minutes") or 0)
    months = sorted(buckets.keys())
    if len(months) >= 2:
        d_prev = buckets[months[-2]]
        d_curr = buckets[months[-1]]
        d_change = compute_change_pct(d_curr, d_prev)
        d_trend = trend_label(d_change, positive_is_good=False)
        if d_trend == "Declining" and d_change > 0.1:
            findings.append("Operational downtime is rising month-over-month.")
            focus.append("Operations")
            risk_count += 1

    # HR
    hr = payroll_and_absence_summary(client=client, periods=3)
    abs_trend = hr.get("absenteeism_trend", [])
    abs_pair = _last_two(abs_trend, "hours")
    if abs_pair:
        a_curr, a_prev = abs_pair
        a_change = compute_change_pct(a_curr, a_prev)
        a_trend = trend_label(a_change, positive_is_good=False)
        if a_trend == "Declining" and a_change > 0.1:
            findings.append("Absence hours are increasing, impacting productivity.")
            focus.append("Workforce")
            risk_count += 1

    # Status
    if risk_count >= 2:
        status = "At Risk"
    elif risk_count == 1:
        status = "Stable"
    else:
        status = "Healthy"

    # Deduplicate focus list
    focus = list(dict.fromkeys(focus))

    # Data freshness: timestamp of most recent AR snapshot row so EOS can detect stale
    # pipelines. Deliberately unscoped by the promoted KPI batch — that pointer is a
    # coarse, cross-table marker that isn't guaranteed to be re-promoted on every
    # import, so filtering by it here previously pinned this timestamp to whichever
    # batch was first ever promoted, making the freshness check itself always stale.
    data_freshness: str | None = None
    try:
        if _books_live():
            from src.services import books_analytics
            lp = books_analytics.data_counts().get("last_posting")
            data_freshness = _dt_to_str(lp) if lp else None
            raise StopIteration
        freshness_row = (
            db.table("sage_ar_snapshot")
            .select("imported_at")
            .order("imported_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if freshness_row:
            data_freshness = _dt_to_str(freshness_row[0].get("imported_at"))
    except (Exception, StopIteration):
        pass

    # Live data counts from populated Sage tables
    customer_count = 0
    inventory_sku_count = 0
    gl_transaction_count = 0
    prospect_count = 0
    try:
        cust_res = client.table("sage_customers_snapshot").select("customer_id").execute()
        customer_count = len(set(
            r.get("customer_id") for r in (cust_res.data or []) if r.get("customer_id")
        ))
    except Exception:
        pass
    try:
        items_res = client.table("sage_items_snapshot").select("item_id").execute()
        seen_skus: set = set()
        for r in (items_res.data or []):
            k = r.get("item_id") or ""
            if k:
                seen_skus.add(k)
        inventory_sku_count = len(seen_skus)
    except Exception:
        pass
    try:
        gl_res = client.table("sage_gl_detail_snapshot").select("id", count="exact").limit(1).execute()
        gl_transaction_count = gl_res.count or 0
    except Exception:
        pass
    try:
        prospect_res = client.table("crm_prospects").select("id").execute()
        prospect_count = len(prospect_res.data or [])
    except Exception:
        pass

    if _books_live():
        from src.services import books_analytics
        _c = books_analytics.data_counts()
        customer_count, inventory_sku_count, gl_transaction_count = _c["customers"], _c["products"], _c["gl_lines"]

    if customer_count > 0:
        status = "Stable" if status != "At Risk" else status

    return {
        "status": status,
        "key_findings": findings,
        "recommended_focus": focus,
        "data_freshness": data_freshness,
        "sources": ["analytics/kpis", "analytics/ar_trends", "ops/kpis", "hr/analytics/summary", "inventory"],
        "live_data": {
            "customer_count": customer_count,
            "inventory_sku_count": inventory_sku_count,
            "gl_transaction_count": gl_transaction_count,
            "prospect_count": prospect_count,
            "note": (
                f"Database contains {customer_count} customers, {inventory_sku_count} inventory SKUs, "
                f"{gl_transaction_count:,} GL journal entries, and {prospect_count} CRM prospects."
                + (
                    " AR/AP invoices not yet entered in Sage — revenue figures will show once invoices are recorded."
                    if finance.get("ar", {}).get("total_amount", 0) == 0
                    and finance.get("ap", {}).get("total_amount", 0) == 0
                    else (
                        f" {finance.get('ar', {}).get('overdue_count', 0):,} AR and "
                        f"{finance.get('ap', {}).get('overdue_count', 0):,} AP invoices overdue."
                    )
                )
            ),
        },
    }


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",), tags=("executive", "risk_signals"))
def risk_signals(client: DBClient = db) -> Dict[str, Any]:
    """Unified risk signals across Finance, CRM, Inventory, Ops, and HR."""
    risks: list[dict] = []

    # Finance: AR aging + overdue count
    aging = ar_aging_buckets(client)
    overdue_amt = float(aging.get("91_plus") or 0)
    if overdue_amt > 0:
        severity = "High" if overdue_amt >= 5_000_000 else "Medium" if overdue_amt >= 1_000_000 else "Low"
        risks.append({
            "domain": "Finance",
            "risk_type": "AR Aging (91+ days)",
            "severity": severity,
            "signal": f"₦{overdue_amt:,.0f} in 91+ day AR bucket.",
            "data_source": "reports/ar_aging",
        })
    finance = finance_kpis(client)
    if finance.get("ar", {}).get("overdue_count", 0) > 10:
        risks.append({
            "domain": "Finance",
            "risk_type": "Overdue Invoices",
            "severity": "Medium",
            "signal": f"{finance['ar']['overdue_count']} overdue AR invoices.",
            "data_source": "analytics/kpis",
        })

    # CRM: average risk score and high-risk customers
    crm = crm_risk_scores(client).get("customers", [])
    if crm:
        avg_risk = sum(float(c.get("risk_score") or 0) for c in crm) / len(crm)
        high_risk = [c for c in crm if float(c.get("risk_score") or 0) >= 70]
        if avg_risk >= 60:
            risks.append({
                "domain": "CRM",
                "risk_type": "Pipeline Fragility",
                "severity": "High" if avg_risk >= 80 else "Medium",
                "signal": f"Average CRM risk score is {avg_risk:.1f}.",
                "data_source": "crm/risk_scores",
            })
        if high_risk:
            risks.append({
                "domain": "CRM",
                "risk_type": "High-Risk Accounts",
                "severity": "Medium",
                "signal": f"{len(high_risk)} accounts with risk score ≥ 70.",
                "data_source": "crm/risk_scores",
            })

    # Inventory: low stock and out-of-stock alerts
    inv = get_inventory_summary(limit=100, client=client)
    low_stock = [i for i in inv if i.get("current_stock", 0) < 10]
    out_stock = [i for i in inv if i.get("current_stock", 0) <= 0]
    if out_stock:
        risks.append({
            "domain": "Inventory",
            "risk_type": "Stockouts",
            "severity": "High",
            "signal": f"{len(out_stock)} SKUs out of stock.",
            "data_source": "dashboard/inventory",
        })
    if low_stock:
        risks.append({
            "domain": "Inventory",
            "risk_type": "Low Stock",
            "severity": "Medium" if len(low_stock) >= 10 else "Low",
            "signal": f"{len(low_stock)} SKUs below reorder threshold.",
            "data_source": "dashboard/inventory",
        })

    # Operations: downtime and fulfillment delays
    ops = ops_kpis(client)
    if ops.get("downtime_minutes_total", 0) > 500:
        risks.append({
            "domain": "Ops",
            "risk_type": "Downtime Spike",
            "severity": "High" if ops["downtime_minutes_total"] > 2000 else "Medium",
            "signal": f"Total downtime {ops['downtime_minutes_total']:.0f} minutes.",
            "data_source": "ops/kpis",
        })
    if ops.get("fulfillment_days_avg", 0) > 5:
        risks.append({
            "domain": "Ops",
            "risk_type": "Fulfillment Delays",
            "severity": "Medium",
            "signal": f"Average fulfillment time {ops['fulfillment_days_avg']:.1f} days.",
            "data_source": "ops/kpis",
        })

    # HR: absence and overtime
    hr = payroll_and_absence_summary(client=client, periods=3)
    if hr.get("overtime_pct_payroll", 0) > 0.15:
        risks.append({
            "domain": "HR",
            "risk_type": "Overtime Pressure",
            "severity": "Medium",
            "signal": f"Overtime cost is {hr['overtime_pct_payroll']*100:.1f}% of payroll.",
            "data_source": "hr/analytics/summary",
        })
    abs_trend = hr.get("absenteeism_trend", [])
    if len(abs_trend) >= 2:
        prev = float(abs_trend[-2].get("hours") or 0)
        curr = float(abs_trend[-1].get("hours") or 0)
        change_pct = compute_change_pct(curr, prev)
        if change_pct > 0.1:
            risks.append({
                "domain": "HR",
                "risk_type": "Absence Spike",
                "severity": "Low" if change_pct < 0.2 else "Medium",
                "signal": f"Absence hours up {change_pct*100:.1f}% period-over-period.",
                "data_source": "hr/analytics/summary",
            })

    return {"risks": risks}


def opportunities_from_risks(risks: list[dict]) -> list[dict]:
    """Pair opportunity insights with risks using deterministic mappings."""
    out: list[dict] = []
    for r in risks:
        rtype = (r.get("risk_type") or "").lower()
        domain = (r.get("domain") or "").lower()
        opportunity = None
        confidence = "Medium"

        if domain == "finance" and "aging" in rtype:
            opportunity = "Offer early payment incentives or retainer terms to accelerate collections."
            confidence = "High"
        elif domain == "finance" and "overdue" in rtype:
            opportunity = "Prioritize high‑balance accounts and negotiate structured repayment plans."
            confidence = "Medium"
        elif domain == "crm" and "pipeline" in rtype:
            opportunity = "Rebalance pipeline with upsell/renewal focus and tighten stage exit criteria."
            confidence = "Medium"
        elif domain == "crm" and "accounts" in rtype:
            opportunity = "Target at‑risk accounts with retention offers and value reinforcement."
            confidence = "Medium"
        elif domain == "inventory" and "stockout" in rtype:
            opportunity = "Bundle substitutes or promote alternative SKUs to protect revenue."
            confidence = "High"
        elif domain == "inventory" and "low stock" in rtype:
            opportunity = "Trigger selective reorder and adjust safety stock for high‑velocity items."
            confidence = "High"
        elif domain == "ops" and "downtime" in rtype:
            opportunity = "Prioritize preventive maintenance and automate high‑failure steps."
            confidence = "Medium"
        elif domain == "ops" and "fulfillment" in rtype:
            opportunity = "Streamline pick‑pack workflows and rebalance labor by demand peaks."
            confidence = "Medium"
        elif domain == "hr" and "overtime" in rtype:
            opportunity = "Redesign shifts or introduce tooling to reduce overtime burden."
            confidence = "Medium"
        elif domain == "hr" and "absence" in rtype:
            opportunity = "Cross‑train teams and improve leave planning to protect coverage."
            confidence = "Low"

        if opportunity:
            out.append({
                "risk": r.get("risk_type"),
                "opportunity": opportunity,
                "confidence": confidence,
            })
    return out


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",), tags=("executive", "recommendations"))
def recommendations(client: DBClient = db) -> Dict[str, Any]:
    """Rule-based recommendations derived from existing analytics."""
    recs: list[dict] = []

    # Finance: AR aging and overdue
    aging = ar_aging_buckets(client)
    overdue_amt = float(aging.get("91_plus") or 0)
    if overdue_amt > 0:
        recs.append({
            "action": "Launch focused collections on 91+ day AR balances.",
            "reason": f"₦{overdue_amt:,.0f} sits in the 91+ day bucket, raising cashflow risk.",
            "data_source": "reports/ar_aging",
            "confidence": "High",
        })

    finance = finance_kpis(client)
    if finance.get("ar", {}).get("overdue_count", 0) > 10:
        recs.append({
            "action": "Segment overdue accounts and assign repayment plans.",
            "reason": f"{finance['ar']['overdue_count']} invoices are overdue.",
            "data_source": "analytics/kpis",
            "confidence": "Medium",
        })

    # Inventory: low stock
    inv = get_inventory_summary(limit=100, client=client)
    low_stock = [i for i in inv if i.get("current_stock", 0) < 10]
    out_stock = [i for i in inv if i.get("current_stock", 0) <= 0]
    if out_stock:
        recs.append({
            "action": "Prioritize replenishment for out‑of‑stock SKUs.",
            "reason": f"{len(out_stock)} SKUs are currently out of stock.",
            "data_source": "dashboard/inventory",
            "confidence": "High",
        })
    if low_stock:
        recs.append({
            "action": "Review reorder points for low‑stock items.",
            "reason": f"{len(low_stock)} SKUs are below threshold.",
            "data_source": "dashboard/inventory",
            "confidence": "Medium",
        })

    # Ops: downtime and fulfillment
    ops = ops_kpis(client)
    if ops.get("downtime_minutes_total", 0) > 500:
        recs.append({
            "action": "Schedule preventive maintenance on high‑downtime assets.",
            "reason": f"Total downtime is {ops['downtime_minutes_total']:.0f} minutes.",
            "data_source": "ops/kpis",
            "confidence": "Medium",
        })
    if ops.get("fulfillment_days_avg", 0) > 5:
        recs.append({
            "action": "Optimize pick‑pack workflows to reduce fulfillment time.",
            "reason": f"Average fulfillment time is {ops['fulfillment_days_avg']:.1f} days.",
            "data_source": "ops/kpis",
            "confidence": "Medium",
        })

    # HR: overtime and absences
    hr = payroll_and_absence_summary(client=client, periods=3)
    if hr.get("overtime_pct_payroll", 0) > 0.15:
        recs.append({
            "action": "Rebalance shifts or automate repetitive tasks to reduce overtime.",
            "reason": f"Overtime is {hr['overtime_pct_payroll']*100:.1f}% of payroll.",
            "data_source": "hr/analytics/summary",
            "confidence": "Medium",
        })
    abs_trend = hr.get("absenteeism_trend", [])
    if len(abs_trend) >= 2:
        prev = float(abs_trend[-2].get("hours") or 0)
        curr = float(abs_trend[-1].get("hours") or 0)
        change_pct = compute_change_pct(curr, prev)
        if change_pct > 0.1:
            recs.append({
                "action": "Improve leave planning and cross‑training to protect coverage.",
                "reason": f"Absence hours increased {change_pct*100:.1f}% period‑over‑period.",
                "data_source": "hr/analytics/summary",
                "confidence": "Low" if change_pct < 0.2 else "Medium",
            })

    return {"recommendations": recs}


def _zscore(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = var ** 0.5 if var > 0 else 0.0
    if std == 0:
        return [0.0 for _ in values]
    return [(v - mean) / std for v in values]


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",), tags=("executive", "anomalies"))
def anomaly_signals(client: DBClient = db) -> Dict[str, Any]:
    """Explainable anomaly detection using z-scores on existing series."""
    anomalies: list[dict] = []

    # AR balance series
    ar_series = ar_trend_summary(client=client, periods=12).get("periods", [])
    ar_vals = [float(p.get("balance") or 0) for p in ar_series]
    ar_z = _zscore(ar_vals)
    if ar_z and abs(ar_z[-1]) >= 2:
        anomalies.append({
            "domain": "Finance",
            "signal": "AR balance anomaly",
            "zscore": ar_z[-1],
            "detail": f"Latest AR balance deviates by {ar_z[-1]:.2f}σ.",
            "data_source": "analytics/ar_trends",
        })

    # HR absence series
    hr = payroll_and_absence_summary(client=client, periods=12)
    abs_series = hr.get("absenteeism_trend", [])
    abs_vals = [float(p.get("hours") or 0) for p in abs_series]
    abs_z = _zscore(abs_vals)
    if abs_z and abs(abs_z[-1]) >= 2:
        anomalies.append({
            "domain": "HR",
            "signal": "Absence anomaly",
            "zscore": abs_z[-1],
            "detail": f"Latest absence hours deviate by {abs_z[-1]:.2f}σ.",
            "data_source": "hr/analytics/summary",
        })

    # Ops downtime series
    downtime_rows = client.table("ops_downtime_snapshot").select("minutes,imported_at").order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute().data or []
    buckets: dict[str, float] = {}
    for r in downtime_rows:
        k = _dt_to_str(r.get("imported_at"))[:7]
        if not k:
            continue
        buckets[k] = buckets.get(k, 0.0) + float(r.get("minutes") or 0)
    months = sorted(buckets.keys())[-12:]
    down_vals = [buckets[m] for m in months]
    down_z = _zscore(down_vals)
    if down_z and abs(down_z[-1]) >= 2:
        anomalies.append({
            "domain": "Ops",
            "signal": "Downtime anomaly",
            "zscore": down_z[-1],
            "detail": f"Latest downtime deviates by {down_z[-1]:.2f}σ.",
            "data_source": "ops/kpis",
        })

    return {"anomalies": anomalies}
