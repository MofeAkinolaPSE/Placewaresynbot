"""qc.py — Quality Control summary aggregation.

Extracted from routers/qc.py's qc_dashboard() handler so the new ACE
Workstation aggregator (services/intelligence.py's get_workstation_summary())
can call it directly instead of duplicating these 5 queries -- QC was
previously the only domain in this app with no service module of its own.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict
from typing import Any as DBClient

from ..db import db
from .inventory import get_expiring_inventory

logger = logging.getLogger("qc")


def get_qc_summary(client: DBClient = db) -> Dict[str, Any]:
    """
    Returns a single payload with all QC KPIs for the dashboard overview tab.
    Runs 5 lightweight queries in sequence; failures are soft (return 0).
    """
    today_start = dt.datetime.combine(dt.date.today(), dt.time.min).isoformat() + "Z"
    today_end   = dt.datetime.combine(dt.date.today(), dt.time.max).isoformat() + "Z"

    # 1. Products expiring within 30 days
    expiring_critical = 0
    try:
        exp = get_expiring_inventory(thresholds=[90, 60, 30], client=client)
        expiring_critical = sum(
            1 for i in (exp.get("items") or []) if i.get("tier") == "critical"
        )
    except Exception as exc:
        logger.warning("Expiry KPI error: %s", exc)

    # 2. Open deviation reports
    open_deviations = 0
    try:
        r = (client.table("deviation_reports")
             .select("id", count="exact")
             .in_("status", ["open", "under_investigation"])
             .execute())
        open_deviations = r.count or len(r.data or [])
    except Exception as exc:
        logger.warning("Deviation KPI error: %s", exc)

    # 3. Temperature deviations today
    temp_alerts_today = 0
    try:
        r = (client.table("temperature_logs")
             .select("id", count="exact")
             .eq("is_deviation", True)
             .gte("logged_at", today_start)
             .lte("logged_at", today_end)
             .execute())
        temp_alerts_today = r.count or len(r.data or [])
    except Exception as exc:
        logger.warning("Temperature KPI error: %s", exc)

    # 4. NAFDAC batches pending approval
    nafdac_pending = 0
    try:
        r = (client.table("nafdac_batch_registry")
             .select("id", count="exact")
             .eq("status", "pending")
             .execute())
        nafdac_pending = r.count or len(r.data or [])
    except Exception as exc:
        logger.warning("NAFDAC KPI error: %s", exc)

    # 5. Open recall cases
    open_recalls = 0
    try:
        r = (client.table("recall_cases")
             .select("id", count="exact")
             .in_("status", ["initiated", "in_progress"])
             .execute())
        open_recalls = r.count or len(r.data or [])
    except Exception as exc:
        logger.warning("Recall KPI error: %s", exc)

    # 6. Recent deviations (last 5) for activity feed
    recent_deviations: list[dict] = []
    try:
        r = (client.table("deviation_reports")
             .select("id,deviation_id,classification,trigger_type,status,observation,created_at")
             .order("created_at", desc=True)
             .limit(5)
             .execute())
        recent_deviations = r.data or []
    except Exception:
        pass

    return {
        "expiring_critical_30d": expiring_critical,
        "open_deviations":       open_deviations,
        "temp_alerts_today":     temp_alerts_today,
        "nafdac_pending":        nafdac_pending,
        "open_recalls":          open_recalls,
        "recent_deviations":     recent_deviations,
    }
