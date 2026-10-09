"""
Sales CRM Pipeline Router — ACE
=========================================
Implements Tier-1 Sales & Business Development features derived from the
April 2026 requirements-gathering form:

  • GET  /crm/sales/pipeline          – Kanban board grouped by stage
  • PATCH /crm/sales/leads/{id}/stage – Move a lead to a new pipeline stage
  • POST  /crm/sales/followups        – Create a follow-up reminder
  • GET   /crm/sales/followups/due    – List reminders due within N hours
  • PATCH /crm/sales/followups/{id}   – Update reminder status (done / snoozed)
  • POST  /crm/sales/bulk-message     – Queue a bulk SMS/Email job
  • GET   /crm/sales/bulk-message     – List bulk message jobs
  • GET   /crm/sales/weekly-report    – Generate / retrieve weekly sales report
  • POST  /crm/sales/query            – Plain-language NLQ ("Which clients haven't ordered in 60 days?")
"""

from __future__ import annotations

import logging
import datetime as dt
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.db import db
from src.middleware import verify_jwt, require_role, require_any_role
from src.constants import BOT_NAME, BOT_BRAND

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crm/sales", tags=["CRM Sales"])

# ---------------------------------------------------------------------------
# Allowed stage transitions (pharma-specific pipeline including payment_plan)
# ---------------------------------------------------------------------------
PIPELINE_STAGES: list[str] = [
    "new",
    "qualified",
    "proposal",
    "negotiation",
    "payment_plan",
    "won",
    "lost",
]

STAGE_TRANSITIONS: dict[str, set[str]] = {
    "new":          {"qualified", "lost"},
    "qualified":    {"proposal", "new", "lost"},
    "proposal":     {"negotiation", "qualified", "lost"},
    "negotiation":  {"payment_plan", "won", "proposal", "lost"},
    "payment_plan": {"won", "negotiation", "lost"},
    "won":          set(),
    "lost":         {"new"},   # allow re-engagement
}

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class StageUpdateIn(BaseModel):
    stage: str
    notes: Optional[str] = None


class FollowUpCreateIn(BaseModel):
    lead_id:       Optional[int] = None
    customer_id:   Optional[int] = None
    assigned_rep:  Optional[str] = None       # UUID string
    reminder_type: str = Field(default="follow_up")
    due_at:        str = Field(..., description="ISO-8601 datetime")
    note:          Optional[str] = None


class FollowUpUpdateIn(BaseModel):
    status: str = Field(..., description="pending | done | dismissed | snoozed")
    note:   Optional[str] = None


class BulkMessageIn(BaseModel):
    channel:          str = Field(default="sms",
                                  description="sms | email")
    message_text:     str = Field(..., min_length=1, max_length=4096)
    subject:          Optional[str] = None
    # Explicit selection from the recipient picker:
    #   {"customer_ids": [...], "supplier_ids": [...]}
    # or a segment broadcast: {"facility_type": "hospital"}
    recipient_filter: Optional[dict] = None


class NLQIn(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)


class LeadCreateIn(BaseModel):
    company_name:    str = Field(..., min_length=1, max_length=255)
    contact_person:  Optional[str] = None
    contact_phone:   Optional[str] = None
    product_interest: Optional[List[str]] = None
    stage:           str = Field(default="new")
    expected_value:  Optional[float] = None
    payment_terms:   Optional[str] = None
    notes:           Optional[str] = None
    next_action:     Optional[str] = None
    assigned_rep:    Optional[str] = None   # UUID string


class LeadUpdateIn(BaseModel):
    company_name:    Optional[str] = None
    contact_person:  Optional[str] = None
    contact_phone:   Optional[str] = None
    product_interest: Optional[List[str]] = None
    expected_value:  Optional[float] = None
    payment_terms:   Optional[str] = None
    notes:           Optional[str] = None
    next_action:     Optional[str] = None
    assigned_rep:    Optional[str] = None
    score:           Optional[int] = Field(default=None, ge=0, le=100)
    last_contacted_at: Optional[str] = None   # ISO-8601


class InteractionLogIn(BaseModel):
    interaction_type: str = Field(
        ..., description="call | visit | site_visit | demo | email | whatsapp | meeting"
    )
    summary:         str = Field(..., min_length=1, max_length=2000)
    outcome:         Optional[str] = None
    next_step:       Optional[str] = None
    occurred_at:     Optional[str] = None   # ISO-8601; defaults to now


class SalesTargetIn(BaseModel):
    rep_id:          Optional[str] = None   # UUID; None = team-level target
    period:          str = Field(..., description="YYYY-MM (monthly) or YYYY-Www (weekly)")
    period_type:     str = Field(default="monthly", description="weekly | monthly | quarterly")
    target_value:    float = Field(..., ge=0)
    target_deals:    Optional[int] = None


class SalesTargetUpdateIn(BaseModel):
    target_value:    Optional[float] = None
    target_deals:    Optional[int] = None


# ---------------------------------------------------------------------------
# Helper: safe auth extraction (graceful fallback when state not set)
# ---------------------------------------------------------------------------

def _actor_id(request) -> Optional[str]:  # type: ignore[return]
    try:
        from src.middleware import verify_jwt, require_any_role
        auth = verify_jwt(request)
        return auth.get("sub") or auth.get("user_id")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. Pipeline board — leads grouped by stage
# ---------------------------------------------------------------------------

# Columns added by migration 077 — selected opportunistically
_FULL_LEAD_COLS = (
    "id,company_name,contact_person,contact_phone,product_interest,"
    "stage,score,expected_value,payment_terms,last_contacted_at,"
    "next_action,notes,assigned_rep,created_at,updated_at"
)
# Columns guaranteed to exist from migration 019
_BASE_LEAD_COLS = (
    "id,stage,score,expected_value,assigned_rep,created_at,updated_at"
)


def _select_leads(cols: str, **kwargs) -> list[dict]:
    """Execute a leads select, falling back to base columns if extended ones don't exist yet."""
    try:
        q = db.table("leads").select(cols)
        for method, val in kwargs.items():
            q = getattr(q, method)(**val) if isinstance(val, dict) else getattr(q, method)(val)
        return q.execute().data or []
    except Exception as exc:
        if "does not exist" in str(exc).lower() and cols != _BASE_LEAD_COLS:
            logger.warning("Extended lead columns unavailable, falling back to base cols: %s", exc)
            q = db.table("leads").select(_BASE_LEAD_COLS)
            for method, val in kwargs.items():
                q = getattr(q, method)(**val) if isinstance(val, dict) else getattr(q, method)(val)
            return q.execute().data or []
        raise


