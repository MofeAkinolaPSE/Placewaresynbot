"""
Finance & Accounting Router — ACE (Tier 1 + Tier 2)
=============================================================
Implements Finance & Accounting features derived from the April 2026
requirements-gathering form (Finance Director: OGUNDOYIN OLUYEMI EMMANUEL):

  Tier-1 (Daily-Use Core):
  • GET  /finance/ar/aging          – Unified AR aging: buckets + per-customer rows
  • GET  /finance/ar/alerts         – List active alert rules + triggered events
  • POST /finance/ar/alerts         – Create a new threshold alert rule
  • DELETE /finance/ar/alerts/{id}  – Deactivate an alert rule
  • POST /finance/ar/alerts/{id}/ack – Acknowledge a triggered alert event
  • POST /finance/ar/match          – Invoice-to-payment matching (flag discrepancies)
  • GET  /finance/reports/pl        – P&L from GL journal entries (period-aware)
  • GET  /finance/reports/pl/pdf    – P&L as audit-stamped PDF
  • GET  /finance/exports/log       – Audit trail of all exports

  Tier-2 (Reports / Analytics):
  • GET  /finance/forecast/cashflow – 12-week rolling cash flow forecast
  • GET  /finance/payroll/summary   – Payroll summary + period-over-period variance
  • GET  /finance/payroll/pdf       – Payroll report as audit-stamped PDF

Security:
  All endpoints require `finance` or `management` or `admin` role.
  PDF exports write a row to `fin_audit_export_log`.
"""

from __future__ import annotations

