from __future__ import annotations

from typing import Dict, Any
from supabase import Client
from ..db import supabase
from ..cache import ttl_cache


MAX_ANALYTICS_ROWS = 3000


@ttl_cache(ttl_seconds=180, ignore_kwargs=("client",))
def payroll_and_absence_summary(client: Client = supabase, periods: int = 3) -> Dict[str, Any]:
    """Compute HR analytics with deterministic formulas.

    - salary_total: sum(salary)
    - overtime_cost_total: sum(overtime_hours * overtime_rate)
    - overtime_pct_payroll: overtime_cost_total / (salary_total + overtime_cost_total)
    - avg_cost_per_employee: (salary_total + overtime_cost_total) / distinct_employees
    - absenteeism_trend: hours absent grouped by most recent N months
    """
    # Payroll
    p = client.table("hr_payroll_snapshot").select("employee_id,salary,overtime_hours,overtime_rate").order("imported_at", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    rows = p.data or []
    salary_total = sum(float(r.get("salary") or 0) for r in rows)
    overtime_cost_total = sum(float(r.get("overtime_hours") or 0) * float(r.get("overtime_rate") or 0) for r in rows)
    employees = {r.get("employee_id") for r in rows if r.get("employee_id")}
    denom = max(1, len(employees))
    payroll_total = salary_total + overtime_cost_total
    overtime_pct = (overtime_cost_total / payroll_total) if payroll_total > 0 else 0.0
    avg_cost_per_emp = payroll_total / denom if denom > 0 else 0.0

    # Absences by month
    a = client.table("hr_absence_snapshot").select("date,hours").order("date", desc=True).limit(MAX_ANALYTICS_ROWS).execute()
    abs_rows = a.data or []
    buckets: Dict[str, float] = {}
    for r in abs_rows:
        d = (r.get("date") or "")[:7]  # YYYY-MM
        if not d:
            continue
        buckets[d] = buckets.get(d, 0.0) + float(r.get("hours") or 0)
    # Most recent N periods
    periods_keys = sorted(buckets.keys(), reverse=True)[:periods]
    trend = [{"period": k, "hours": buckets[k]} for k in periods_keys]

    explain = {
        "salary_total": "sum(salary)",
        "overtime_cost_total": "sum(overtime_hours * overtime_rate)",
        "overtime_pct_payroll": "overtime_cost_total / (salary_total + overtime_cost_total)",
        "avg_cost_per_employee": "(salary_total + overtime_cost_total) / distinct_employees",
        "absenteeism_trend": "group by YYYY-MM: sum(hours)",
        "sources": ["hr_payroll_snapshot", "hr_absence_snapshot"],
    }
    return {
        "salary_total": salary_total,
        "overtime_cost_total": overtime_cost_total,
        "overtime_pct_payroll": overtime_pct,
        "avg_cost_per_employee": avg_cost_per_emp,
        "absenteeism_trend": trend,
        "explain": explain,
    }