@router.get("/pipeline")
def get_pipeline(
    limit: int = Query(default=200, le=500),
    _u=Depends(verify_jwt),
):
    """Return leads grouped by pipeline stage for the Kanban board."""
    try:
        # Try full column set (post-077), fall back to base if migration not yet applied
        try:
            resp = (
                db.table("leads")
                .select(_FULL_LEAD_COLS)
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            leads: list[dict] = resp.data or []
        except Exception as col_err:
            if "does not exist" in str(col_err).lower():
                logger.warning("Pipeline: falling back to base columns (%s)", col_err)
                resp = (
                    db.table("leads")
                    .select(_BASE_LEAD_COLS)
                    .order("updated_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                leads = resp.data or []
            else:
                raise

        board: dict[str, list] = {s: [] for s in PIPELINE_STAGES}
        for lead in leads:
            stage = str(lead.get("stage") or "new")
            if stage not in board:
                board[stage] = []
            board[stage].append(lead)

        return {
            "stages":  PIPELINE_STAGES,
            "board":   board,
            "total":   len(leads),
            "counts":  {s: len(board[s]) for s in PIPELINE_STAGES},
        }
    except Exception as exc:
        logger.error("Pipeline fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch pipeline")


# ---------------------------------------------------------------------------
# 2. Stage transition
# ---------------------------------------------------------------------------

@router.patch("/leads/{lead_id}/stage")
def move_lead_stage(
    lead_id: int,
    payload: StageUpdateIn,
    request=Depends(verify_jwt),   # type: ignore[assignment]
):
    """Move a lead to a new pipeline stage with transition validation."""
    new_stage = payload.stage.strip().lower()
    if new_stage not in PIPELINE_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage '{new_stage}'. Valid stages: {PIPELINE_STAGES}",
        )

    try:
        resp = db.table("leads").select("id,stage").eq("id", lead_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Lead not found")

        current_stage = str(rows[0].get("stage") or "new")
        allowed = STAGE_TRANSITIONS.get(current_stage, set())
        if new_stage != current_stage and new_stage not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Transition not allowed: {current_stage} → {new_stage}",
            )

        update_payload: dict = {
            "stage":      new_stage,
            "updated_at": dt.datetime.utcnow().isoformat() + "Z",
        }
        if payload.notes:
            update_payload["notes"] = payload.notes

        db.table("leads").update(update_payload).eq("id", lead_id).execute()

        return {
            "lead_id": lead_id,
            "from":    current_stage,
            "to":      new_stage,
            "status":  "updated",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Stage transition error for lead %s: %s", lead_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update stage")


# ---------------------------------------------------------------------------
# 3. Create follow-up reminder
# ---------------------------------------------------------------------------

@router.post("/followups", status_code=201)
def create_followup(
    payload: FollowUpCreateIn,
    request=Depends(verify_jwt),   # type: ignore[assignment]
):
    """Schedule a follow-up reminder for a lead or customer."""
    if not payload.lead_id and not payload.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of lead_id or customer_id",
        )

    # Validate ISO-8601
    try:
        dt.datetime.fromisoformat(payload.due_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="due_at must be a valid ISO-8601 datetime")

    row = {
        "lead_id":       payload.lead_id,
        "customer_id":   payload.customer_id,
        "assigned_rep":  payload.assigned_rep,
        "reminder_type": payload.reminder_type,
        "due_at":        payload.due_at,
        "note":          payload.note,
        "status":        "pending",
    }

    try:
        resp = db.table("crm_follow_up_reminders").insert(row).execute()
        data = resp.data or []
        return data[0] if data else {"status": "created"}
    except Exception as exc:
        logger.error("Create follow-up error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create follow-up reminder")


# ---------------------------------------------------------------------------
# 4. List reminders due within N hours (default 24)
# ---------------------------------------------------------------------------

@router.get("/followups/due")
def get_due_followups(
    hours: int = Query(default=24, ge=1, le=720),
    rep_id: Optional[str] = Query(default=None),
    _u=Depends(verify_jwt),
):
    """Return follow-up reminders due within the next `hours` hours."""
    now = dt.datetime.utcnow()
    cutoff = (now + dt.timedelta(hours=hours)).isoformat() + "Z"

    try:
        q = db.table("crm_follow_up_reminders").select(
            "id,lead_id,customer_id,assigned_rep,reminder_type,due_at,note,status,created_at"
        ).eq("status", "pending").lte("due_at", cutoff)

        if rep_id:
            q = q.eq("assigned_rep", rep_id)

        resp = q.order("due_at").limit(100).execute()
        return {"reminders": resp.data or [], "cutoff": cutoff}
    except Exception as exc:
        logger.error("Due followups error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch reminders")


# ---------------------------------------------------------------------------
# 5. Update reminder status
# ---------------------------------------------------------------------------

VALID_REMINDER_STATUSES = {"pending", "done", "dismissed", "snoozed"}


@router.patch("/followups/{reminder_id}")
def update_followup(
    reminder_id: str,
    payload: FollowUpUpdateIn,
    _u=Depends(verify_jwt),
):
    """Mark a reminder as done, dismissed, or snoozed."""
    if payload.status not in VALID_REMINDER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {sorted(VALID_REMINDER_STATUSES)}",
        )

    update_row: dict = {"status": payload.status}
    if payload.note:
        update_row["note"] = payload.note
    if payload.status == "done":
        update_row["completed_at"] = dt.datetime.utcnow().isoformat() + "Z"

    try:
        resp = db.table("crm_follow_up_reminders").update(update_row).eq("id", reminder_id).execute()
        data = resp.data or []
        if not data:
            raise HTTPException(status_code=404, detail="Reminder not found")
        return data[0]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Update reminder error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update reminder")


# ---------------------------------------------------------------------------
# 6. Queue a bulk message job
# ---------------------------------------------------------------------------

VALID_CHANNELS = {"email", "sms"}


@router.post("/bulk-message", status_code=201)
def create_bulk_message(
    payload: BulkMessageIn,
    request=Depends(require_any_role("sales", "management", "crm")),   # type: ignore[assignment]
):
    """Queue a bulk SMS / Email send to selected recipients or a client segment."""
    channel = payload.channel.strip().lower()
    if channel not in VALID_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel '{channel}'. Allowed: {sorted(VALID_CHANNELS)}",
        )

    row = {
        "channel":          channel,
        "message_text":     payload.message_text,
        "subject":          payload.subject,
        "recipient_filter": payload.recipient_filter or {},
        "status":           "queued",
    }

    try:
        resp = db.table("crm_bulk_message_jobs").insert(row).execute()
        data = resp.data or []
        return data[0] if data else {"status": "queued"}
    except Exception as exc:
        logger.error("Bulk message queue error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to queue bulk message")


