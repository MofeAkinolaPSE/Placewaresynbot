"""
Weekly Report Scheduler — ACE
=======================================
Runs a background thread that fires every Monday at 08:00 WAT (UTC+1).
Generates the current week's sales report and emails it to the configured
management recipients.

Environment variables:
  WEEKLY_REPORT_RECIPIENTS  — comma-separated email list
                              e.g. "md@placeware.ng,sales@placeware.ng"
  EMAIL_FROM                — Gmail address to send from
  EMAIL_PASS                — Gmail App Password
  WEEKLY_REPORT_ENABLED     — set to "0" to disable (default enabled)
"""

from __future__ import annotations

import logging
import os
import threading
import time
import datetime as dt

logger = logging.getLogger(__name__)

_WAT_OFFSET = dt.timedelta(hours=1)   # West Africa Time = UTC+1
_SEND_HOUR  = 8                         # 08:00 WAT

# File-based exclusive lock — ensures only one uvicorn worker runs the scheduler
# when the app starts with --workers N. The lock is held for the process lifetime;
# it is released automatically when the process exits.
_SCHEDULER_LOCK_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "placeware_scheduler.lock")
_scheduler_lock_fd = None


def _next_monday_8am() -> float:
    """Return the UTC timestamp of the next Monday at 08:00 WAT."""
    now_utc = dt.datetime.utcnow()
    now_wat = now_utc + _WAT_OFFSET
    # Find next Monday
    days_ahead = (7 - now_wat.weekday()) % 7  # Monday = 0
    if days_ahead == 0 and now_wat.hour >= _SEND_HOUR:
        days_ahead = 7  # already past this Monday's send time → next Monday
    target_wat = now_wat.replace(
        hour=_SEND_HOUR, minute=0, second=0, microsecond=0
    ) + dt.timedelta(days=days_ahead)
    target_utc = target_wat - _WAT_OFFSET
    return target_utc.timestamp()