import datetime
import io
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from src.db import db, audit_event
from src.middleware import verify_jwt, require_role
from src.services.sage_adapter.service import (
    ar_aging_buckets,
    ar_aging_customers,
    _latest_batch_for_table,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/finance", tags=["Finance"])

# ---------------------------------------------------------------------------
# Roles allowed for all finance endpoints
# ---------------------------------------------------------------------------
_FINANCE_ROLES = {"admin", "finance", "management"}


def _require_finance(request: Request) -> dict:
    """Decode JWT and enforce finance-tier role."""
    payload = verify_jwt(request)
    roles = {str(r).lower() for r in payload.get("roles", [])}
    if not roles & _FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Finance or management role required")
    return payload


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AlertRuleIn(BaseModel):
    threshold_amount: float = Field(..., gt=0, description="Balance threshold in NGN")
    days_overdue_min: int = Field(30, ge=0, description="Minimum days past due to trigger")
    customer_id: Optional[str] = Field(None, description="Specific customer, or null for all")
    description: Optional[str] = None
    notify_emails: List[str] = Field(default_factory=list)


class MatchRequest(BaseModel):
    period: Optional[str] = Field(None, description="Filter to YYYY-MM period, e.g. '2025-03'")


# ---------------------------------------------------------------------------
# AR AGING  —  GET /finance/ar/aging
# ---------------------------------------------------------------------------
@router.get("/ar/aging")
async def ar_aging(request: Request, bucket: Optional[str] = Query(None)):
    """
    Return AR aging summary (buckets) plus per-customer rows.

    Optional ?bucket= filters to a specific aging range:
    0-30 | 31-60 | 61-90 | 90+
    """
    _require_finance(request)
    try:
        summary = ar_aging_buckets()

        buckets_to_fetch = (
            [bucket]
            if bucket
            else ["0-30 days", "31-60 days", "61-90 days", "90+ days"]
        )

        all_customers: List[Dict[str, Any]] = []
        for b in buckets_to_fetch:
            rows = ar_aging_customers(bucket=b)
            for r in rows:
                r["bucket_label"] = b
            all_customers.extend(rows)

        # Evaluate active alert rules against the customer data
        triggered: List[Dict[str, Any]] = []
        try:
            rules_resp = (
                db.table("fin_ar_alert_rules")
                .select("id,threshold_amount,days_overdue_min,customer_id,description")
                .eq("is_active", True)
                .execute()
            )
            for rule in rules_resp.data or []:
                for cust in all_customers:
                    cid = cust.get("customer_id")
                    if rule.get("customer_id") and rule["customer_id"] != cid:
                        continue
                    bal = float(cust.get("total_balance") or 0)
                    days = int(cust.get("max_days_overdue") or 0)
                    if bal >= rule["threshold_amount"] and days >= rule["days_overdue_min"]:
                        triggered.append(
                            {
                                "rule_id": str(rule["id"]),
                                "customer_id": cid,
                                "outstanding_balance": bal,
                                "days_overdue": days,
                                "rule_description": rule.get("description"),
                            }
                        )
        except Exception as e:
            log.warning("Alert rule evaluation failed: %s", e)

        return {
            "summary": summary,
            "customers": all_customers,
            "triggered_alerts": triggered,
            "as_of": datetime.date.today().isoformat(),
        }
    except Exception as e:
        log.error("/finance/ar/aging error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to compute AR aging")


# ---------------------------------------------------------------------------
# AR ALERTS — CRUD
# ---------------------------------------------------------------------------
@router.get("/ar/alerts")
async def list_ar_alerts(request: Request):
    """List all active alert rules and unacknowledged alert events."""
    _require_finance(request)
    try:
        rules = (
            db.table("fin_ar_alert_rules")
            .select("*")
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        events = (
            db.table("fin_ar_alert_events")
            .select("*")
            .eq("acknowledged", False)
            .order("triggered_at", desc=True)
            .limit(200)
            .execute()
            .data
            or []
        )
        return {"rules": rules, "unacknowledged_events": events}
    except Exception as e:
        log.error("/finance/ar/alerts GET error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch alert rules")


@router.post("/ar/alerts", status_code=201)
async def create_ar_alert(request: Request, body: AlertRuleIn):
    """Create a new AR threshold alert rule."""
    user = _require_finance(request)
    try:
        row = {
            "threshold_amount": body.threshold_amount,
            "days_overdue_min": body.days_overdue_min,
            "customer_id": body.customer_id,
            "description": body.description,
            "notify_emails": body.notify_emails,
            "is_active": True,
            "created_by": user.get("sub"),
        }
        resp = db.table("fin_ar_alert_rules").insert(row).execute()
        audit_event(
            event_class="finance",
            event_type="ar_alert_created",
            actor_id=user.get("sub"),
            metadata={"threshold": body.threshold_amount, "days": body.days_overdue_min},
        )
        return {"status": "created", "rule": (resp.data or [{}])[0]}
    except Exception as e:
        log.error("/finance/ar/alerts POST error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create alert rule")


@router.delete("/ar/alerts/{rule_id}", status_code=200)
async def delete_ar_alert(request: Request, rule_id: str):
    """Deactivate (soft-delete) an alert rule."""
    user = _require_finance(request)
    try:
        resp = (
            db.table("fin_ar_alert_rules")
            .update({"is_active": False, "updated_at": datetime.datetime.utcnow().isoformat()})
            .eq("id", rule_id)
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        audit_event(
            event_class="finance",
            event_type="ar_alert_deactivated",
            actor_id=user.get("sub"),
            metadata={"rule_id": rule_id},
        )
        return {"status": "deactivated", "rule_id": rule_id}
    except HTTPException:
        raise
    except Exception as e:
        log.error("/finance/ar/alerts DELETE error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to deactivate alert rule")


@router.post("/ar/alerts/{event_id}/ack", status_code=200)
async def ack_alert_event(request: Request, event_id: str):
    """Acknowledge a triggered alert event (dismiss from dashboard)."""
    user = _require_finance(request)
    try:
        resp = (
            db.table("fin_ar_alert_events")
            .update(
                {
                    "acknowledged": True,
                    "acknowledged_by": user.get("sub"),
                    "acknowledged_at": datetime.datetime.utcnow().isoformat(),
                }
            )
            .eq("id", event_id)
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Alert event not found")
        return {"status": "acknowledged", "event_id": event_id}
    except HTTPException:
        raise
    except Exception as e:
        log.error("/finance/ar/alerts/ack error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to acknowledge alert event")


# ---------------------------------------------------------------------------
# INVOICE MATCHING  —  POST /finance/ar/match
# ---------------------------------------------------------------------------
@router.post("/ar/match")
async def match_invoices(request: Request, body: MatchRequest):
    """
    Scan AR snapshot and GL payments to flag unmatched invoices.

    Returns:
      matched   — invoices with a corresponding GL payment entry
      unmatched — outstanding invoices with no payment record
      discrepancies — invoices where paid amount differs from invoice amount
    """
    _require_finance(request)
    try:
        batch_id = _latest_batch_for_table("sage_ar_snapshot")
        ar_q = (
            db.table("sage_ar_snapshot")
            .select("invoice_id,customer_id,amount,balance,status,due_date,date")
        )
        if batch_id:
            ar_q = ar_q.eq("batch_id", batch_id)
        if body.period:
            ar_q = ar_q.like("date", f"{body.period}%")
        ar_rows = ar_q.limit(5000).execute().data or []

        # Fetch GL payment entries (credit side referencing invoice ids)
        gl_batch = _latest_batch_for_table("sage_gl_snapshot")
        gl_q = (
            db.table("sage_gl_snapshot")
            .select("account_code,credit,debit,period,account_name")
            .gt("credit", 0)
        )
        if gl_batch:
            gl_q = gl_q.eq("batch_id", gl_batch)
        gl_rows = gl_q.limit(10000).execute().data or []

        # Build lookup: account_code → total credits (GL payments proxy)
        payments: Dict[str, float] = {}
        for g in gl_rows:
            ref = (g.get("account_code") or "").strip()
            if ref:
                payments[ref] = payments.get(ref, 0.0) + float(g.get("credit") or 0)

        matched: List[Dict] = []
        unmatched: List[Dict] = []
        discrepancies: List[Dict] = []

        for inv in ar_rows:
            inv_id = (inv.get("invoice_id") or "").strip()
            amount = float(inv.get("amount") or 0)
            balance = float(inv.get("balance") or 0)
            paid_in_gl = payments.get(inv_id, 0.0)
            status = (inv.get("status") or "").lower()

            record = {
                "invoice_id": inv_id,
                "customer_id": inv.get("customer_id"),
                "invoice_amount": amount,
                "outstanding_balance": balance,
                "gl_payment_found": paid_in_gl,
                "due_date": inv.get("due_date"),
                "status": status,
            }

            if status == "paid" and paid_in_gl == 0.0:
                # Marked paid in AR but no GL credit found
                discrepancies.append({**record, "issue": "marked_paid_no_gl_credit"})
            elif paid_in_gl > 0.0 and abs(amount - paid_in_gl) > 0.01:
                # Partial payment or amount mismatch
                discrepancies.append(
                    {
                        **record,
                        "issue": "amount_mismatch",
                        "difference": round(amount - paid_in_gl, 2),
                    }
                )
            elif paid_in_gl > 0.0:
                matched.append(record)
            else:
                unmatched.append(record)

        return {
            "period": body.period or "all",
            "total_invoices": len(ar_rows),
            "matched": matched,
            "unmatched": unmatched,
            "discrepancies": discrepancies,
            "summary": {
                "matched_count": len(matched),
                "unmatched_count": len(unmatched),
                "discrepancy_count": len(discrepancies),
            },
        }
    except Exception as e:
        log.error("/finance/ar/match error: %s", e)
        raise HTTPException(status_code=500, detail="Invoice matching failed")


# ---------------------------------------------------------------------------
# P&L REPORT  —  GET /finance/reports/pl
# ---------------------------------------------------------------------------
def _compute_pl(period: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute P&L from GL journal entries and chart of accounts.
    Revenue accounts: credit-heavy GL lines (account codes per sage_coa_snapshot).
    Expense accounts: debit-heavy GL lines.
    """
    from src.constants import (
        REVENUE_GL_ACCOUNT_MIN,
        REVENUE_GL_ACCOUNT_MAX,
        COST_GL_ACCOUNT_MIN,
        COST_GL_ACCOUNT_MAX,
    )

    # Monthly P&L comes from the v_pl_monthly view (migration 093): GL detail
    # transactions classified by account_type from the chart of accounts.
    # The GL account-summary snapshot can't be used — its income rows carry
    # no per-period breakdown (period = '0000-00').
    pl_q = db.table("v_pl_monthly").select("period,revenue,expenses")
    if period:
        pl_q = pl_q.like("period", f"{period}%")
    pl_rows = pl_q.limit(1000).execute().data or []

    # Build monthly buckets { "YYYY-MM": { revenue, expenses } }
    monthly: Dict[str, Dict[str, float]] = {}
    totals = {"revenue": 0.0, "expenses": 0.0}

    for r in pl_rows:
        pd = str(r.get("period") or "")[:7]
        if not pd:
            continue
        rev = float(r.get("revenue") or 0)
        exp = float(r.get("expenses") or 0)
        bucket = monthly.setdefault(pd, {"revenue": 0.0, "expenses": 0.0})
        bucket["revenue"] += rev
        bucket["expenses"] += exp
        totals["revenue"] += rev
        totals["expenses"] += exp

    series = []
    for month in sorted(monthly.keys()):
        rev = monthly[month]["revenue"]
        exp = monthly[month]["expenses"]
        series.append(
            {
                "period": month,
                "revenue": round(rev, 2),
                "expenses": round(exp, 2),
                "gross_profit": round(rev - exp, 2),
                "margin_pct": round((rev - exp) / rev * 100, 2) if rev > 0 else 0.0,
            }
        )

    total_rev = totals["revenue"]
    total_exp = totals["expenses"]
    net_profit = total_rev - total_exp
    return {
        "period_filter": period or "all",
        "series": series,
        "totals": {
            "revenue": round(total_rev, 2),
            "expenses": round(total_exp, 2),
            "net_profit": round(net_profit, 2),
            "net_margin_pct": round(net_profit / total_rev * 100, 2) if total_rev > 0 else 0.0,
        },
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }


@router.get("/reports/pl")
async def get_pl_report(request: Request, period: Optional[str] = Query(None)):
    """
    Return P&L statement computed from GL journal entries.
    Optional ?period=YYYY-MM to filter to a single month.
    """
    user = _require_finance(request)
    try:
        data = _compute_pl(period=period)
        return data
    except Exception as e:
        log.error("/finance/reports/pl error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to compute P&L report")


# ---------------------------------------------------------------------------
# P&L PDF  —  GET /finance/reports/pl/pdf
# ---------------------------------------------------------------------------
@router.get("/reports/pl/pdf")
async def get_pl_pdf(request: Request, period: Optional[str] = Query(None)):
    """
    Return P&L statement as an audit-stamped PDF.
    Writes a row to fin_audit_export_log.
    """
    user = _require_finance(request)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        pl = _compute_pl(period=period)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=50, bottomMargin=40)
        styles = getSampleStyleSheet()
        elems = []

        # Title
        elems.append(Paragraph("Placeware Pharma — Profit & Loss Statement", styles["Title"]))
        sub = f"Period: {period or 'All periods'}  |  Generated: {pl['generated_at'][:19]} UTC"
        elems.append(Paragraph(sub, styles["Normal"]))
        elems.append(Spacer(1, 14))

        # Totals summary table
        totals = pl["totals"]
        summary_data = [
            ["Metric", "Amount (₦)"],
            ["Total Revenue", f"{totals['revenue']:,.2f}"],
            ["Total Expenses", f"{totals['expenses']:,.2f}"],
            ["Net Profit", f"{totals['net_profit']:,.2f}"],
            ["Net Margin %", f"{totals['net_margin_pct']:.2f}%"],
        ]
        t = Table(summary_data, colWidths=[200, 200])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ]
            )
        )
        elems.append(t)
        elems.append(Spacer(1, 20))

        # Monthly series table
        if pl["series"]:
            elems.append(Paragraph("Monthly Breakdown", styles["Heading2"]))
            elems.append(Spacer(1, 8))
            series_data = [["Period", "Revenue (₦)", "Expenses (₦)", "Gross Profit (₦)", "Margin %"]]
            for row in pl["series"]:
                series_data.append(
                    [
                        row["period"],
                        f"{row['revenue']:,.2f}",
                        f"{row['expenses']:,.2f}",
                        f"{row['gross_profit']:,.2f}",
                        f"{row['margin_pct']:.2f}%",
                    ]
                )
            st = Table(series_data, colWidths=[80, 100, 100, 110, 70])
            st.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            elems.append(st)

        # Audit footer
        elems.append(Spacer(1, 30))
        actor_id = user.get("sub") or "system"
        elems.append(
            Paragraph(
                f"AUDIT TRAIL: Exported by user {actor_id} at {pl['generated_at'][:19]} UTC. "
                f"Data sourced from Sage GL snapshot. This report is confidential.",
                styles["Normal"],
            )
        )

        doc.build(elems)
        pdf_bytes = buf.getvalue()

        # Log the export
        try:
            db.table("fin_audit_export_log").insert(
                {
                    "report_type": "pl",
                    "exported_by": user.get("sub"),
                    "row_count": len(pl["series"]),
                    "period": period or "all",
                    "file_format": "pdf",
                    "filters": {"period": period},
                }
            ).execute()
        except Exception as log_err:
            log.warning("Failed to write audit export log: %s", log_err)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="pl_report_{period or "all"}_{datetime.date.today().isoformat()}.pdf"'
            },
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed")
    except Exception as e:
        log.error("/finance/reports/pl/pdf error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate P&L PDF")


# ---------------------------------------------------------------------------
# AUDIT EXPORT LOG  —  GET /finance/exports/log
# ---------------------------------------------------------------------------
@router.get("/exports/log")
async def list_export_log(request: Request, limit: int = Query(50, le=200)):
    """Return audit trail of all financial report exports."""
    _require_finance(request)
    try:
        rows = (
            db.table("fin_audit_export_log")
            .select("*")
            .order("exported_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        return {"data": rows, "count": len(rows)}
    except Exception as e:
        log.error("/finance/exports/log error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch export log")


# ===========================================================================
# TIER 2 — CASH FLOW FORECAST
# ===========================================================================

@router.get("/forecast/cashflow")
async def cashflow_forecast(
    request: Request,
    weeks: int = Query(12, ge=4, le=52),
):
    """
    12-week rolling cash flow forecast.

    Inflows:  AR receivables expected within each week (from sage_ar_snapshot
              where status != 'paid', bucketed by due_date).
    Outflows: Open/partial POs expected within each week (sage_purchase_orders_snapshot,
              bucketed by expected_delivery_date).
    Running balance starts from the most recent GL cash account balance.

    Returns weekly rows + summary totals.
    """
    _require_finance(request)
    try:
        today = datetime.date.today()
        # Build week boundaries
        week_buckets: List[Dict[str, Any]] = []
        for w in range(weeks):
            start = today + datetime.timedelta(days=w * 7)
            end = start + datetime.timedelta(days=6)
            week_buckets.append(
                {
                    "week": w + 1,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "inflow": 0.0,
                    "outflow": 0.0,
                }
            )

        # ---- Inflows: outstanding AR due in next N weeks ----
        ar_batch = _latest_batch_for_table("sage_ar_snapshot")
        ar_q = db.table("sage_ar_snapshot").select("due_date,balance,status")
        if ar_batch:
            ar_q = ar_q.eq("batch_id", ar_batch)
        ar_rows = ar_q.neq("status", "paid").limit(10000).execute().data or []

        for r in ar_rows:
            bal = float(r.get("balance") or 0)
            if bal <= 0:
                continue
            dd_raw = r.get("due_date")
            if not dd_raw:
                continue
            try:
                dd = datetime.date.fromisoformat(str(dd_raw)[:10])
            except ValueError:
                continue
            for wb in week_buckets:
                ws = datetime.date.fromisoformat(wb["start"])
                we = datetime.date.fromisoformat(wb["end"])
                if ws <= dd <= we:
                    wb["inflow"] += bal
                    break

        # ---- Outflows: open/partial POs due in next N weeks ----
        po_batch = _latest_batch_for_table("sage_purchase_orders_snapshot")
        po_q = db.table("sage_purchase_orders_snapshot").select(
            "expected_delivery_date,total_amount,status"
        )
        if po_batch:
            po_q = po_q.eq("batch_id", po_batch)
        po_rows = po_q.in_("status", ["open", "partial"]).limit(5000).execute().data or []

        for r in po_rows:
            amt = float(r.get("total_amount") or 0)
            if amt <= 0:
                continue
            dd_raw = r.get("expected_delivery_date")
            if not dd_raw:
                continue
            try:
                dd = datetime.date.fromisoformat(str(dd_raw)[:10])
            except ValueError:
                continue
            for wb in week_buckets:
                ws = datetime.date.fromisoformat(wb["start"])
                we = datetime.date.fromisoformat(wb["end"])
                if ws <= dd <= we:
                    wb["outflow"] += amt
                    break

        # ---- Compute running balance ----
        # Seed from latest GL cash balance (rough approximation from net GL credits)
        opening_balance = 0.0
        try:
            gl_batch = _latest_batch_for_table("sage_gl_snapshot")
            gl_q = db.table("sage_gl_snapshot").select("credit,debit")
            if gl_batch:
                gl_q = gl_q.eq("batch_id", gl_batch)
            gl_rows = gl_q.limit(50000).execute().data or []
            net = sum(
                float(r.get("credit") or 0) - float(r.get("debit") or 0)
                for r in gl_rows
            )
            opening_balance = max(net, 0.0)
        except Exception:
            pass

        running = opening_balance
        for wb in week_buckets:
            running = running + wb["inflow"] - wb["outflow"]
            wb["running_balance"] = round(running, 2)
            wb["net"] = round(wb["inflow"] - wb["outflow"], 2)
            wb["inflow"] = round(wb["inflow"], 2)
            wb["outflow"] = round(wb["outflow"], 2)

        total_inflow = sum(w["inflow"] for w in week_buckets)
        total_outflow = sum(w["outflow"] for w in week_buckets)

        return {
            "weeks": weeks,
            "opening_balance": round(opening_balance, 2),
            "forecast": week_buckets,
            "totals": {
                "total_inflow": round(total_inflow, 2),
                "total_outflow": round(total_outflow, 2),
                "net_position": round(total_inflow - total_outflow, 2),
                "closing_balance": round(opening_balance + total_inflow - total_outflow, 2),
            },
            "as_of": today.isoformat(),
            "note": "Inflows from outstanding AR; outflows from open/partial POs. Opening balance estimated from GL net.",
        }
    except Exception as e:
        log.error("/finance/forecast/cashflow error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to compute cash flow forecast")


# ===========================================================================
# TIER 2 — PAYROLL SUMMARY & VARIANCE
# ===========================================================================

def _compute_payroll(period: Optional[str] = None) -> Dict[str, Any]:
    """
    Summarise payroll from sage_payroll_snapshot.
    Groups by department/period where available, or treats all rows as current period.
    Returns per-employee rows, totals, and period-over-period variance.
    """
    batch_id = _latest_batch_for_table("sage_payroll_snapshot")
    q = db.table("sage_payroll_snapshot").select(
        "employee_id,department,period,salary,overtime_hours,overtime_rate,total_gross,net_pay,deductions,imported_at"
    )
    if batch_id:
        q = q.eq("batch_id", batch_id)
    if period:
        q = q.eq("period", period)
    rows = q.order("imported_at", desc=True).limit(500).execute().data or []

    # Compute totals
    total_gross = 0.0
    total_net = 0.0
    total_deductions = 0.0
    total_overtime_cost = 0.0
    dept_totals: Dict[str, Dict[str, float]] = {}

    employees: List[Dict[str, Any]] = []
    for r in rows:
        salary = float(r.get("salary") or 0)
        ot_hrs = float(r.get("overtime_hours") or 0)
        ot_rate = float(r.get("overtime_rate") or 0)
        ot_cost = ot_hrs * ot_rate
        gross = float(r.get("total_gross") or 0) or (salary + ot_cost)
        net = float(r.get("net_pay") or 0) or gross
        deductions = float(r.get("deductions") or 0) or (gross - net)
        dept = r.get("department") or "Unassigned"

        total_gross += gross
        total_net += net
        total_deductions += deductions
        total_overtime_cost += ot_cost

        dtot = dept_totals.setdefault(dept, {"gross": 0.0, "net": 0.0, "headcount": 0, "overtime_cost": 0.0})
        dtot["gross"] += gross
        dtot["net"] += net
        dtot["headcount"] += 1
        dtot["overtime_cost"] += ot_cost

        employees.append(
            {
                "employee_id": r.get("employee_id"),
                "department": dept,
                "period": r.get("period"),
                "salary": round(salary, 2),
                "overtime_hours": ot_hrs,
                "overtime_cost": round(ot_cost, 2),
                "gross_pay": round(gross, 2),
                "deductions": round(deductions, 2),
                "net_pay": round(net, 2),
            }
        )

    dept_summary = [
        {
            "department": dept,
            "headcount": v["headcount"],
            "total_gross": round(v["gross"], 2),
            "total_net": round(v["net"], 2),
            "total_overtime_cost": round(v["overtime_cost"], 2),
        }
        for dept, v in sorted(dept_totals.items())
    ]

    # ---- Period-over-period variance: compare current batch vs prior batch ----
    variance: Optional[Dict[str, Any]] = None
    try:
        prior_resp = (
            db.table("sage_payroll_snapshot")
            .select("batch_id,imported_at")
            .order("imported_at", desc=True)
            .limit(50)
            .execute()
            .data
            or []
        )
        seen = []
        for r in prior_resp:
            bid = r.get("batch_id")
            if bid and bid not in seen:
                seen.append(bid)
            if len(seen) >= 2:
                break

        if len(seen) >= 2 and batch_id and seen[0] == batch_id:
            prior_batch = seen[1]
            prior_rows = (
                db.table("sage_payroll_snapshot")
                .select("salary,overtime_hours,overtime_rate,total_gross,net_pay")
                .eq("batch_id", prior_batch)
                .execute()
                .data
                or []
            )
            prior_gross = 0.0
            for pr in prior_rows:
                pg = float(pr.get("total_gross") or 0) or (
                    float(pr.get("salary") or 0)
                    + float(pr.get("overtime_hours") or 0) * float(pr.get("overtime_rate") or 0)
                )
                prior_gross += pg
            variance = {
                "prior_total_gross": round(prior_gross, 2),
                "current_total_gross": round(total_gross, 2),
                "change": round(total_gross - prior_gross, 2),
                "change_pct": round((total_gross - prior_gross) / prior_gross * 100, 2) if prior_gross > 0 else None,
            }
    except Exception as ve:
        log.warning("Payroll variance computation failed: %s", ve)

    return {
        "period_filter": period or "latest",
        "headcount": len(employees),
        "employees": employees,
        "department_summary": dept_summary,
        "totals": {
            "total_gross": round(total_gross, 2),
            "total_net": round(total_net, 2),
            "total_deductions": round(total_deductions, 2),
            "total_overtime_cost": round(total_overtime_cost, 2),
        },
        "variance": variance,
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }


@router.get("/payroll/summary")
async def payroll_summary(request: Request, period: Optional[str] = Query(None)):
    """
    Return payroll summary: per-employee rows, department totals, and
    period-over-period variance (current vs prior import batch).
    """
    user = _require_finance(request)
    try:
        data = _compute_payroll(period=period)
        return data
    except Exception as e:
        log.error("/finance/payroll/summary error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to compute payroll summary")


@router.get("/payroll/pdf")
async def payroll_pdf(request: Request, period: Optional[str] = Query(None)):
    """
    Return payroll summary as an audit-stamped PDF.
    Writes a row to fin_audit_export_log.
    """
    user = _require_finance(request)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        data = _compute_payroll(period=period)
        totals = data["totals"]
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=50, bottomMargin=40)
        styles = getSampleStyleSheet()
        elems = []

        elems.append(Paragraph("Placeware Pharma — Payroll Summary Report", styles["Title"]))
        elems.append(
            Paragraph(
                f"Period: {data['period_filter']}  |  Headcount: {data['headcount']}  |  Generated: {data['generated_at'][:19]} UTC",
                styles["Normal"],
            )
        )
        elems.append(Spacer(1, 14))

        # Totals table
        totals_data = [
            ["Metric", "Amount (₦)"],
            ["Total Gross Pay", f"{totals['total_gross']:,.2f}"],
            ["Total Net Pay", f"{totals['total_net']:,.2f}"],
            ["Total Deductions", f"{totals['total_deductions']:,.2f}"],
            ["Total Overtime Cost", f"{totals['total_overtime_cost']:,.2f}"],
        ]
        if data.get("variance"):
            v = data["variance"]
            totals_data.append(["vs Prior Period", f"{v['change']:+,.2f} ({v.get('change_pct', 0):.1f}%)"])

        t = Table(totals_data, colWidths=[200, 200])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ]
            )
        )
        elems.append(t)
        elems.append(Spacer(1, 16))

        # Department summary
        if data["department_summary"]:
            elems.append(Paragraph("By Department", styles["Heading2"]))
            elems.append(Spacer(1, 6))
            dept_data = [["Department", "Headcount", "Gross (₦)", "Net (₦)", "OT Cost (₦)"]]
            for d in data["department_summary"]:
                dept_data.append(
                    [
                        d["department"],
                        str(d["headcount"]),
                        f"{d['total_gross']:,.2f}",
                        f"{d['total_net']:,.2f}",
                        f"{d['total_overtime_cost']:,.2f}",
                    ]
                )
            dt = Table(dept_data, colWidths=[120, 70, 100, 100, 80])
            dt.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            elems.append(dt)
            elems.append(Spacer(1, 16))

        # Employee detail (capped at 100 rows for PDF size)
        if data["employees"]:
            elems.append(Paragraph("Employee Detail (first 100)", styles["Heading2"]))
            elems.append(Spacer(1, 6))
            emp_data = [["Employee ID", "Department", "Gross (₦)", "Deductions (₦)", "Net (₦)", "OT Hrs"]]
            for emp in data["employees"][:100]:
                emp_data.append(
                    [
                        emp["employee_id"] or "—",
                        emp["department"] or "—",
                        f"{emp['gross_pay']:,.2f}",
                        f"{emp['deductions']:,.2f}",
                        f"{emp['net_pay']:,.2f}",
                        str(emp["overtime_hours"]),
                    ]
                )
            et = Table(emp_data, colWidths=[80, 90, 90, 90, 80, 50])
            et.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            elems.append(et)

        # Audit footer
        elems.append(Spacer(1, 28))
        actor_id = user.get("sub") or "system"
        elems.append(
            Paragraph(
                f"AUDIT TRAIL: Exported by user {actor_id} at {data['generated_at'][:19]} UTC. "
                "Payroll data is strictly confidential. Unauthorised disclosure is prohibited.",
                styles["Normal"],
            )
        )

        doc.build(elems)
        pdf_bytes = buf.getvalue()

        # Log the export
        try:
            db.table("fin_audit_export_log").insert(
                {
                    "report_type": "payroll",
                    "exported_by": user.get("sub"),
                    "row_count": data["headcount"],
                    "period": period or "latest",
                    "file_format": "pdf",
                    "filters": {"period": period},
                }
            ).execute()
        except Exception as log_err:
            log.warning("Failed to write audit export log: %s", log_err)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="payroll_{period or "latest"}_{datetime.date.today().isoformat()}.pdf"'
            },
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed")
    except Exception as e:
        log.error("/finance/payroll/pdf error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate payroll PDF")


# ===========================================================================
# TIER 3 — VENDOR PAYMENT APPROVAL WORKFLOW
# ===========================================================================

class VendorPaymentIn(BaseModel):
    vendor_id: str = Field(..., min_length=1)
    vendor_name: Optional[str] = None
    amount: float = Field(..., gt=0)
    currency: str = Field("NGN", max_length=3)
    payment_date: Optional[str] = None   # ISO date string
    reference: Optional[str] = None
    description: Optional[str] = None


class ApprovalActionIn(BaseModel):
    note: Optional[str] = None


_VALID_TRANSITIONS: Dict[str, List[str]] = {
    "pending":   ["approved", "rejected", "cancelled"],
    "approved":  ["paid", "cancelled"],
    "rejected":  [],          # terminal
    "paid":      [],          # terminal
    "cancelled": [],          # terminal
}

_APPROVE_ROLES = {"admin", "finance", "management"}


@router.get("/vendor/payments")
async def list_vendor_payments(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """
    List vendor payment requests, optionally filtered by status.
    Paginated (limit/offset).
    """
    _require_finance(request)
    try:
        q = db.table("fin_vendor_payment_requests").select("*").order("created_at", desc=True)
        if status:
            q = q.eq("status", status)
        rows = q.range(offset, offset + limit - 1).execute().data or []
        return {"data": rows, "count": len(rows), "offset": offset, "limit": limit}
    except Exception as e:
        log.error("/finance/vendor/payments list error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch vendor payments")


@router.post("/vendor/payments", status_code=201)
async def create_vendor_payment(request: Request, body: VendorPaymentIn):
    """
    Create a new vendor payment request (status = pending).
    Any finance/admin user can raise a request.
    """
    user = _require_finance(request)
    try:
        row: Dict[str, Any] = {
            "vendor_id": body.vendor_id,
            "vendor_name": body.vendor_name,
            "amount": body.amount,
            "currency": body.currency.upper(),
            "payment_date": body.payment_date,
            "reference": body.reference,
            "description": body.description,
            "status": "pending",
            "requested_by": user.get("sub"),
        }
        result = db.table("fin_vendor_payment_requests").insert(row).execute().data
        created = result[0] if result else row
        log.info("Vendor payment request created: vendor=%s amount=%s by=%s", body.vendor_id, body.amount, user.get("sub"))
        return created
    except Exception as e:
        log.error("/finance/vendor/payments create error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create vendor payment request")


@router.patch("/vendor/payments/{payment_id}/approve")
async def approve_vendor_payment(
    request: Request,
    payment_id: str,
    body: ApprovalActionIn = ApprovalActionIn(),
):
    """
    Approve a pending vendor payment request.
    Requires admin, finance, or management role.
    """
    user = _require_finance(request)
    role = (user.get("role") or user.get("user_role") or "").lower()
    if role not in _APPROVE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role to approve payments")
    return await _transition_payment(payment_id, "approved", user, body.note)


@router.patch("/vendor/payments/{payment_id}/reject")
async def reject_vendor_payment(
    request: Request,
    payment_id: str,
    body: ApprovalActionIn = ApprovalActionIn(),
):
    """
    Reject a pending or approved vendor payment request.
    """
    user = _require_finance(request)
    role = (user.get("role") or user.get("user_role") or "").lower()
    if role not in _APPROVE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role to reject payments")
    return await _transition_payment(payment_id, "rejected", user, body.note)


@router.patch("/vendor/payments/{payment_id}/mark-paid")
async def mark_vendor_payment_paid(
    request: Request,
    payment_id: str,
    body: ApprovalActionIn = ApprovalActionIn(),
):
    """
    Mark an approved vendor payment as paid.
    """
    user = _require_finance(request)
    return await _transition_payment(payment_id, "paid", user, body.note)


@router.delete("/vendor/payments/{payment_id}")
async def cancel_vendor_payment(request: Request, payment_id: str):
    """
    Cancel a pending vendor payment request (soft delete via status transition).
    """
    user = _require_finance(request)
    return await _transition_payment(payment_id, "cancelled", user, note=None)


async def _transition_payment(
    payment_id: str,
    new_status: str,
    user: Dict[str, Any],
    note: Optional[str],
) -> Dict[str, Any]:
    """Shared state-machine transition for vendor payment requests."""
    try:
        existing_resp = (
            db.table("fin_vendor_payment_requests")
            .select("id,status")
            .eq("id", payment_id)
            .single()
            .execute()
        )
        existing = existing_resp.data
        if not existing:
            raise HTTPException(status_code=404, detail="Payment request not found")

        current_status = existing.get("status", "")
        allowed = _VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot transition from '{current_status}' to '{new_status}'. Allowed: {allowed or 'none (terminal)'}",
            )

        update: Dict[str, Any] = {
            "status": new_status,
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }
        actor_id = user.get("sub")
        if new_status == "approved":
            update["approved_by"] = actor_id
            update["approved_at"] = datetime.datetime.utcnow().isoformat()
        if new_status == "paid":
            update["paid_at"] = datetime.datetime.utcnow().isoformat()
        if note is not None:
            update["approval_note"] = note

        result = (
            db.table("fin_vendor_payment_requests")
            .update(update)
            .eq("id", payment_id)
            .execute()
            .data
        )
        updated = result[0] if result else {**existing, **update}
        log.info(
            "Vendor payment %s transitioned %s → %s by %s",
            payment_id, current_status, new_status, actor_id,
        )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        log.error("Payment transition error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update payment status")


# ===========================================================================
# TIER 3 — CREDIT RISK SCORING
# ===========================================================================

_RISK_TIERS = [
    (76, "Critical"),
    (51, "High"),
    (21, "Medium"),
    (0,  "Low"),
]


def _score_customer(
    balance: float,
    days_overdue: int,
    alert_events: int,
    total_ar: float,
) -> Dict[str, Any]:
    """
    Compute a 0–100 credit risk score for a single customer.

    Scoring components:
      • Days overdue:    0-30 → +5 | 31-60 → +20 | 61-90 → +40 | 91+ → +60
      • Balance size:    > 2M NGN → +15 | > 5M NGN → additional +10
      • AR concentration: balance/total_ar > 25% → +10
      • Alert events:    +5 per event, capped at +20
    """
    score = 0

    # Overdue bucket contribution
    if days_overdue > 90:
        score += 60
    elif days_overdue > 60:
        score += 40
    elif days_overdue > 30:
        score += 20
    elif days_overdue > 0:
        score += 5

    # Balance size
    if balance >= 5_000_000:
        score += 25
    elif balance >= 2_000_000:
        score += 15

    # AR concentration
    if total_ar > 0 and (balance / total_ar) > 0.25:
        score += 10

    # Alert frequency
    score += min(alert_events * 5, 20)

    score = min(score, 100)

    # Determine tier
    tier = "Low"
    for threshold, label in _RISK_TIERS:
        if score >= threshold:
            tier = label
            break

    return {"score": score, "tier": tier}


@router.get("/credit/risk")
async def credit_risk_scores(request: Request):
    """
    Compute a credit risk score (0–100) and tier (Low/Medium/High/Critical)
    for every customer in the AR snapshot.

    Algorithm inputs:
      • Outstanding balance (from sage_ar_snapshot)
      • Days overdue (computed from due_date vs today)
      • Number of unacknowledged alert events (from fin_ar_alert_events)
      • Share of total AR outstanding

    Returns scored list sorted by score descending + a tier distribution summary.
    """
    _require_finance(request)
    today = datetime.date.today()
    try:
        # --- AR outstanding per customer ---
        # balance > 0 filter keeps the zero-value aged-summary rows from
        # crowding real invoices out of the row limit.
        ar_batch = _latest_batch_for_table("sage_ar_snapshot")
        ar_q = db.table("sage_ar_snapshot").select(
            "customer_id,balance,due_date,date,status"
        ).gt("balance", 0)
        if ar_batch:
            ar_q = ar_q.eq("batch_id", ar_batch)
        ar_rows = ar_q.neq("status", "paid").limit(50000).execute().data or []

        # Aggregate per customer: max days overdue, total outstanding
        customer_data: Dict[str, Dict[str, Any]] = {}
        total_ar = 0.0
        for r in ar_rows:
            cid = str(r.get("customer_id") or "unknown")
            bal = float(r.get("balance") or 0)
            if bal <= 0:
                continue
            # Sage exports carry no due_date — fall back to invoice date
            # plus 30-day standard trade terms (see sage_adapter service).
            dd_raw = r.get("due_date")
            terms_days = 0
            if not dd_raw:
                dd_raw = r.get("date")
                terms_days = 30
            days_overdue = 0
            if dd_raw:
                try:
                    dd = datetime.date.fromisoformat(str(dd_raw)[:10])
                    days_overdue = max((today - dd).days - terms_days, 0)
                except ValueError:
                    pass

            total_ar += bal
            if cid not in customer_data:
                customer_data[cid] = {"balance": 0.0, "max_days_overdue": 0}
            customer_data[cid]["balance"] += bal
            customer_data[cid]["max_days_overdue"] = max(
                customer_data[cid]["max_days_overdue"], days_overdue
            )

        # --- Alert events per customer ---
        alert_counts: Dict[str, int] = {}
        try:
            events = (
                db.table("fin_ar_alert_events")
                .select("customer_id")
                .eq("acknowledged", False)
                .limit(5000)
                .execute()
                .data
                or []
            )
            for ev in events:
                cid = str(ev.get("customer_id") or "unknown")
                alert_counts[cid] = alert_counts.get(cid, 0) + 1
        except Exception as ae:
            log.warning("Credit risk: could not fetch alert events: %s", ae)

        # --- Score each customer ---
        scored: List[Dict[str, Any]] = []
        tier_counts: Dict[str, int] = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}

        for cid, data in customer_data.items():
            result = _score_customer(
                balance=data["balance"],
                days_overdue=data["max_days_overdue"],
                alert_events=alert_counts.get(cid, 0),
                total_ar=total_ar,
            )
            tier_counts[result["tier"]] = tier_counts.get(result["tier"], 0) + 1
            scored.append(
                {
                    "customer_id": cid,
                    "outstanding_balance": round(data["balance"], 2),
                    "max_days_overdue": data["max_days_overdue"],
                    "alert_events": alert_counts.get(cid, 0),
                    "risk_score": result["score"],
                    "risk_tier": result["tier"],
                }
            )

        scored.sort(key=lambda x: x["risk_score"], reverse=True)

        return {
            "customers": scored,
            "total_customers": len(scored),
            "total_ar_outstanding": round(total_ar, 2),
            "tier_distribution": tier_counts,
            "scoring_date": today.isoformat(),
        }
    except Exception as e:
        log.error("/finance/credit/risk error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to compute credit risk scores")


# ===========================================================================
# TIER 3 — BUDGET VS. ACTUAL VARIANCE
# ===========================================================================

class BudgetTargetIn(BaseModel):
    department: str = Field(..., min_length=1)
    category: str = Field("general", min_length=1)
    period: str = Field(..., pattern=r"^\d{4}-\d{2}$")   # YYYY-MM
    budgeted_amount: float = Field(..., ge=0)
    note: Optional[str] = None


@router.get("/budget/targets")
async def list_budget_targets(
    request: Request,
    period: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
):
    """List budget targets, optionally filtered by period and/or department."""
    _require_finance(request)
    try:
        q = db.table("fin_budget_targets").select("*").order("period", desc=True).order("department")
        if period:
            q = q.eq("period", period)
        if department:
            q = q.eq("department", department)
        rows = q.limit(500).execute().data or []
        return {"data": rows, "count": len(rows)}
    except Exception as e:
        log.error("/finance/budget/targets error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch budget targets")


@router.post("/budget/targets", status_code=201)
async def upsert_budget_target(request: Request, body: BudgetTargetIn):
    """
    Create or update a budget target for a department/category/period.
    Uses ON CONFLICT DO UPDATE via upsert.
    """
    user = _require_finance(request)
    try:
        row = {
            "department": body.department.strip(),
            "category": body.category.strip(),
            "period": body.period,
            "budgeted_amount": body.budgeted_amount,
            "note": body.note,
            "created_by": user.get("sub"),
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }
        result = (
            db.table("fin_budget_targets")
            .upsert(row, on_conflict="department,category,period")
            .execute()
            .data
        )
        return result[0] if result else row
    except Exception as e:
        log.error("/finance/budget/targets upsert error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save budget target")


@router.delete("/budget/targets/{target_id}")
async def delete_budget_target(request: Request, target_id: str):
    """Delete a budget target by ID."""
    user = _require_finance(request)
    role = (user.get("role") or user.get("user_role") or "").lower()
    if role not in {"admin", "finance"}:
        raise HTTPException(status_code=403, detail="Only admin/finance roles can delete budget targets")
    try:
        db.table("fin_budget_targets").delete().eq("id", target_id).execute()
        return {"deleted": True, "id": target_id}
    except Exception as e:
        log.error("/finance/budget/targets delete error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete budget target")


@router.get("/budget/variance")
async def budget_variance(
    request: Request,
    period: Optional[str] = Query(None, description="YYYY-MM — defaults to current month"),
):
    """
    Compare GL actual spending vs. budget targets for a period.

    Actuals come from sage_gl_snapshot (debit_amount = expense) grouped by
    cost_center (which maps to department). Credits are excluded (revenue).
    Targets come from fin_budget_targets.

    Returns: per-department rows with budgeted / actual / variance / variance_pct,
    plus an overall summary.
    """
    _require_finance(request)
    try:
        if not period:
            period = datetime.date.today().strftime("%Y-%m")
        requested_period = period

        # ---- Actual spending from GL detail (v_budget_actuals_monthly view,
        # migration 094): expense-type accounts grouped by account name.
        # sage_gl_snapshot can't be used — it has no per-period expense rows.
        def _fetch_actuals(p: str) -> List[Dict[str, Any]]:
            return (
                db.table("v_budget_actuals_monthly")
                .select("department,actual")
                .eq("period", p)
                .limit(5000)
                .execute()
                .data
                or []
            )

        gl_rows = _fetch_actuals(period)
        if not gl_rows:
            # Requested month has no GL activity (e.g. current month before the
            # next Sage export) — fall back to the latest month that does.
            latest = (
                db.table("v_budget_actuals_monthly")
                .select("period")
                .order("period", desc=True)
                .limit(1)
                .execute()
                .data
                or []
            )
            latest_period = latest[0].get("period") if latest else None
            if latest_period and latest_period != period:
                period = str(latest_period)
                gl_rows = _fetch_actuals(period)

        actuals: Dict[str, float] = {}
        for r in gl_rows:
            dept = str(r.get("department") or "Unassigned").strip() or "Unassigned"
            amt = float(r.get("actual") or 0)
            if amt > 0:
                actuals[dept] = actuals.get(dept, 0.0) + amt

        # ---- Budget targets for period ----
        targets_rows = (
            db.table("fin_budget_targets")
            .select("department,category,budgeted_amount,note")
            .eq("period", period)
            .execute()
            .data
            or []
        )
        # Aggregate targets per department (sum across categories)
        budgets: Dict[str, float] = {}
        for t in targets_rows:
            dept = str(t.get("department") or "Unassigned")
            budgets[dept] = budgets.get(dept, 0.0) + float(t.get("budgeted_amount") or 0)

        # ---- Build variance rows ----
        all_depts = sorted(set(list(actuals.keys()) + list(budgets.keys())))
        rows_out: List[Dict[str, Any]] = []
        for dept in all_depts:
            actual = actuals.get(dept, 0.0)
            budget = budgets.get(dept, 0.0)
            variance = actual - budget
            var_pct = round((variance / budget * 100), 2) if budget > 0 else None
            rows_out.append(
                {
                    "department": dept,
                    "budgeted": round(budget, 2),
                    "actual": round(actual, 2),
                    "variance": round(variance, 2),
                    "variance_pct": var_pct,
                    "status": (
                        "over_budget" if variance > 0 and budget > 0
                        else "under_budget" if variance < 0 and budget > 0
                        else "no_budget" if budget == 0
                        else "on_budget"
                    ),
                }
            )

        total_budget = sum(r["budgeted"] for r in rows_out)
        total_actual = sum(r["actual"] for r in rows_out)

        return {
            "period": period,
            "requested_period": requested_period,
            "rows": rows_out,
            "summary": {
                "total_budgeted": round(total_budget, 2),
                "total_actual": round(total_actual, 2),
                "total_variance": round(total_actual - total_budget, 2),
                "over_budget_departments": sum(1 for r in rows_out if r["status"] == "over_budget"),
                "no_budget_departments": sum(1 for r in rows_out if r["status"] == "no_budget"),
            },
            "gl_rows_processed": len(gl_rows),
        }
    except Exception as e:
        log.error("/finance/budget/variance error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to compute budget variance")


def _next_month_str(period: str) -> str:
    """Return the first day of the month after `period` (YYYY-MM)."""
    year, month = int(period[:4]), int(period[5:7])
    if month == 12:
        return f"{year + 1}-01-01"
    return f"{year}-{month + 1:02d}-01"


# ---------------------------------------------------------------------------
# CHART OF ACCOUNTS  —  GET /finance/coa
# ---------------------------------------------------------------------------
@router.get("/coa")
async def get_chart_of_accounts(request: Request, limit: int = Query(500, le=1000)):
    """Return chart of accounts from Sage 50 snapshot."""
    _require_finance(request)
    try:
        resp = (
            db.table("v_chart_of_accounts")
            .select("*")
            .order("account_code")
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        return {"data": rows, "total": len(rows)}
    except Exception as e:
        log.error("/finance/coa error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve chart of accounts")


# ---------------------------------------------------------------------------
# INVOICES  —  GET /finance/invoices  &  GET /finance/invoices/{invoice_id}
# ---------------------------------------------------------------------------
@router.get("/invoices")
async def list_invoices(
    request: Request,
    limit: int = Query(200, le=500),
    status: str = Query(None, description="Filter by status: open, paid, overdue"),
):
    """Return Placeware AR invoices (synced from Sage 50 on CSV import)."""
    _require_finance(request)
    try:
        rows = (
            db.table("placeware_invoices")
            .select("*")
            .order("invoice_date", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
        if not rows:
            # Fallback: read directly from Silver view if table not yet populated
            rows = (
                db.table("v_ar_invoices")
                .select("*")
                .limit(limit)
                .execute()
                .data or []
            )
        if status:
            rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
        return {"data": rows, "total": len(rows)}
    except Exception as e:
        log.error("/finance/invoices error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve invoices")


@router.get("/invoices/{invoice_id}")
async def get_invoice_detail(request: Request, invoice_id: str):
    """Return a single invoice with its line items."""
    _require_finance(request)
    try:
        header_rows = (
            db.table("placeware_invoices")
            .select("*")
            .eq("invoice_id", invoice_id)
            .limit(1)
            .execute()
            .data or []
        )
        if not header_rows:
            header_rows = (
                db.table("v_ar_invoices")
                .select("*")
                .eq("invoice_id", invoice_id)
                .limit(1)
                .execute()
                .data or []
            )
        if not header_rows:
            raise HTTPException(status_code=404, detail="Invoice not found")
        lines = (
            db.table("v_ar_invoice_lines")
            .select("*")
            .eq("invoice_id", invoice_id)
            .execute()
            .data or []
        )
        return {"invoice": header_rows[0], "lines": lines}
    except HTTPException:
        raise
    except Exception as e:
        log.error("/finance/invoices/%s error: %s", invoice_id, e)
        raise HTTPException(status_code=500, detail="Failed to retrieve invoice detail")


# ---------------------------------------------------------------------------
# BANK RECONCILIATION  —  GET /finance/reconciliation/status
#                          POST /finance/reconciliation/log
# ---------------------------------------------------------------------------

# Snapshot types that are point-in-time (overwrite) vs historical (append)
_POINT_IN_TIME_TYPES = {
    "account_reconciliation",
    "deposits_in_transit",
    "other_outstanding_items",
    "outstanding_checks",
}
_STALE_DAYS = 30  # flag as stale after this many days without an update


class ReconciliationLogIn(BaseModel):
    account_code: str = Field(..., min_length=1)
    account_name: Optional[str] = None
    snapshot_type: str = Field(
        ...,
        description=(
            "One of: account_reconciliation, account_register, bank_deposit_report, "
            "deposits_in_transit, other_outstanding_items, outstanding_checks"
        ),
    )
    reconciled_period: Optional[str] = Field(None, description="YYYY-MM, e.g. '2026-06'")
    gl_balance: Optional[float] = None
    bank_balance: Optional[float] = None
    outstanding_count: Optional[int] = None
    outstanding_total: Optional[float] = None
    notes: Optional[str] = None


@router.get("/reconciliation/status")
async def get_reconciliation_status(request: Request):
    """
    Return the freshness status of all reconciliation snapshot types.
    For each known row, compute days_since_update and a staleness flag.
    Roles: admin, finance, management
    """
    _require_finance(request)
    try:
        rows = (
            db.table("reconciliation_tracking")
            .select(
                "id, account_code, account_name, snapshot_type, reconciled_period, "
                "gl_balance, bank_balance, difference, outstanding_count, "
                "outstanding_total, last_imported_at, entry_method, logged_by, notes, updated_at"
            )
            .order("account_code")
            .execute()
            .data or []
        )

        now = datetime.datetime.now(datetime.timezone.utc)
        result = []
        for r in rows:
            updated = r.get("updated_at") or r.get("last_imported_at")
            days_since: Optional[int] = None
            if updated:
                try:
                    ts = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    days_since = (now - ts).days
                except Exception:
                    pass

            is_point_in_time = r["snapshot_type"] in _POINT_IN_TIME_TYPES
            is_stale = (
                is_point_in_time
                and (days_since is None or days_since >= _STALE_DAYS)
            )

            result.append({
                **r,
                "days_since_update": days_since,
                "is_point_in_time": is_point_in_time,
                "is_stale": is_stale,
                "stale_threshold_days": _STALE_DAYS,
            })

        return {"data": result, "total": len(result), "stale_count": sum(1 for r in result if r["is_stale"])}
    except Exception as e:
        log.error("/finance/reconciliation/status error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve reconciliation status")


@router.post("/reconciliation/log", status_code=201)
async def log_reconciliation(request: Request, body: ReconciliationLogIn):
    """
    Upsert a reconciliation tracking row — either from a Sage export ingestion
    or manually entered by finance staff via the Placeware UI.
    Point-in-time types (account_reconciliation, deposits_in_transit,
    other_outstanding_items, outstanding_checks) replace the existing row.
    Historical types (account_register, bank_deposit_report) append a new row.
    Roles: admin, finance, management
    """
    payload = _require_finance(request)
    logged_by = payload.get("email") or payload.get("sub") or "unknown"

    _valid_types = {
        "account_reconciliation", "account_register", "bank_deposit_report",
        "deposits_in_transit", "other_outstanding_items", "outstanding_checks",
    }
    if body.snapshot_type not in _valid_types:
        raise HTTPException(status_code=422, detail=f"Invalid snapshot_type: {body.snapshot_type!r}")

    row: Dict[str, Any] = {
        "account_code": body.account_code.strip(),
        "account_name": body.account_name,
        "snapshot_type": body.snapshot_type,
        "reconciled_period": body.reconciled_period,
        "gl_balance": body.gl_balance,
        "bank_balance": body.bank_balance,
        "outstanding_count": body.outstanding_count,
        "outstanding_total": body.outstanding_total,
        "last_imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entry_method": "manual",
        "logged_by": str(logged_by)[:200],
        "notes": body.notes[:1000] if body.notes else None,
    }

    try:
        if body.snapshot_type in _POINT_IN_TIME_TYPES:
            # Upsert — one row per account+type
            res = (
                db.table("reconciliation_tracking")
                .upsert(row, on_conflict="account_code,snapshot_type")
                .execute()
            )
        else:
            # Append — historical records accumulate
            res = db.table("reconciliation_tracking").insert(row).execute()

        saved = res.data[0] if res.data else row
        log.info(
            "reconciliation/log: %s/%s logged by %s for period %s",
            body.account_code, body.snapshot_type, logged_by, body.reconciled_period,
        )
        return {"status": "ok", "data": saved}
    except Exception as e:
        log.error("/finance/reconciliation/log error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save reconciliation log")