@router.get("/bulk-message")
def list_bulk_messages(
    limit: int = Query(default=20, le=100),
    _u=Depends(verify_jwt),
):
    """List recent bulk message jobs."""
    try:
        resp = (
            db.table("crm_bulk_message_jobs")
            .select("id,channel,subject,status,recipient_count,sent_count,failed_count,created_at,processed_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.error("List bulk messages error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch bulk message jobs")


# ---------------------------------------------------------------------------
# 7. Weekly sales performance report
# ---------------------------------------------------------------------------

@router.get("/weekly-report")
def get_weekly_report(
    week_start: Optional[str] = Query(
        default=None,
        description="ISO date (YYYY-MM-DD). Defaults to start of current week.",
    ),
    _u=Depends(verify_jwt),
):
    """
    Generate (or retrieve cached) weekly sales performance report.
    Aggregates: leads by stage, new leads, conversions, top products, rep activity.
    """
    # Resolve week window
    today = dt.date.today()
    if week_start:
        try:
            ws = dt.date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="week_start must be YYYY-MM-DD")
    else:
        ws = today - dt.timedelta(days=today.weekday())   # Monday of current week

    we = ws + dt.timedelta(days=6)  # Sunday

    # Check cache
    try:
        cached = (
            db.table("crm_weekly_reports")
            .select("*")
            .eq("week_start", ws.isoformat())
            .limit(1)
            .execute()
        )
        if cached.data:
            return {"source": "cache", "report": cached.data[0]}
    except Exception:
        pass  # Proceed to fresh generation

    # --- Fresh generation ---
    ws_dt = dt.datetime.combine(ws, dt.time.min).isoformat() + "Z"
    we_dt = dt.datetime.combine(we, dt.time.max).isoformat() + "Z"

    try:
        # Leads created this week (try extended cols, fall back if migration 077 not applied)
        try:
            new_leads_resp = (
                db.table("leads")
                .select("id,stage,score,expected_value,assigned_rep,company_name,product_interest")
                .gte("created_at", ws_dt)
                .lte("created_at", we_dt)
                .execute()
            )
        except Exception as _col_err:
            if "does not exist" in str(_col_err).lower():
                new_leads_resp = (
                    db.table("leads")
                    .select("id,stage,score,expected_value,assigned_rep")
                    .gte("created_at", ws_dt)
                    .lte("created_at", we_dt)
                    .execute()
                )
            else:
                raise
        new_leads: list[dict] = new_leads_resp.data or []

        # All active (non-terminal) leads
        active_resp = (
            db.table("leads")
            .select("id,stage,score,expected_value,assigned_rep")
            .not_in("stage", ["won", "lost"])
            .execute()
        )
        active_leads: list[dict] = active_resp.data or []

        # Deals won / lost this week
        won_resp = (
            db.table("leads")
            .select("id,expected_value,assigned_rep")
            .eq("stage", "won")
            .gte("updated_at", ws_dt)
            .lte("updated_at", we_dt)
            .execute()
        )
        lost_resp = (
            db.table("leads")
            .select("id,expected_value,assigned_rep")
            .eq("stage", "lost")
            .gte("updated_at", ws_dt)
            .lte("updated_at", we_dt)
            .execute()
        )

        won_leads  = won_resp.data or []
        lost_leads = lost_resp.data or []

        # --- Aggregation ---
        stage_counts: dict[str, int] = {s: 0 for s in PIPELINE_STAGES}
        for lead in active_leads:
            s = str(lead.get("stage") or "new")
            if s in stage_counts:
                stage_counts[s] += 1

        pipeline_value = sum(float(l.get("expected_value") or 0) for l in active_leads)
        won_value      = sum(float(l.get("expected_value") or 0) for l in won_leads)

        # Product interest frequency
        product_freq: dict[str, int] = {}
        for lead in new_leads:
            for product in (lead.get("product_interest") or []):
                product_freq[product] = product_freq.get(product, 0) + 1

        # Rep activity (leads created this week per rep)
        rep_activity: dict[str, int] = {}
        for lead in new_leads:
            rep = str(lead.get("assigned_rep") or "unassigned")
            rep_activity[rep] = rep_activity.get(rep, 0) + 1

        report_data = {
            "week_start":      ws.isoformat(),
            "week_end":        we.isoformat(),
            "new_leads_count": len(new_leads),
            "active_leads":    len(active_leads),
            "won_count":       len(won_leads),
            "lost_count":      len(lost_leads),
            "pipeline_value":  round(pipeline_value, 2),
            "won_value":       round(won_value, 2),
            "stage_breakdown": stage_counts,
            "top_products":    sorted(product_freq.items(), key=lambda x: -x[1])[:10],
            "rep_activity":    rep_activity,
            "generated_at":    dt.datetime.utcnow().isoformat() + "Z",
        }

        # Cache for the week
        try:
            db.table("crm_weekly_reports").upsert(
                {
                    "week_start":   ws.isoformat(),
                    "week_end":     we.isoformat(),
                    "report_data":  report_data,
                    "generated_at": dt.datetime.utcnow().isoformat() + "Z",
                },
                on_conflict="week_start",
            ).execute()
        except Exception as cache_err:
            logger.warning("Failed to cache weekly report: %s", cache_err)

        return {"source": "live", "report": report_data}

    except Exception as exc:
        logger.error("Weekly report generation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate weekly report")


# ---------------------------------------------------------------------------
# 8. Plain-language NLQ query (Ask ACE)
# ---------------------------------------------------------------------------

# CRM context facts injected into the LLM prompt
_CRM_SYSTEM_PROMPT = (
    f"You are {BOT_NAME}, the sales intelligence assistant for {BOT_BRAND}. "
    "You have access to the company's CRM pipeline data. "
    "Answer the sales rep's question concisely using the pipeline context provided. "
    "If the data is insufficient, say so clearly. "
    "Do not fabricate numbers. "
    "Response must be in plain English suitable for a mobile screen."
)


def _live_crm_context() -> str:
    """Customers (segment, last order, usual gap, sales, balance, risk) and open deals, from crm_hub."""
    try:
        from src.services import crm_hub
        d = crm_hub.customer_directory()
        p = crm_hub.pipeline()
    except Exception as exc:
        logger.warning("Ask ACE live context unavailable: %s", exc)
        return ""
    rows = sorted([c for c in d.get("customers") or [] if c.get("segment") != "never"],
                  key=lambda c: -float(c.get("sales_12m") or 0))[:60]
    lines = [f"Sales data as of {d.get('as_of')}. Customers on file: {d.get('total')}; by segment: {d.get('counts')}.",
             "Top 60 buying customers (name | segment | last order | days since | usual gap days | reorder due in days | "
             "sales 12m | trend % | balance | past due | risk):"]
    for c in rows:
        lines.append(f"{c['name']} | {c.get('segment')} | {c.get('last_order')} | {c.get('days_since_order')} | "
                     f"{round(float(c['avg_gap_days'])) if c.get('avg_gap_days') else '-'} | {c.get('reorder_due_in')} | "
                     f"₦{float(c.get('sales_12m') or 0):,.0f} | {c.get('trend_pct')} | ₦{float(c.get('balance') or 0):,.0f} | "
                     f"₦{float(c.get('overdue') or 0):,.0f} | {'; '.join(c.get('risk_reasons') or []) or '-'}")
    lines.append("Open deals (company | stage | value | last contact):")
    for stage, deals in (p.get("board") or {}).items():
        if stage in ("won", "lost"):
            continue
        for x in deals[:40]:
            lines.append(f"{x.get('company_name')} | {stage} | ₦{float(x.get('expected_value') or 0):,.0f} | {x.get('last_contacted_at') or 'never'}")
    return "\n".join(lines)


def _answer_crm(query_text: str, context: str, user: dict) -> dict:
    from src.services.ace_voice import clean_answer, core_prompt
    answer = ""
    try:
        from src.llm_client import LLMClient
        answer = LLMClient().generate_response(
            context=context, question=query_text,
            instruction=core_prompt(user.get("roles") or ["sales"])
            + "\n\nYou are answering from the CRM data in the context only (customers from ACE Books sales, and the deal pipeline). "
              "If the data doesn't cover the question, say so in one line.",
        )
    except Exception as exc:
        logger.error("NLQ LLM error: %s", exc)
        answer = "I couldn't process that right now. Try again in a moment."
    answer = clean_answer(answer)
    try:
        db.table("crm_nlq_history").insert({"query_text": query_text, "response_text": answer}).execute()
    except Exception:
        pass
    return {"query": query_text, "answer": answer}


@router.post("/query")
def nlq_query(
    payload: NLQIn,
    _u=Depends(verify_jwt),
):
    """
    Answer a plain-language sales question using current pipeline context.
    Example: "Which clients have not ordered in 60 days?"
    """
    query_text = payload.query.strip()

    # Live CRM context (same data as the CRM pages: ACE Books sales + the pipeline)
    live = _live_crm_context()
    if live:
        return _answer_crm(query_text, live, _u)

    # Fallback: lightweight CRM context snapshot for the LLM
    try:
        # Try extended lead columns (post-077), fall back gracefully
        try:
            leads_resp = (
                db.table("leads")
                .select("id,company_name,stage,last_contacted_at,expected_value,assigned_rep,product_interest")
                .order("updated_at", desc=True)
                .limit(100)
                .execute()
            )
        except Exception as _lce:
            if "does not exist" in str(_lce).lower():
                leads_resp = (
                    db.table("leads")
                    .select("id,stage,expected_value,assigned_rep")
                    .order("updated_at", desc=True)
                    .limit(100)
                    .execute()
                )
            else:
                raise
        leads_sample: list[dict] = leads_resp.data or []

        # customers: last_ordered_at / facility_type are extended columns — handle gracefully
        try:
            customers_resp = (
                db.table("customers")
                .select("id,name,last_ordered_at,account_manager,facility_type")
                .order("updated_at", desc=True)
                .limit(50)
                .execute()
            )
        except Exception as _cce:
            if "does not exist" in str(_cce).lower():
                customers_resp = (
                    db.table("customers")
                    .select("id,name")
                    .limit(50)
                    .execute()
                )
            else:
                raise
        customers_sample: list[dict] = customers_resp.data or []

    except Exception as exc:
        logger.error("NLQ context fetch error: %s", exc)
        leads_sample = []
        customers_sample = []

    # Compose context string (lightweight — avoid token bloat)
    today_str = dt.date.today().isoformat()
    context_lines: list[str] = [
        f"Today's date: {today_str}",
        f"Pipeline leads ({len(leads_sample)} shown):",
    ]
    for lead in leads_sample[:30]:
        last_contact = lead.get("last_contacted_at") or "never"
        context_lines.append(
            f"  - {lead.get('company_name') or 'Unknown'} | stage={lead.get('stage')} "
            f"| last_contacted={last_contact} | value=₦{lead.get('expected_value') or 0}"
        )
    context_lines.append(f"\nCustomers ({len(customers_sample)} shown):")
    for cust in customers_sample[:20]:
        last_order = cust.get("last_ordered_at") or "never"
        context_lines.append(
            f"  - {cust.get('name') or 'Unknown'} | type={cust.get('facility_type')} "
            f"| last_ordered={last_order}"
        )

    context = "\n".join(context_lines)

    # Call LLM
    answer = ""
    try:
        from src.llm_client import LLMClient
        llm = LLMClient()
        answer = llm.generate_response(
            context=context,
            question=query_text,
            instruction=_CRM_SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.error("NLQ LLM error: %s", exc)
        answer = "I could not process that query right now. Please try again shortly."
    from src.services.ace_voice import clean_answer
    answer = clean_answer(answer)

    # Log query to history (best-effort)
    try:
        db.table("crm_nlq_history").insert(
            {"query_text": query_text, "response_text": answer}
        ).execute()
    except Exception:
        pass

    return {"query": query_text, "answer": answer}


# ---------------------------------------------------------------------------
# 9. Sales rep leaderboard (Tier 2)
# ---------------------------------------------------------------------------

@router.get("/leaderboard")
def get_leaderboard(
    days: int = Query(default=30, ge=1, le=365),
    _u=Depends(verify_jwt),
):
    """
    Sales rep leaderboard: ranked by deals won, pipeline value, and activity
    over the last `days` days.
    """
    since = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat() + "Z"

    try:
        # All leads updated in the window
        resp = (
            db.table("leads")
            .select("id,stage,expected_value,assigned_rep,created_at,updated_at")
            .gte("updated_at", since)
            .execute()
        )
        leads: list[dict] = resp.data or []
    except Exception as exc:
        logger.error("Leaderboard fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch leaderboard data")

    # Aggregate per rep
    rep_stats: dict[str, dict] = {}

    def _rep_entry() -> dict:
        return {
            "rep_id": "",
            "won_count": 0,
            "won_value": 0.0,
            "lost_count": 0,
            "active_count": 0,
            "pipeline_value": 0.0,
            "total_touched": 0,
        }

    for lead in leads:
        rep = str(lead.get("assigned_rep") or "unassigned")
        if rep not in rep_stats:
            rep_stats[rep] = _rep_entry()
            rep_stats[rep]["rep_id"] = rep

        stage = str(lead.get("stage") or "new")
        value = float(lead.get("expected_value") or 0)
        rep_stats[rep]["total_touched"] += 1

        if stage == "won":
            rep_stats[rep]["won_count"] += 1
            rep_stats[rep]["won_value"] += value
        elif stage == "lost":
            rep_stats[rep]["lost_count"] += 1
        else:
            rep_stats[rep]["active_count"] += 1
            rep_stats[rep]["pipeline_value"] += value

    # Compute score: won_count * 3 + active_count * 1
    for entry in rep_stats.values():
        entry["score"] = entry["won_count"] * 3 + entry["active_count"]
        entry["won_value"] = round(entry["won_value"], 2)
        entry["pipeline_value"] = round(entry["pipeline_value"], 2)

    ranked = sorted(rep_stats.values(), key=lambda x: -x["score"])
    for i, entry in enumerate(ranked):
        entry["rank"] = i + 1

    return {
        "period_days": days,
        "since": since,
        "leaderboard": ranked,
        "total_reps": len(ranked),
    }


# ---------------------------------------------------------------------------
# 10. Dispatch a bulk message job (Tier 2)
# ---------------------------------------------------------------------------

@router.post("/bulk-message/{job_id}/dispatch")
def dispatch_bulk_message(
    job_id: str,
    request=Depends(require_any_role("sales", "management", "crm")),   # type: ignore[assignment]
):
    """
    Trigger immediate dispatch of a queued bulk message job.
    Requires TERMII_API_KEY (SMS) or EMAIL_FROM/EMAIL_PASS (email) to be set.
    """
    try:
        resp = db.table("crm_bulk_message_jobs").select("*").eq("id", job_id).limit(1).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Dispatch fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch job")

    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    job = rows[0]
    if job.get("status") not in ("queued", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already '{job.get('status')}' — only queued/failed jobs can be dispatched",
        )

    try:
        from src.services.messaging import dispatch_job
        result = dispatch_job(job)
    except Exception as exc:
        logger.error("Dispatch error for job %s: %s", job_id, exc)
        db.table("crm_bulk_message_jobs").update(
            {"status": "failed", "processed_at": dt.datetime.utcnow().isoformat() + "Z"}
        ).eq("id", job_id).execute()
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {exc}")

    db.table("crm_bulk_message_jobs").update(
        {
            "status":         result.get("status", "completed"),
            "sent_count":     result.get("sent", 0),
            "failed_count":   result.get("failed", 0),
            "recipient_count": result.get("total", 0),
            "processed_at":   dt.datetime.utcnow().isoformat() + "Z",
        }
    ).eq("id", job_id).execute()

    return {"job_id": job_id, **result}


# ===========================================================================
# LEAD CRUD (Gap-fill: reps must be able to create & update leads from CRM)
# ===========================================================================

# ---------------------------------------------------------------------------
# C1. Create a new lead
# ---------------------------------------------------------------------------

@router.post("/leads", status_code=201)
def create_lead(
    payload: LeadCreateIn,
    request=Depends(verify_jwt),  # type: ignore[assignment]
):
    """Create a new CRM lead with enriched pharma fields."""
    stage = payload.stage.strip().lower()
    if stage not in PIPELINE_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage '{stage}'. Valid: {PIPELINE_STAGES}",
        )

    row: dict = {
        "company_name":    payload.company_name,
        "contact_person":  payload.contact_person,
        "contact_phone":   payload.contact_phone,
        "product_interest": payload.product_interest or [],
        "stage":           stage,
        "expected_value":  payload.expected_value,
        "payment_terms":   payload.payment_terms,
        "notes":           payload.notes,
        "next_action":     payload.next_action,
        "assigned_rep":    payload.assigned_rep,
        "created_at":      dt.datetime.utcnow().isoformat() + "Z",
        "updated_at":      dt.datetime.utcnow().isoformat() + "Z",
    }
    # Remove None values so the DB default is used
    row = {k: v for k, v in row.items() if v is not None}

    try:
        resp = db.table("leads").insert(row).execute()
        created = resp.data[0] if resp.data else row
        return {"status": "created", "lead": created}
    except Exception as exc:
        logger.error("Lead create error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create lead")


# ---------------------------------------------------------------------------
# C2. Update lead fields (company info, contact, product interest, etc.)
# ---------------------------------------------------------------------------

@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: int,
    payload: LeadUpdateIn,
    request=Depends(verify_jwt),  # type: ignore[assignment]
):
    """Update enriched fields on an existing lead."""
    updates: dict = {
        k: v for k, v in payload.model_dump(exclude_none=True).items()
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    updates["updated_at"] = dt.datetime.utcnow().isoformat() + "Z"

    # Validate score range if provided
    if "score" in updates:
        score = int(updates["score"])
        if not 0 <= score <= 100:
            raise HTTPException(status_code=400, detail="score must be 0-100")

    try:
        resp = db.table("leads").select("id").eq("id", lead_id).limit(1).execute()
        if not (resp.data or []):
            raise HTTPException(status_code=404, detail="Lead not found")

        db.table("leads").update(updates).eq("id", lead_id).execute()
        return {"status": "updated", "lead_id": lead_id, "updated_fields": list(updates.keys())}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Lead update error for %s: %s", lead_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update lead")


