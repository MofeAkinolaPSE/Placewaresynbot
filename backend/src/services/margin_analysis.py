"""
Margin Driver Analysis Service

Decomposes overall margin compression into named cost drivers by grouping
GL account codes into business-meaningful buckets and computing month-over-month
change per driver relative to the revenue base.

Public API:
    margin_driver_report(client=db) -> dict
        Returns {
            overall_margin_pct: float,
            total_revenue: float,
            total_cost: float,
            top_drivers: list[DriverResult],
            all_drivers: list[DriverResult],
            last_updated: str | None,
        }

    DriverResult structure:
        {name, account_range, cost, pct_of_revenue, mom_change_pct, trend, severity}
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from typing import Any as DBClient

from src.cache import ttl_cache
from src.db import db
from src.services.sage_adapter.service import get_sage_kpi_batch_id
from src.services.intelligence import compute_change_pct, trend_label

logger = logging.getLogger(__name__)


def _dt_to_str(val: object) -> str:
    """Coerce psycopg2 datetime/date to ISO string; passthrough for str/None."""
    if val is None:
        return ""
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# GL account-code buckets that map to named cost drivers
# ---------------------------------------------------------------------------
COST_DRIVER_BUCKETS: List[Dict[str, Any]] = [
    {
        "name": "Cost of Goods Sold",
        "short": "COGS",
        "min": 5000,
        "max": 5099,
        "description": "Direct product / vaccine acquisition cost",
    },
    {
        "name": "Cold-Chain & Logistics",
        "short": "Cold-Chain",
        "min": 5100,
        "max": 5299,
        "description": "Cold-storage, distribution, and last-mile delivery costs",
    },
    {
        "name": "Salaries & Workforce",
        "short": "Workforce",
        "min": 6100,
        "max": 6199,
        "description": "Payroll, benefits, and staff-related expenses",
    },
    {
        "name": "Quality Assurance & Compliance",
        "short": "QA/Compliance",
        "min": 6400,
        "max": 6499,
        "description": "NAFDAC fees, QA processes, regulatory compliance costs",
    },
    {
        "name": "General Overheads",
        "short": "Overheads",
        "min": 6500,
        "max": 6999,
        "description": "Admin, utilities, rent, and other operating overheads",
    },
    {
        "name": "Other Costs",
        "short": "Other",
        "min": 5300,
        "max": 6099,
        "description": "Remaining cost accounts not classified above",
    },
]

REVENUE_MIN = 4000
REVENUE_MAX = 4999


def _severity(pct_of_revenue: float, mom_change_pct: float) -> str:
    """Rate driver severity: high / medium / low."""
    if pct_of_revenue > 40 or (mom_change_pct > 0.15 and pct_of_revenue > 15):
        return "high"
    if pct_of_revenue > 20 or mom_change_pct > 0.10:
        return "medium"
    return "low"


def _account_code_to_int(code: Any) -> int | None:
    """Parse account code to int. Handles ACC-4001, 4001, 4001-01 formats."""
    try:
        m = re.search(r'\d+', str(code))
        return int(m.group()) if m else None
    except (ValueError, TypeError):
        return None


def _bucket_for_code(code_int: int) -> str | None:
    for bucket in COST_DRIVER_BUCKETS:
        if bucket["min"] <= code_int <= bucket["max"]:
            return bucket["name"]
    return None


@ttl_cache(ttl_seconds=600, ignore_kwargs=("client",), tags=("finance", "margin_drivers"))
def margin_driver_report(client: DBClient = db) -> Dict[str, Any]:
    """Decompose overall margin into named GL-bucket cost drivers with MoM trend.

    Returns overall_margin_pct, top 3 compression drivers, and full driver list.
    """
    from src.services.sage_adapter.service import _latest_batch_for_table
    gl_batch = get_sage_kpi_batch_id() or _latest_batch_for_table("sage_gl_snapshot", client)

    gl_q = client.table("sage_gl_snapshot").select("period,account_code,account_name,debit,credit")
    if gl_batch:
        gl_q = gl_q.eq("batch_id", gl_batch)
    gl_rows = gl_q.limit(50000).execute().data or []

    if not gl_rows:
        return {
            "overall_margin_pct": 0.0,
            "total_revenue": 0.0,
            "total_cost": 0.0,
            "top_drivers": [],
            "all_drivers": [],
            "last_updated": None,
            "_no_data": True,
        }

    # Aggregate by period × driver bucket
    # driver_period[period][driver_name] = {cost, revenue}
    driver_period: Dict[str, Dict[str, float]] = {}  # {driver_name: {period: cost}}
    total_revenue_by_period: Dict[str, float] = {}
    total_cost_by_driver: Dict[str, float] = {}

    for row in gl_rows:
        code = _account_code_to_int(row.get("account_code"))
        if code is None:
            continue
        period = _dt_to_str(row.get("period") or "unknown")[:7]
        debit = float(row.get("debit") or 0)
        credit = float(row.get("credit") or 0)

        # Revenue
        if REVENUE_MIN <= code <= REVENUE_MAX:
            total_revenue_by_period[period] = total_revenue_by_period.get(period, 0.0) + (credit - debit)
            continue

        # Cost bucketing
        driver = _bucket_for_code(code)
        if driver is None:
            continue
        total_cost_by_driver[driver] = total_cost_by_driver.get(driver, 0.0) + (debit - credit)
        period_map = driver_period.setdefault(driver, {})
        period_map[period] = period_map.get(period, 0.0) + (debit - credit)

    total_revenue = max(sum(total_revenue_by_period.values()), 0.0)
    total_cost = max(sum(total_cost_by_driver.values()), 0.0)
    overall_margin_pct = (
        round((total_revenue - total_cost) / total_revenue * 100, 2) if total_revenue > 0 else 0.0
    )

    # Build driver results with MoM change
    all_periods_sorted = sorted(total_revenue_by_period.keys())
    results: List[Dict[str, Any]] = []

    for bucket in COST_DRIVER_BUCKETS:
        name = bucket["name"]
        cost = max(total_cost_by_driver.get(name, 0.0), 0.0)
        pct = round(cost / total_revenue * 100, 2) if total_revenue > 0 else 0.0

        # MoM: compare last two periods for this driver
        mom_change = 0.0
        period_costs = driver_period.get(name, {})
        if len(all_periods_sorted) >= 2:
            prev_p, curr_p = all_periods_sorted[-2], all_periods_sorted[-1]
            prev_cost = period_costs.get(prev_p, 0.0)
            curr_cost = period_costs.get(curr_p, 0.0)
            mom_change = compute_change_pct(curr_cost, prev_cost)

        t_label = trend_label(mom_change, positive_is_good=False)  # rising cost = bad

        results.append({
            "name": name,
            "short": bucket["short"],
            "account_range": f"{bucket['min']}–{bucket['max']}",
            "description": bucket["description"],
            "cost": round(cost, 2),
            "pct_of_revenue": pct,
            "mom_change_pct": round(mom_change * 100, 2),  # as percentage points
            "trend": t_label,
            "severity": _severity(pct, mom_change) if cost > 0 else "low",
        })

    # Sort by pct_of_revenue desc — biggest compressors first
    results.sort(key=lambda x: -x["pct_of_revenue"])

    # Top 3 non-zero drivers
    top_drivers = [r for r in results if r["cost"] > 0][:3]

    # Last updated from most recent GL row imported_at (not in this query — use batch_id time proxy)
    last_updated: str | None = None
    try:
        lu_q = client.table("sage_gl_snapshot").select("imported_at").order("imported_at", desc=True).limit(1)
        if gl_batch:
            lu_q = lu_q.eq("batch_id", gl_batch)
        lu_rows = lu_q.execute().data
        if lu_rows:
            last_updated = lu_rows[0].get("imported_at")
    except Exception:
        pass

    return {
        "overall_margin_pct": overall_margin_pct,
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "top_drivers": top_drivers,
        "all_drivers": results,
        "last_updated": last_updated,
    }