def _generate_and_email_report() -> None:
    """Core task: generate this week's report and email it to management."""
    recipients_raw = os.getenv("WEEKLY_REPORT_RECIPIENTS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients:
        logger.info("Weekly report scheduler: no recipients configured — skipping email.")
        return

    logger.info("Weekly report scheduler: generating report for emailing to %s", recipients)

    # ── Generate report data ───────────────────────────────────────────────
    report_data: dict = {}
    try:
        from src.db import db
        from src.routers.crm_sales import PIPELINE_STAGES

        today = dt.date.today()
        ws = today - dt.timedelta(days=today.weekday())
        we = ws + dt.timedelta(days=6)
        ws_dt = dt.datetime.combine(ws, dt.time.min).isoformat() + "Z"
        we_dt = dt.datetime.combine(we, dt.time.max).isoformat() + "Z"

        # Try extended cols, fall back gracefully
        try:
            nl_resp = (
                db.table("leads")
                .select("id,stage,expected_value,assigned_rep,company_name,product_interest")
                .gte("created_at", ws_dt).lte("created_at", we_dt).execute()
            )
        except Exception as _c:
            if "does not exist" in str(_c).lower():
                nl_resp = (
                    db.table("leads")
                    .select("id,stage,expected_value,assigned_rep")
                    .gte("created_at", ws_dt).lte("created_at", we_dt).execute()
                )
            else:
                raise
        new_leads = nl_resp.data or []

        active_leads = (
            db.table("leads").select("id,stage,expected_value")
            .not_.in_("stage", ["won", "lost"]).execute().data or []
        )
        won_leads  = (db.table("leads").select("id,expected_value").eq("stage", "won").gte("updated_at", ws_dt).lte("updated_at", we_dt).execute().data or [])
        lost_leads = (db.table("leads").select("id").eq("stage", "lost").gte("updated_at", ws_dt).lte("updated_at", we_dt).execute().data or [])

        stage_counts: dict = {s: 0 for s in PIPELINE_STAGES}
        for l in active_leads:
            s = str(l.get("stage") or "new")
            if s in stage_counts:
                stage_counts[s] += 1

        product_freq: dict = {}
        rep_activity: dict = {}
        for l in new_leads:
            for p in (l.get("product_interest") or []):
                product_freq[p] = product_freq.get(p, 0) + 1
            rep = str(l.get("assigned_rep") or "unassigned")
            rep_activity[rep] = rep_activity.get(rep, 0) + 1

        report_data = {
            "week_start":      ws.isoformat(),
            "week_end":        we.isoformat(),
            "new_leads_count": len(new_leads),
            "active_leads":    len(active_leads),
            "won_count":       len(won_leads),
            "lost_count":      len(lost_leads),
            "pipeline_value":  round(sum(float(l.get("expected_value") or 0) for l in active_leads), 2),
            "won_value":       round(sum(float(l.get("expected_value") or 0) for l in won_leads), 2),
            "stage_breakdown": stage_counts,
            "top_products":    sorted(product_freq.items(), key=lambda x: -x[1])[:10],
            "rep_activity":    rep_activity,
            "generated_at":    dt.datetime.utcnow().isoformat() + "Z",
        }
    except Exception as exc:
        logger.error("Scheduler: report generation failed: %s", exc)
        return

    # ── Build email body ───────────────────────────────────────────────────
    def currency(v: float) -> str:
        return f"\u20a6{v / 1_000_000:.2f}M" if v >= 1_000_000 else f"\u20a6{v / 1_000:.1f}k"

    top_products_text = "\n".join(
        f"  - {p} (x{c})" for p, c in report_data["top_products"][:5]
    ) or "  None recorded"
    rep_activity_text = "\n".join(
        f"  - {r}: {c} leads" for r, c in sorted(report_data["rep_activity"].items(), key=lambda x: -x[1])[:5]
    ) or "  No activity"

    body = f"""
Weekly Sales Performance Report
Period: {report_data['week_start']} to {report_data['week_end']}

KEY METRICS
-----------
New Leads (this week): {report_data['new_leads_count']}
Active Leads:          {report_data['active_leads']}
Deals Won:             {report_data['won_count']} ({currency(report_data['won_value'])} won value)
Deals Lost:            {report_data['lost_count']}
Pipeline Value:        {currency(report_data['pipeline_value'])}

TOP PRODUCTS OF INTEREST
------------------------
{top_products_text}

REP ACTIVITY
------------
{rep_activity_text}

---
Generated automatically by ACE at {report_data['generated_at'][:19]} UTC.
Confidential — for authorised personnel only.
""".strip()

    subject = f"[ACE] Weekly Sales Report — {report_data['week_start']} to {report_data['week_end']}"

    # ── Send emails ────────────────────────────────────────────────────────
    try:
        from src.services.messaging import send_email
        for recipient in recipients:
            try:
                send_email(recipient, subject, body)
                logger.info("Weekly report emailed to %s", recipient)
            except Exception as email_exc:
                logger.error("Failed to email weekly report to %s: %s", recipient, email_exc)
    except Exception as exc:
        logger.error("Scheduler: messaging import failed: %s", exc)


def _scheduler_loop() -> None:
    """Main scheduler loop — sleeps until next Monday 8am WAT, then fires."""
    logger.info("Weekly report scheduler started.")
    while True:
        next_run = _next_monday_8am()
        now = time.time()
        sleep_seconds = max(60.0, next_run - now)
        next_run_dt = dt.datetime.utcfromtimestamp(next_run)
        logger.info(
            "Weekly report scheduler: next run at %s UTC (in %.1f hours)",
            next_run_dt.isoformat(),
            sleep_seconds / 3600,
        )

        # Sleep in 60-second intervals to allow clean shutdown
        elapsed = 0.0
        while elapsed < sleep_seconds:
            time.sleep(min(60.0, sleep_seconds - elapsed))
            elapsed += 60.0

        # Double-check it's still roughly Monday 8am WAT (drift protection)
        now_wat = dt.datetime.utcnow() + _WAT_OFFSET
        if now_wat.weekday() == 0 and now_wat.hour in (8, 9):
            try:
                _generate_and_email_report()
            except Exception as exc:
                logger.error("Weekly report scheduler: unhandled error: %s", exc)
        else:
            logger.info("Scheduler: skipping fire (not Monday morning WAT). Will recalculate.")


def start_scheduler() -> None:
    """
    Start the weekly report email scheduler in a daemon background thread.
    Uses a file-based exclusive lock so only one uvicorn worker process
    runs the scheduler when the app starts with --workers N.
    """
    global _scheduler_lock_fd

    if os.getenv("WEEKLY_REPORT_ENABLED", "1") in ("0", "false", "False"):
        logger.info("Weekly report scheduler disabled (WEEKLY_REPORT_ENABLED=0)")
        return

    # Acquire exclusive lock — non-blocking. Workers that lose the race skip.
    try:
        import fcntl  # Linux/macOS (Docker container is always Linux)
        _scheduler_lock_fd = open(_SCHEDULER_LOCK_PATH, "w")
        fcntl.flock(_scheduler_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logger.info("Scheduler: another worker holds the scheduler lock — skipping (PID %s)", os.getpid())
        if _scheduler_lock_fd:
            try:
                _scheduler_lock_fd.close()
            except Exception:
                pass
            _scheduler_lock_fd = None
        return
    except ImportError:
        # Windows (dev only) — fcntl not available, skip locking
        pass

    thread = threading.Thread(
        target=_scheduler_loop,
        name="weekly-report-scheduler",
        daemon=True,   # killed when main process exits
    )
    thread.start()
    logger.info("Weekly report scheduler started (PID %s holds lock)", os.getpid())