# ===========================================================================
# INTERACTION / ACTIVITY LOG
# (Gap-fill: survey Q3 — record calls, visits, site visits, demos vs notepad)
# ===========================================================================

# ---------------------------------------------------------------------------
# I1. Log an interaction against a lead
# ---------------------------------------------------------------------------

VALID_INTERACTION_TYPES = {
    "call", "visit", "site_visit", "demo", "email", "whatsapp", "meeting",
}


@router.post("/leads/{lead_id}/interactions", status_code=201)
def log_interaction(
    lead_id: int,
    payload: InteractionLogIn,
    request=Depends(verify_jwt),  # type: ignore[assignment]
):
    """
    Record a client interaction (call, visit, demo, etc.) against a lead.
    Also updates leads.last_contacted_at automatically.
    """
    itype = payload.interaction_type.strip().lower()
    if itype not in VALID_INTERACTION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interaction_type '{itype}'. Valid: {sorted(VALID_INTERACTION_TYPES)}",
        )

    # Verify lead exists
    try:
        chk = db.table("leads").select("id").eq("id", lead_id).limit(1).execute()
        if not (chk.data or []):
            raise HTTPException(status_code=404, detail="Lead not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Interaction lead check error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to verify lead")

    occurred_at = payload.occurred_at or (dt.datetime.utcnow().isoformat() + "Z")
    logged_by: Optional[str] = None
    try:
        auth = request if isinstance(request, dict) else {}
        logged_by = auth.get("sub") or auth.get("user_id")
    except Exception:
        pass

    row: dict = {
        "lead_id":          lead_id,
        "interaction_type": itype,
        "summary":          payload.summary,
        "outcome":          payload.outcome,
        "next_step":        payload.next_step,
        "occurred_at":      occurred_at,
        "logged_by":        logged_by,
        "created_at":       dt.datetime.utcnow().isoformat() + "Z",
    }
    row = {k: v for k, v in row.items() if v is not None}

    try:
        resp = db.table("crm_interaction_log").insert(row).execute()
        created = resp.data[0] if resp.data else row

        # Update last_contacted_at on lead
        db.table("leads").update(
            {"last_contacted_at": occurred_at, "updated_at": dt.datetime.utcnow().isoformat() + "Z"}
        ).eq("id", lead_id).execute()

        return {"status": "logged", "interaction": created}
    except Exception as exc:
        logger.error("Interaction log error for lead %s: %s", lead_id, exc)
        raise HTTPException(status_code=500, detail="Failed to log interaction")


