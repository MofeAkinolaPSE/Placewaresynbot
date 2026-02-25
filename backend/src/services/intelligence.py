from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from supabase import Client
import json

from ..db import supabase
from ..constants import TABLE_ALERTS, TABLE_BRIEFINGS
from ..cache import ttl_cache
from .sage_adapter.service import kpis as finance_kpis, ar_trend_summary, ar_aging_buckets
from .inventory import get_inventory_summary, get_latest_batch_sku_count, get_recent_inventory_movements
from .ops import kpis as ops_kpis, stock_turnover_series
from .hr import payroll_and_absence_summary
from .crm import risk_scores as crm_risk_scores
from .staff_ops import get_timesheets
from .sage_adapter.service import get_sage_kpi_batch_id

logger = logging.getLogger("intelligence")

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

@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",))
def get_inventory_dashboard(limit: int = 50, client: Client = supabase) -> Dict[str, Any]:
    """
    Inventory Health Check:
    - Low stock items
    - Recent movements
    - Coverage risk
    """
    summary = get_inventory_summary(limit=100, client=client)
    total_active_skus = get_latest_batch_sku_count(client=client)
    
    low_stock = [i for i in summary if i['current_stock'] < 10] # Configurable threshold?
    out_of_stock = [i for i in summary if i['current_stock'] <= 0]
    
    recent_movements = get_recent_inventory_movements(limit=limit, client=client)

    return {
        "summary": {
            "total_active_skus": total_active_skus if total_active_skus > 0 else len(summary),
            "low_stock_count": len(low_stock),
            "out_of_stock_count": len(out_of_stock),
        },
        "critical_items": low_stock[:limit],
        "recent_movements": recent_movements,
    }

@ttl_cache(ttl_seconds=600, ignore_kwargs=("client",))
def get_workforce_dashboard(client: Client = supabase) -> Dict[str, Any]:
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
    
    # Fallback: If no timesheets logged (Phase 2), show total registered staff (Phase 1)
    if active_count == 0:
        try:
            sage_batch_id = get_sage_kpi_batch_id()
            # Get count
            staff_q = client.table("sage_staff_snapshot").select("*", count="exact")
            if sage_batch_id:
                staff_q = staff_q.eq("batch_id", sage_batch_id)
            staff_resp = staff_q.limit(1).execute()
            if staff_resp.count > 0:
                active_count = staff_resp.count
            
            # Get breakdown by department for chart fallback
            # We can't do GROUP BY via API easily without RPC, so we fetch all staff departments
            all_staff_q = client.table("sage_staff_snapshot").select("department")
            if sage_batch_id:
                all_staff_q = all_staff_q.eq("batch_id", sage_batch_id)
            all_staff = all_staff_q.limit(1000).execute()
            for s in all_staff.data:
                d = s.get("department") or "Unassigned"
                # Use hours=1 per person as proxy for "headcount" in the chart
                dept_hours[d] = dept_hours.get(d, 0) + 1
                
        except Exception as e:
            logger.warning(f"Workforce fallback failed: {e}")
            pass 

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
    client: Client = supabase
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

@ttl_cache(ttl_seconds=30, ignore_kwargs=("client",))
def get_active_alerts(client: Client = supabase) -> List[Dict[str, Any]]:
    return client.table(TABLE_ALERTS)\
        .select("*")\
        .eq("status", "unread")\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute().data or []

# --- Executive Briefing Engine ---

@ttl_cache(ttl_seconds=300, ignore_kwargs=("client",))
def generate_executive_briefing(client: Client = supabase) -> Dict[str, Any]:
    """
    Holistic Business Summary.
    Combines Finance, Inventory, and Ops into a single JSON report.
    """
    # 1. Gather Data
    finance = finance_kpis(client)
    inventory = get_inventory_dashboard(limit=5, client=client)
    workforce = get_workforce_dashboard(client=client)
    alerts = get_active_alerts(client=client)
    
    # 2. Synthesize Insights (Deterministic)
    critical_risks = []
    if finance['ar']['overdue_count'] > 5:
        critical_risks.append("High volume of overdue AR invoices.")
    if inventory['summary']['out_of_stock_count'] > 0:
        critical_risks.append(f"{inventory['summary']['out_of_stock_count']} critical SKUs out of stock.")
    
    briefing = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "health_score": "Requires Attention" if critical_risks else "Stable",
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
        "latest_alerts": [a['title'] for a in alerts[:3]]
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


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",))
def executive_summary(client: Client = supabase) -> Dict[str, Any]:
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
    if finance.get("ar", {}).get("overdue_count", 0) > 5:
        findings.append("Overdue AR invoices are elevated.")
        focus.append("Collections")
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
        k = (r.get("imported_at") or "")[:7]
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

    return {
        "status": status,
        "key_findings": findings,
        "recommended_focus": focus,
        "sources": ["analytics/kpis", "analytics/ar_trends", "ops/kpis", "hr/analytics/summary", "inventory"],
    }


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",))
def risk_signals(client: Client = supabase) -> Dict[str, Any]:
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


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",))
def recommendations(client: Client = supabase) -> Dict[str, Any]:
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


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",))
def anomaly_signals(client: Client = supabase) -> Dict[str, Any]:
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
        k = (r.get("imported_at") or "")[:7]
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