# ---------------------------------------------------------------------------
# I2. List interactions for a lead (activity timeline)
# ---------------------------------------------------------------------------

@router.get("/leads/{lead_id}/interactions")
def list_interactions(
    lead_id: int,
    limit: int = Query(default=50, le=200),
    _u=Depends(verify_jwt),
):
    """Return the full interaction history for a lead, newest first."""
    try:
        resp = (
            db.table("crm_interaction_log")
            .select("id,interaction_type,summary,outcome,next_step,occurred_at,logged_by,created_at")
            .eq("lead_id", lead_id)
            .order("occurred_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"lead_id": lead_id, "interactions": resp.data or [], "count": len(resp.data or [])}
    except Exception as exc:
        logger.error("Interaction list error for lead %s: %s", lead_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch interactions")


# ===========================================================================
# SALES TARGETS
# (Gap-fill: survey Q6 — weekly/monthly/quarterly targets reviewed by MD/Finance)
# ===========================================================================

VALID_PERIOD_TYPES = {"weekly", "monthly", "quarterly"}


@router.post("/targets", status_code=201)
def create_target(
    payload: SalesTargetIn,
    request=Depends(require_any_role("sales", "management", "crm")),  # type: ignore[assignment]
):
    """
    Set a sales target for a rep or the whole team.
    `period` format: YYYY-MM for monthly, YYYY-Www for weekly (e.g. 2026-W16),
    YYYY-Qn for quarterly (e.g. 2026-Q2).
    """
    ptype = payload.period_type.strip().lower()
    if ptype not in VALID_PERIOD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period_type '{ptype}'. Valid: {sorted(VALID_PERIOD_TYPES)}",
        )

    row: dict = {
        "rep_id":         payload.rep_id,
        "period":         payload.period.strip(),
        "period_type":    ptype,
        "target_value":   payload.target_value,
        "target_deals":   payload.target_deals,
        "created_at":     dt.datetime.utcnow().isoformat() + "Z",
        "updated_at":     dt.datetime.utcnow().isoformat() + "Z",
    }
    row = {k: v for k, v in row.items() if v is not None}

    try:
        resp = db.table("crm_sales_targets").insert(row).execute()
        return {"status": "created", "target": resp.data[0] if resp.data else row}
    except Exception as exc:
        logger.error("Target create error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create target")


@router.get("/targets")
def list_targets(
    period: Optional[str] = Query(default=None),
    rep_id: Optional[str] = Query(default=None),
    _u=Depends(verify_jwt),
):
    """List sales targets, optionally filtered by period or rep."""
    try:
        q = db.table("crm_sales_targets").select(
            "id,rep_id,period,period_type,target_value,target_deals,created_at,updated_at"
        )
        if period:
            q = q.eq("period", period)
        if rep_id:
            q = q.eq("rep_id", rep_id)
        resp = q.order("period", desc=True).limit(200).execute()
        return {"targets": resp.data or [], "count": len(resp.data or [])}
    except Exception as exc:
        logger.error("Target list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch targets")


@router.patch("/targets/{target_id}")
def update_target(
    target_id: str,
    payload: SalesTargetUpdateIn,
    request=Depends(require_any_role("sales", "management", "crm")),  # type: ignore[assignment]
):
    """Update a target's value or deal count."""
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = dt.datetime.utcnow().isoformat() + "Z"

    try:
        chk = db.table("crm_sales_targets").select("id").eq("id", target_id).limit(1).execute()
        if not (chk.data or []):
            raise HTTPException(status_code=404, detail="Target not found")
        db.table("crm_sales_targets").update(updates).eq("id", target_id).execute()
        return {"status": "updated", "target_id": target_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Target update error %s: %s", target_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update target")


@router.get("/targets/vs-actuals")
def targets_vs_actuals(
    period: str = Query(..., description="e.g. 2026-04 (monthly) or 2026-W16 (weekly)"),
    _u=Depends(verify_jwt),
):
    """
    Compare sales targets against actuals (won deals) for a given period.
    Returns per-rep breakdown: target_value, actual_value, attainment %.
    """
    # Determine date range from period string
    try:
        if len(period) == 7 and period[4] == "-" and period[5] != "W" and period[5] != "Q":
            # YYYY-MM monthly
            year, month = int(period[:4]), int(period[5:7])
            ws = dt.date(year, month, 1)
            import calendar
            we = dt.date(year, month, calendar.monthrange(year, month)[1])
        elif "W" in period.upper():
            # YYYY-Www
            clean = period.upper().replace("-W", "W")
            ws = dt.datetime.strptime(clean + "1", "%YW%W%w").date()
            we = ws + dt.timedelta(days=6)
        elif "Q" in period.upper():
            # YYYY-Qn
            year = int(period[:4])
            qnum = int(period[-1])
            q_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
            q_ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
            ws = dt.date(year, *q_starts[qnum])
            we = dt.date(year, *q_ends[qnum])
        else:
            raise ValueError("Unrecognised period format")
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot parse period '{period}'. Use YYYY-MM, YYYY-Www, or YYYY-Qn: {exc}",
        )

    ws_iso = ws.isoformat()
    we_iso = we.isoformat()

    # Fetch targets for this period
    targets: list[dict] = []
    try:
        t_resp = db.table("crm_sales_targets").select("*").eq("period", period).execute()
        targets = t_resp.data or []
    except Exception as exc:
        logger.warning("Targets fetch error: %s", exc)

    # Fetch won deals in this date window
    actuals: list[dict] = []
    try:
        a_resp = (
            db.table("leads")
            .select("id,expected_value,assigned_rep")
            .eq("stage", "won")
            .gte("updated_at", ws_iso)
            .lte("updated_at", we_iso + "T23:59:59Z")
            .execute()
        )
        actuals = a_resp.data or []
    except Exception as exc:
        logger.warning("Actuals fetch error: %s", exc)

    # Aggregate actuals per rep
    actual_by_rep: dict[str, float] = {}
    for deal in actuals:
        rep = str(deal.get("assigned_rep") or "unassigned")
        actual_by_rep[rep] = actual_by_rep.get(rep, 0) + float(deal.get("expected_value") or 0)

    # Build comparison rows
    rows: list[dict] = []
    for t in targets:
        rep = t.get("rep_id") or "team"
        actual = actual_by_rep.get(rep, 0.0)
        tval = float(t.get("target_value") or 0)
        rows.append({
            "rep_id":      rep,
            "period":      period,
            "target_value": round(tval, 2),
            "actual_value": round(actual, 2),
            "attainment_pct": round((actual / tval * 100) if tval else 0, 1),
            "target_deals":  t.get("target_deals"),
        })

    # Reps with actuals but no set target
    for rep, actual in actual_by_rep.items():
        if rep not in {r["rep_id"] for r in rows}:
            rows.append({
                "rep_id":       rep,
                "period":       period,
                "target_value": None,
                "actual_value": round(actual, 2),
                "attainment_pct": None,
                "target_deals":  None,
            })

    return {
        "period":      period,
        "period_start": ws_iso,
        "period_end":   we_iso,
        "rows":        sorted(rows, key=lambda r: -(r["actual_value"] or 0)),
        "total_target": round(sum(r["target_value"] or 0 for r in rows), 2),
        "total_actual": round(sum(r["actual_value"] or 0 for r in rows), 2),
    }


# ===========================================================================
# TIER 3 ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# 11. Pre-call intelligence brief (Tier 3)
# ---------------------------------------------------------------------------

_BRIEF_SYSTEM_PROMPT = (
    f"You are {BOT_NAME}, the sales intelligence assistant for {BOT_BRAND}. "
    "Generate a concise pre-call intelligence brief (4-6 bullet points) for a sales rep who is about to call this client. "
    "Include: their stage in the pipeline, key products they are interested in, "
    "last contact date, any open reminders, recommended next talking points, and potential objection to prepare for. "
    "Keep language professional, action-oriented, and mobile-friendly. "
    "This is a pharma distribution company — maintain compliance language."
)


@router.get("/leads/{lead_id}/brief")
def get_precall_brief(
    lead_id: int,
    _u=Depends(verify_jwt),
):
    """
    Generate a pre-call intelligence brief for a specific lead.
    Aggregates lead data, customer info, recent reminders, and purchase history,
    then passes to the LLM for a structured call-prep summary.
    """
    # ── 1. Fetch lead ──────────────────────────────────────────────────────
    try:
        try:
            lead_resp = (
                db.table("leads")
                .select(_FULL_LEAD_COLS)
                .eq("id", lead_id)
                .limit(1)
                .execute()
            )
        except Exception as _le:
            if "does not exist" in str(_le).lower():
                lead_resp = (
                    db.table("leads")
                    .select(_BASE_LEAD_COLS)
                    .eq("id", lead_id)
                    .limit(1)
                    .execute()
                )
            else:
                raise
        leads_data = lead_resp.data or []
    except Exception as exc:
        logger.error("Brief: lead fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch lead")

    if not leads_data:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = leads_data[0]

    # ── 2. Fetch linked customer (by company_name match) ───────────────────
    customer: dict = {}
    company_name = lead.get("company_name", "")
    if company_name:
        try:
            cust_resp = (
                db.table("customers")
                .select("id,name,phone,email,facility_type,last_ordered_at,payment_terms_days")
                .ilike("name", f"%{company_name}%")
                .limit(1)
                .execute()
            )
            customer = (cust_resp.data or [{}])[0]
        except Exception:
            customer = {}

    # ── 3. Recent reminders for this lead ─────────────────────────────────
    reminders: list[dict] = []
    try:
        rem_resp = (
            db.table("crm_follow_up_reminders")
            .select("reminder_type,due_at,note,status")
            .eq("lead_id", lead_id)
            .order("due_at", desc=True)
            .limit(3)
            .execute()
        )
        reminders = rem_resp.data or []
    except Exception:
        pass

    # ── 4. Recent invoices / purchase history ─────────────────────────────
    recent_invoices: list[dict] = []
    cust_id = customer.get("id")
    if cust_id:
        try:
            inv_resp = (
                db.table("sales_invoices")
                .select("id,invoice_date,total_amount,status")
                .eq("customer_id", cust_id)
                .order("invoice_date", desc=True)
                .limit(5)
                .execute()
            )
            recent_invoices = inv_resp.data or []
        except Exception:
            pass

    # ── 5. Build context string for LLM ───────────────────────────────────
    lines = [
        f"Company: {lead.get('company_name') or 'Unknown'}",
        f"Contact: {lead.get('contact_person') or 'N/A'} | Phone: {lead.get('contact_phone') or 'N/A'}",
        f"Pipeline Stage: {lead.get('stage') or 'new'}",
        f"Expected Deal Value: ₦{lead.get('expected_value') or 0:,}",
        f"Products of Interest: {', '.join(lead.get('product_interest') or []) or 'None specified'}",
        f"Last Contacted: {lead.get('last_contacted_at') or 'Never'}",
        f"Next Action: {lead.get('next_action') or 'Not set'}",
        f"Notes: {lead.get('notes') or 'None'}",
    ]
    if customer:
        lines += [
            f"\nCustomer Profile:",
            f"  Facility Type: {customer.get('facility_type') or 'Unknown'}",
            f"  Last Ordered: {customer.get('last_ordered_at') or 'Never'}",
            f"  Payment Terms: {customer.get('payment_terms_days', 30)} days",
        ]
    if reminders:
        lines.append("\nOpen Reminders:")
        for r in reminders:
            lines.append(f"  - [{r.get('status')}] {r.get('reminder_type')} due {r.get('due_at', '')[:10]}: {r.get('note') or ''}")
    if recent_invoices:
        lines.append("\nRecent Invoices:")
        for inv in recent_invoices:
            lines.append(
                f"  - #{inv.get('id')} | {inv.get('invoice_date', '')[:10]} "
                f"| ₦{inv.get('total_amount') or 0:,} | {inv.get('status')}"
            )

    context = "\n".join(lines)

    # ── 6. Generate AI brief ───────────────────────────────────────────────
    ai_brief = ""
    try:
        from src.llm_client import LLMClient
        llm = LLMClient()
        ai_brief = llm.generate_response(
            context=context,
            question="Generate a pre-call intelligence brief for this client.",
            instruction=_BRIEF_SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.error("Brief LLM error: %s", exc)
        ai_brief = "AI brief unavailable — review the client data above before calling."

    return {
        "lead_id":         lead_id,
        "lead":            lead,
        "customer":        customer,
        "recent_reminders": reminders,
        "recent_invoices": recent_invoices,
        "ai_brief":        ai_brief,
        "generated_at":    dt.datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# 12. Product availability check from lead card (Tier 3)
# ---------------------------------------------------------------------------

@router.get("/leads/{lead_id}/product-availability")
def get_product_availability(
    lead_id: int,
    _u=Depends(verify_jwt),
):
    """
    Check current inventory availability for a lead's product_interest list.
    Queries the inventory table for stock levels of each product.
    """
    # Get product_interest from lead (requires migration 077)
    try:
        try:
            lead_resp = (
                db.table("leads")
                .select("id,product_interest,company_name")
                .eq("id", lead_id)
                .limit(1)
                .execute()
            )
            lead_data = (lead_resp.data or [{}])[0]
            products = lead_data.get("product_interest") or []
        except Exception as _pe:
            if "does not exist" in str(_pe).lower():
                return {
                    "lead_id": lead_id,
                    "note": "product_interest column not available. Run migration 077.",
                    "availability": [],
                }
            raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Product availability lead fetch: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch lead products")

    if not lead_data:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not products:
        return {"lead_id": lead_id, "availability": [], "note": "No products of interest recorded for this lead."}

    # Query inventory for each product
    availability: list[dict] = []
    for product_name in products:
        try:
            inv_resp = (
                db.table("inventory")
                .select("id,name,sku,quantity_on_hand,unit,reorder_level,storage_location,expiry_date,batch_number")
                .ilike("name", f"%{product_name}%")
                .limit(5)
                .execute()
            )
            rows = inv_resp.data or []
            if rows:
                for row in rows:
                    qty = float(row.get("quantity_on_hand") or 0)
                    reorder = float(row.get("reorder_level") or 0)
                    availability.append({
                        "product_query": product_name,
                        "name":         row.get("name"),
                        "sku":          row.get("sku"),
                        "quantity":     qty,
                        "unit":         row.get("unit"),
                        "status":       "in_stock" if qty > reorder else ("low_stock" if qty > 0 else "out_of_stock"),
                        "location":     row.get("storage_location"),
                        "expiry":       row.get("expiry_date"),
                        "batch":        row.get("batch_number"),
                    })
            else:
                availability.append({
                    "product_query": product_name,
                    "status": "not_found",
                    "quantity": 0,
                })
        except Exception as inv_exc:
            logger.warning("Inventory check for '%s' failed: %s", product_name, inv_exc)
            availability.append({"product_query": product_name, "status": "error", "error": str(inv_exc)})

    return {
        "lead_id":      lead_id,
        "company":      lead_data.get("company_name"),
        "products_checked": len(products),
        "availability": availability,
        "checked_at":   dt.datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# 13. Client purchase history from Sage (Tier 3)
# ---------------------------------------------------------------------------

@router.get("/leads/{lead_id}/purchase-history")
def get_purchase_history(
    lead_id: int,
    limit: int = Query(default=20, le=100),
    _u=Depends(verify_jwt),
):
    """
    Retrieve Sage-sourced purchase history for the customer linked to a lead.
    Matches by company_name against the customers table, then queries sales_invoices.
    """
    # Get lead's company_name
    try:
        try:
            lead_resp = (
                db.table("leads")
                .select("id,company_name,contact_person")
                .eq("id", lead_id)
                .limit(1)
                .execute()
            )
            lead_data = (lead_resp.data or [{}])[0]
        except Exception as _le:
            if "does not exist" in str(_le).lower():
                return {
                    "lead_id": lead_id,
                    "note": "company_name column not available. Run migration 077.",
                    "invoices": [],
                }
            raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Purchase history lead fetch: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch lead")

    if not lead_data:
        raise HTTPException(status_code=404, detail="Lead not found")

    company = lead_data.get("company_name") or ""

    # Find matching customer
    customer: dict = {}
    if company:
        try:
            cust_resp = (
                db.table("customers")
                .select("id,name,email,phone")
                .ilike("name", f"%{company}%")
                .limit(1)
                .execute()
            )
            customer = (cust_resp.data or [{}])[0]
        except Exception:
            pass

    cust_id = customer.get("id")

    # Fetch invoices
    invoices: list[dict] = []
    invoice_lines: list[dict] = []

    if cust_id:
        try:
            inv_resp = (
                db.table("sales_invoices")
                .select("id,invoice_number,invoice_date,total_amount,outstanding_amount,status,due_date")
                .eq("customer_id", cust_id)
                .order("invoice_date", desc=True)
                .limit(limit)
                .execute()
            )
            invoices = inv_resp.data or []
        except Exception as exc:
            logger.warning("sales_invoices query failed: %s", exc)

        # Get line items for the most recent invoice
        if invoices:
            first_inv_id = invoices[0].get("id")
            try:
                lines_resp = (
                    db.table("sales_invoice_lines")
                    .select("description,quantity,unit_price,line_total,product_code")
                    .eq("invoice_id", first_inv_id)
                    .execute()
                )
                invoice_lines = lines_resp.data or []
            except Exception:
                pass

    total_spend = sum(float(inv.get("total_amount") or 0) for inv in invoices)
    outstanding  = sum(float(inv.get("outstanding_amount") or 0) for inv in invoices)

    return {
        "lead_id":         lead_id,
        "company":         lead_data.get("company_name"),
        "customer":        customer,
        "invoice_count":   len(invoices),
        "total_spend":     round(total_spend, 2),
        "outstanding_ar":  round(outstanding, 2),
        "invoices":        invoices,
        "latest_invoice_lines": invoice_lines,
        "fetched_at":      dt.datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# 14. Weekly report PDF download (Tier 3)
# ---------------------------------------------------------------------------

def _build_report_pdf(report: dict) -> bytes:
    """Build a PDF from weekly report data using reportlab."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style  = ParagraphStyle("Title2",  parent=styles["Title"],  fontSize=18, spaceAfter=6)
    h2_style     = ParagraphStyle("H2",      parent=styles["Heading2"], fontSize=13, spaceAfter=4)
    body_style   = ParagraphStyle("Body",    parent=styles["Normal"],  fontSize=10, spaceAfter=2)
    footer_style = ParagraphStyle("Footer",  parent=styles["Normal"],  fontSize=8, textColor=colors.grey)

    BRAND_GREEN = colors.HexColor("#16a34a")
    HEADER_BG   = colors.HexColor("#f0fdf4")
    ALT_ROW_BG  = colors.HexColor("#f9fafb")

    def currency(v: float) -> str:
        return f"\u20a6{v / 1_000_000:.2f}M" if v >= 1_000_000 else f"\u20a6{v / 1_000:.1f}k"

    elements = []

    # ── Header ─────────────────────────────────────────────────────────────
    elements.append(Paragraph(f"{BOT_BRAND} — Weekly Sales Report", title_style))
    elements.append(Paragraph(
        f"Period: {report.get('week_start')} to {report.get('week_end')} &nbsp;&nbsp; "
        f"Generated: {report.get('generated_at', '')[:19].replace('T', ' ')} UTC",
        body_style,
    ))
    elements.append(HRFlowable(width="100%", thickness=2, color=BRAND_GREEN, spaceAfter=12))

    # ── KPI Summary ────────────────────────────────────────────────────────
    elements.append(Paragraph("Key Performance Indicators", h2_style))
    kpi_data = [
        ["Metric", "Value"],
        ["New Leads (this week)",  str(report.get("new_leads_count", 0))],
        ["Active Leads",           str(report.get("active_leads", 0))],
        ["Deals Won (this week)",  str(report.get("won_count", 0))],
        ["Deals Lost (this week)", str(report.get("lost_count", 0))],
        ["Pipeline Value",         currency(float(report.get("pipeline_value", 0)))],
        ["Won Value (this week)",  currency(float(report.get("won_value", 0)))],
    ]
    kpi_table = Table(kpi_data, colWidths=[9 * cm, 7 * cm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), BRAND_GREEN),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 10),
        ("BACKGROUND",   (0, 1), (-1, -1), ALT_ROW_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_BG]),
        ("GRID",         (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 16))

    # ── Stage Breakdown ────────────────────────────────────────────────────
    stage_breakdown = report.get("stage_breakdown", {})
    if stage_breakdown:
        elements.append(Paragraph("Active Leads by Stage", h2_style))
        stage_data = [["Stage", "Count"]]
        stage_labels = {
            "new": "New Lead", "qualified": "Qualified", "proposal": "Proposal Sent",
            "negotiation": "Negotiation", "payment_plan": "Payment Plan",
            "won": "Won", "lost": "Lost",
        }
        for stage, count in stage_breakdown.items():
            if count > 0:
                stage_data.append([stage_labels.get(stage, stage.title()), str(count)])
        if len(stage_data) > 1:
            stage_table = Table(stage_data, colWidths=[9 * cm, 7 * cm])
            stage_table.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, 0), BRAND_GREEN),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_BG]),
                ("GRID",         (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("LEFTPADDING",  (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ]))
            elements.append(stage_table)
            elements.append(Spacer(1, 16))

    # ── Top Products ───────────────────────────────────────────────────────
    top_products = report.get("top_products", [])
    if top_products:
        elements.append(Paragraph("Top Products of Interest", h2_style))
        prod_data = [["Product", "Lead Count"]]
        for product, count in top_products[:10]:
            prod_data.append([str(product), str(count)])
        prod_table = Table(prod_data, colWidths=[11 * cm, 5 * cm])
        prod_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), BRAND_GREEN),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_BG]),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ]))
        elements.append(prod_table)
        elements.append(Spacer(1, 16))

    # ── Rep Activity ───────────────────────────────────────────────────────
    rep_activity = report.get("rep_activity", {})
    if rep_activity:
        elements.append(Paragraph("Rep Activity (New Leads Created)", h2_style))
        rep_data = [["Sales Rep", "Leads Created"]]
        for rep, count in sorted(rep_activity.items(), key=lambda x: -x[1]):
            rep_label = rep[:20] if len(rep) > 20 else rep
            rep_data.append([rep_label, str(count)])
        rep_table = Table(rep_data, colWidths=[11 * cm, 5 * cm])
        rep_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), BRAND_GREEN),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_BG]),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ]))
        elements.append(rep_table)
        elements.append(Spacer(1, 16))

    # ── Footer ─────────────────────────────────────────────────────────────
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey, spaceAfter=6))
    elements.append(Paragraph(
        f"Confidential — {BOT_BRAND} Internal Sales Report. "
        "For authorised personnel only. NAFDAC-regulated distribution data.",
        footer_style,
    ))

    doc.build(elements)
    buf.seek(0)
    return buf.read()


@router.get("/weekly-report/pdf")
def download_weekly_report_pdf(
    week_start: Optional[str] = Query(default=None),
    _u=Depends(verify_jwt),
):
    """
    Download the weekly sales report as a formatted PDF (reportlab).
    Uses cached report if available; generates fresh if not.
    """
    from fastapi.responses import Response as FastAPIResponse

    # Re-use the existing weekly report logic to get data
    today = dt.date.today()
    if week_start:
        try:
            ws = dt.date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="week_start must be YYYY-MM-DD")
    else:
        ws = today - dt.timedelta(days=today.weekday())
    we = ws + dt.timedelta(days=6)

    report_data: dict = {}

    # Try cache first
    try:
        cached = (
            db.table("crm_weekly_reports")
            .select("report_data")
            .eq("week_start", ws.isoformat())
            .limit(1)
            .execute()
        )
        if cached.data:
            report_data = cached.data[0].get("report_data") or {}
    except Exception:
        pass

    # Generate fresh if no cache
    if not report_data:
        ws_dt = dt.datetime.combine(ws, dt.time.min).isoformat() + "Z"
        we_dt = dt.datetime.combine(we, dt.time.max).isoformat() + "Z"
        try:
            try:
                new_leads_resp = (
                    db.table("leads")
                    .select("id,stage,score,expected_value,assigned_rep,company_name,product_interest")
                    .gte("created_at", ws_dt).lte("created_at", we_dt).execute()
                )
            except Exception as _c:
                if "does not exist" in str(_c).lower():
                    new_leads_resp = (
                        db.table("leads")
                        .select("id,stage,score,expected_value,assigned_rep")
                        .gte("created_at", ws_dt).lte("created_at", we_dt).execute()
                    )
                else:
                    raise
            new_leads = new_leads_resp.data or []
            active_resp = (
                db.table("leads").select("id,stage,expected_value,assigned_rep")
                .not_in("stage", ["won", "lost"]).execute()
            )
            active_leads = active_resp.data or []
            won_leads  = (db.table("leads").select("id,expected_value,assigned_rep").eq("stage", "won").gte("updated_at", ws_dt).lte("updated_at", we_dt).execute().data or [])
            lost_leads = (db.table("leads").select("id").eq("stage", "lost").gte("updated_at", ws_dt).lte("updated_at", we_dt).execute().data or [])

            stage_counts: dict[str, int] = {s: 0 for s in PIPELINE_STAGES}
            for lead in active_leads:
                s = str(lead.get("stage") or "new")
                if s in stage_counts:
                    stage_counts[s] += 1

            product_freq: dict[str, int] = {}
            rep_activity: dict[str, int] = {}
            for lead in new_leads:
                for p in (lead.get("product_interest") or []):
                    product_freq[p] = product_freq.get(p, 0) + 1
                rep = str(lead.get("assigned_rep") or "unassigned")
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
            logger.error("PDF report generation error: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to generate report data for PDF")

    try:
        pdf_bytes = _build_report_pdf(report_data)
    except Exception as exc:
        logger.error("PDF build error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to build PDF")

    filename = f"sales_report_{ws.isoformat()}.pdf"
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
