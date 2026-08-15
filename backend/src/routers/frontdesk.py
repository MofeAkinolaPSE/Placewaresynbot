"""
Frontdesk Workflow Router — ACE
=========================================
Implements the walk-in customer intake workflow:
  Walk-in Registration → Invoice Creation → QC Check → Finance Approval → Executive Notification

Endpoints:
  POST /frontdesk/walk-ins            – Register a walk-in
  GET  /frontdesk/walk-ins            – List today's walk-ins
  GET  /frontdesk/walk-ins/{id}       – Get a single walk-in with full status
  POST /frontdesk/walk-ins/{id}/invoice   – Create invoice from walk-in
  POST /frontdesk/invoices/{id}/qc        – Submit QC check result
  POST /frontdesk/invoices/{id}/finance   – Finance approval / rejection
  POST /frontdesk/invoices/{id}/notify    – Notify CEO/CFO (post-approval)
"""

from __future__ import annotations

import logging
import datetime as dt
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.db import db, audit_event
from src.middleware import verify_jwt, require_role
from src.constants import BOT_BRAND, COMPLIANCE_QA_ROLES
from src.services.realtime import realtime_hub

# Roles allowed to hand a finance-approved invoice off to Logistics.
# No require_roles() (OR-logic, multi-role) helper exists in middleware.py —
# checked manually below, same as every other role check in this file.
_DELIVERY_ROLES = {"admin", "finance", "ops"}


def _require_frontdesk_qc(request: Request) -> dict:
    """QC gate for the invoice pipeline. require_role() only does an exact
    single-role match, which meant this endpoint accepted "quality_assurance"
    but not the "qa" alias -- inconsistent with qc.py's own _require_qc,
    which already treats them as equivalent (COMPLIANCE_QA_ROLES). Mirrors
    that precedent instead of re-diverging."""
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    if not (roles & COMPLIANCE_QA_ROLES):
        raise HTTPException(status_code=403, detail="Quality assurance role required")
    return payload


async def _broadcast_frontdesk(event: str, invoice_id: str, walk_in_id: str | None, status: str) -> None:
    """Best-effort realtime push so a QC/Finance/Ops queue view (InvoicesTab)
    can auto-refresh without polling. Never allowed to fail the request."""
    try:
        await realtime_hub.broadcast("frontdesk_updates", {
            "event": event,
            "invoice_id": invoice_id,
            "walk_in_id": walk_in_id,
            "status": status,
        })
    except Exception:
        logger.debug("frontdesk_updates broadcast failed (non-fatal)", exc_info=True)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/frontdesk", tags=["Frontdesk"])

# ---------------------------------------------------------------------------
# Walk-in status machine
# ---------------------------------------------------------------------------

WALK_IN_STATUSES = {
    "arrived",
    "invoiced",
    "qc_pending",
    "qc_passed",
    "qc_failed",
    "finance_pending",
    "finance_approved",
    "finance_rejected",
    "completed",
    "cancelled",
}

WALK_IN_TRANSITIONS: dict[str, set[str]] = {
    "arrived":          {"invoiced", "cancelled"},
    "invoiced":         {"qc_pending", "cancelled"},
    "qc_pending":       {"qc_passed", "qc_failed"},
    "qc_passed":        {"finance_pending"},
    "qc_failed":        {"qc_pending", "cancelled"},
    "finance_pending":  {"finance_approved", "finance_rejected"},
    "finance_approved": {"completed"},
    "finance_rejected": {"finance_pending", "cancelled"},
    "completed":        set(),
    "cancelled":        set(),
}

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class WalkInCreateIn(BaseModel):
    customer_name:  str = Field(..., min_length=2, max_length=200)
    company_name:   Optional[str] = Field(None, max_length=200)
    contact_phone:  Optional[str] = None
    email:          Optional[str] = None
    has_appointment: bool = Field(default=False)
    purpose:        str = Field(..., min_length=3, max_length=500,
                                description="Why the customer is visiting")
    products_requested: Optional[list[str]] = None
    notes:          Optional[str] = None


class InvoiceCreateIn(BaseModel):
    items: list[dict] = Field(
        ...,
        description="List of invoice line items: [{product, quantity, unit_price, batch_number?, manufacture_date?, expiry_date?}]",
    )
    payment_method: str = Field(default="cash",
                                description="cash | transfer | credit")
    notes: Optional[str] = None
    billing_address:  Optional[str] = None
    shipping_address: Optional[str] = None
    customer_po:      Optional[str] = None
    payment_terms:    str = Field(default="Due on Receipt")
    shipping_method:  Optional[str] = None
    tax_amount:       float = Field(default=0, ge=0)


class QCCheckIn(BaseModel):
    passed:         bool
    inspector_name: str = Field(..., min_length=2)
    notes:          Optional[str] = None
    batch_numbers:  Optional[list[str]] = None


class FinanceApprovalIn(BaseModel):
    approved:       bool
    approver_name:  str = Field(..., min_length=2)
    reason:         Optional[str] = None


class NotifyExecutiveIn(BaseModel):
    message: Optional[str] = None   # override default notification text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


_TERMS_DAYS_RE = re.compile(r"Net\s+(\d+)", re.IGNORECASE)


def _due_date_from_terms(terms: str, from_dt: dt.datetime) -> Optional[str]:
    """Computed once at invoice-creation time and stored (frontdesk_invoices.
    due_date), not recomputed on read -- an issued invoice's due date must
    never move if the payment-terms taxonomy changes later."""
    m = _TERMS_DAYS_RE.search(terms or "")
    if not m:
        return None
    days = int(m.group(1))
    return (from_dt.date() + dt.timedelta(days=days)).isoformat()


def _extract_line_item(item: dict) -> tuple[str, float, float, dict]:
    """Shared item-line extraction/validation for create_invoice and
    quick_request -- was previously duplicated verbatim in both handlers;
    extending it (for batch_number/manufacture_date/expiry_date) in only one
    place instead of two, matching drift risk already flagged elsewhere in
    this file. Raises HTTPException(400) on invalid input, same messages as
    before."""
    product    = str(item.get("product", "")).strip()
    quantity   = float(item.get("quantity", 1))
    unit_price = float(item.get("unit_price", 0))
    if not product:
        raise HTTPException(status_code=400, detail="Each item must have a 'product' field")
    if quantity <= 0 or unit_price < 0:
        raise HTTPException(status_code=400, detail="Item quantity must be > 0 and unit_price >= 0")
    line_total = round(quantity * unit_price, 2)
    extra = {}
    for key in ("batch_number", "manufacture_date", "expiry_date"):
        val = item.get(key)
        extra[key] = str(val).strip() or None if val else None
    return product, quantity, unit_price, {
        "product": product, "quantity": quantity, "unit_price": unit_price,
        "line_total": line_total, **extra,
    }


def _transition_walk_in(walk_in_id: str, new_status: str, actor: Optional[str] = None) -> dict:
    """Apply a validated status transition to a walk-in record."""
    resp = db.table("frontdesk_walk_ins").select("id,status").eq("id", walk_in_id).limit(1).execute()
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Walk-in not found")

    current = rows[0]["status"]
    allowed = WALK_IN_TRANSITIONS.get(current, set())
    if new_status not in allowed and new_status != current:
        raise HTTPException(
            status_code=409,
            detail=f"Transition not allowed: {current} → {new_status}. Allowed: {sorted(allowed)}",
        )

    db.table("frontdesk_walk_ins").update(
        {"status": new_status, "updated_at": _now()}
    ).eq("id", walk_in_id).execute()

    try:
        audit_event(
            f"frontdesk_{new_status}",
            {"walk_in_id": walk_in_id, "from": current, "to": new_status},
            actor_id=actor,
            event_class="frontdesk",
            action="status_transition",
            subject_type="walk_in",
            subject_id=walk_in_id,
        )
    except Exception:
        pass

    return {"walk_in_id": walk_in_id, "from": current, "to": new_status}


# ---------------------------------------------------------------------------
# 1. Register a walk-in
# ---------------------------------------------------------------------------

@router.post("/walk-ins", status_code=201)
async def register_walk_in(
    payload: WalkInCreateIn,
    user: dict = Depends(verify_jwt),
):
    """Register a customer walk-in and start the frontdesk workflow."""
    walk_in_id = str(uuid.uuid4())
    actor_id = user.get("sub")

    row = {
        "id":                  walk_in_id,
        "customer_name":       payload.customer_name,
        "company_name":        payload.company_name,
        "contact_phone":       payload.contact_phone,
        "email":               payload.email,
        "has_appointment":     payload.has_appointment,
        "purpose":             payload.purpose,
        "products_requested":  payload.products_requested or [],
        "notes":               payload.notes,
        "status":              "arrived",
        "registered_by":       actor_id,
        "created_at":          _now(),
        "updated_at":          _now(),
    }

    try:
        resp = db.table("frontdesk_walk_ins").insert(row).execute()
        created = (resp.data or [row])[0]
    except Exception as exc:
        logger.error("Walk-in registration error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to register walk-in")

    try:
        audit_event(
            "frontdesk_walk_in_registered",
            {"walk_in_id": walk_in_id, "customer": payload.customer_name},
            actor_id=actor_id,
            event_class="frontdesk",
            action="register",
            subject_type="walk_in",
            subject_id=walk_in_id,
        )
    except Exception:
        pass

    return {"status": "registered", "walk_in": created}


# ---------------------------------------------------------------------------
# 2. List today's walk-ins
# ---------------------------------------------------------------------------

@router.get("/walk-ins")
async def list_walk_ins(
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    _u=Depends(verify_jwt),
):
    """List walk-ins for the given date (defaults to today)."""
    if date:
        try:
            target_date = dt.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        target_date = dt.date.today()

    day_start = dt.datetime.combine(target_date, dt.time.min).isoformat() + "Z"
    day_end   = dt.datetime.combine(target_date, dt.time.max).isoformat() + "Z"

    try:
        q = (
            db.table("frontdesk_walk_ins")
            .select("id,customer_name,contact_phone,purpose,products_requested,status,notes,created_at,updated_at")
            .gte("created_at", day_start)
            .lte("created_at", day_end)
        )
        if status:
            q = q.eq("status", status)
        resp = q.order("created_at", desc=False).limit(limit).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Walk-in list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list walk-ins")

    return {"date": target_date.isoformat(), "count": len(rows), "walk_ins": rows}


# ---------------------------------------------------------------------------
# 3. Get single walk-in with full status (including linked invoices)
# ---------------------------------------------------------------------------

@router.get("/walk-ins/{walk_in_id}")
async def get_walk_in(
    walk_in_id: str,
    _u=Depends(verify_jwt),
):
    """Return a walk-in record with any linked invoice and QC/finance decisions."""
    try:
        resp = db.table("frontdesk_walk_ins").select("*").eq("id", walk_in_id).limit(1).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Walk-in fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch walk-in")

    if not rows:
        raise HTTPException(status_code=404, detail="Walk-in not found")

    walk_in = rows[0]

    # Fetch linked invoices
    invoices: list[dict] = []
    try:
        inv_resp = (
            db.table("frontdesk_invoices")
            .select("id,total_amount,payment_method,status,qc_passed,finance_approved,created_at")
            .eq("walk_in_id", walk_in_id)
            .execute()
        )
        invoices = inv_resp.data or []
    except Exception:
        pass

    return {"walk_in": walk_in, "invoices": invoices}


# ---------------------------------------------------------------------------
# 4. Create invoice from walk-in
# ---------------------------------------------------------------------------

@router.post("/walk-ins/{walk_in_id}/invoice", status_code=201)
async def create_invoice(
    walk_in_id: str,
    payload: InvoiceCreateIn,
    user: dict = Depends(verify_jwt),
):
    """Create a frontdesk invoice for a walk-in customer and advance to qc_pending."""
    actor_id = user.get("sub")

    # Validate walk-in exists and is in 'arrived' state
    try:
        wi_resp = db.table("frontdesk_walk_ins").select("id,status,customer_name,company_name").eq("id", walk_in_id).limit(1).execute()
        walk_in_rows = wi_resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch walk-in")

    if not walk_in_rows:
        raise HTTPException(status_code=404, detail="Walk-in not found")

    walk_in = walk_in_rows[0]
    if walk_in["status"] not in ("arrived", "invoiced"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot invoice a walk-in in '{walk_in['status']}' status",
        )

    # Validate and compute line items
    line_items: list[dict] = []
    total_amount = 0.0
    for item in payload.items:
        _product, _qty, _price, line_item = _extract_line_item(item)
        total_amount += line_item["line_total"]
        line_items.append(line_item)

    invoice_id = str(uuid.uuid4())
    created_at = _now()
    inv_row = {
        "id":             invoice_id,
        "walk_in_id":     walk_in_id,
        "customer_name":  walk_in["customer_name"],
        "company_name":   walk_in.get("company_name"),
        "items":          line_items,
        "total_amount":   round(total_amount, 2),
        "payment_method": payload.payment_method,
        "notes":          payload.notes,
        "billing_address":  payload.billing_address,
        "shipping_address": payload.shipping_address,
        "customer_po":      payload.customer_po,
        "payment_terms":    payload.payment_terms,
        "due_date":         _due_date_from_terms(payload.payment_terms, dt.datetime.utcnow()),
        "shipping_method":  payload.shipping_method,
        "tax_amount":       round(payload.tax_amount, 2),
        # Set directly to qc_pending, not "draft" — discovered via live
        # verification that nothing ever transitioned the invoice's own
        # status column afterward (only the walk-in's status advanced), so
        # invoice.status silently never took the "qc_pending" value the
        # frontend's status filter / role-aware action panel depend on.
        "status":         "qc_pending",
        "qc_passed":      None,
        "finance_approved": None,
        "created_by":     actor_id,
        "created_at":     created_at,
        "updated_at":     created_at,
    }

    try:
        resp = db.table("frontdesk_invoices").insert(inv_row).execute()
        created = (resp.data or [inv_row])[0]
    except Exception as exc:
        logger.error("Invoice creation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create invoice")

    # Advance walk-in status
    try:
        _transition_walk_in(walk_in_id, "qc_pending", actor_id)
    except Exception as exc:
        logger.warning("Walk-in status transition failed after invoice creation: %s", exc)

    try:
        audit_event(
            "frontdesk_invoice_created",
            {"invoice_id": invoice_id, "walk_in_id": walk_in_id, "total": total_amount},
            actor_id=actor_id,
            event_class="frontdesk",
            action="create_invoice",
            subject_type="invoice",
            subject_id=invoice_id,
        )
    except Exception:
        pass

    await _broadcast_frontdesk("invoice_qc_pending", invoice_id, walk_in_id, "qc_pending")

    return {"status": "created", "invoice": created}


# ---------------------------------------------------------------------------
# 5. QC Check
# ---------------------------------------------------------------------------

@router.post("/invoices/{invoice_id}/qc")
async def submit_qc(
    invoice_id: str,
    payload: QCCheckIn,
    user: dict = Depends(_require_frontdesk_qc),
):
    """
    Submit a QC check result for an invoice.
    Passing advances the walk-in to finance_pending; failing sets qc_failed.
    """
    actor_id = user.get("sub")

    try:
        inv_resp = db.table("frontdesk_invoices").select("id,walk_in_id,status").eq("id", invoice_id).limit(1).execute()
        inv_rows = inv_resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch invoice")

    if not inv_rows:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv = inv_rows[0]
    walk_in_id = inv["walk_in_id"]

    qc_update = {
        "qc_passed":       payload.passed,
        "qc_inspector":    payload.inspector_name,
        "qc_notes":        payload.notes,
        "qc_batch_numbers": payload.batch_numbers or [],
        "qc_checked_at":   _now(),
        # On pass, go straight to finance_pending (not the intermediate
        # "qc_passed" value) — qc_passed=True above already records the QC
        # outcome for the badge/finance-precondition check; the frontend's
        # role-aware action panel needs status itself to reach
        # finance_pending so the Finance form actually appears.
        "status":          "finance_pending" if payload.passed else "qc_failed",
        "updated_at":      _now(),
    }

    try:
        db.table("frontdesk_invoices").update(qc_update).eq("id", invoice_id).execute()
    except Exception as exc:
        logger.error("QC update error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save QC result")

    # Advance walk-in
    new_wi_status = "finance_pending" if payload.passed else "qc_failed"
    try:
        _transition_walk_in(walk_in_id, new_wi_status, actor_id)
    except Exception as exc:
        logger.warning("Walk-in transition after QC failed: %s", exc)

    try:
        audit_event(
            "frontdesk_qc_checked",
            {"invoice_id": invoice_id, "passed": payload.passed, "inspector": payload.inspector_name},
            actor_id=actor_id,
            event_class="frontdesk",
            action="qc_check",
            outcome="pass" if payload.passed else "fail",
            subject_type="invoice",
            subject_id=invoice_id,
        )
    except Exception:
        pass

    await _broadcast_frontdesk(
        "invoice_finance_pending" if payload.passed else "invoice_qc_failed",
        invoice_id, walk_in_id, qc_update["status"],
    )

    return {
        "invoice_id": invoice_id,
        "qc_passed":  payload.passed,
        "walk_in_status": new_wi_status,
    }


# ---------------------------------------------------------------------------
# 6. Finance Approval
# ---------------------------------------------------------------------------

@router.post("/invoices/{invoice_id}/finance")
async def finance_approval(
    invoice_id: str,
    payload: FinanceApprovalIn,
    user: dict = Depends(require_role("finance")),
):
    """
    Finance approves or rejects an invoice after QC.
    Approval completes the walk-in workflow; rejection returns to finance_pending.
    """
    actor_id = user.get("sub")

    try:
        inv_resp = db.table("frontdesk_invoices").select("id,walk_in_id,qc_passed,status").eq("id", invoice_id).limit(1).execute()
        inv_rows = inv_resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch invoice")

    if not inv_rows:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv = inv_rows[0]
    if not inv.get("qc_passed"):
        raise HTTPException(status_code=409, detail="Invoice must pass QC before finance approval")

    walk_in_id = inv["walk_in_id"]
    new_status = "finance_approved" if payload.approved else "finance_rejected"

    fin_update = {
        "finance_approved":  payload.approved,
        "finance_approver":  payload.approver_name,
        "finance_reason":    payload.reason,
        "finance_decided_at": _now(),
        "status":            new_status,
        "updated_at":        _now(),
    }

    try:
        db.table("frontdesk_invoices").update(fin_update).eq("id", invoice_id).execute()
    except Exception as exc:
        logger.error("Finance approval error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save finance decision")

    # Advance walk-in
    wi_new_status = "finance_approved" if payload.approved else "finance_rejected"
    try:
        _transition_walk_in(walk_in_id, wi_new_status, actor_id)
    except Exception as exc:
        logger.warning("Walk-in transition after finance decision failed: %s", exc)

    try:
        audit_event(
            "frontdesk_finance_decision",
            {"invoice_id": invoice_id, "approved": payload.approved, "approver": payload.approver_name},
            actor_id=actor_id,
            event_class="frontdesk",
            action="finance_approval",
            outcome="approved" if payload.approved else "rejected",
            reason_code=payload.reason or ("approved" if payload.approved else "rejected"),
            subject_type="invoice",
            subject_id=invoice_id,
        )
    except Exception:
        pass

    await _broadcast_frontdesk(
        "invoice_finance_approved" if payload.approved else "invoice_finance_rejected",
        invoice_id, walk_in_id, new_status,
    )

    return {
        "invoice_id":   invoice_id,
        "approved":     payload.approved,
        "walk_in_status": wi_new_status,
    }


# ---------------------------------------------------------------------------
# 7. Notify CEO/CFO
# ---------------------------------------------------------------------------

@router.post("/invoices/{invoice_id}/notify")
async def notify_executive(
    invoice_id: str,
    payload: NotifyExecutiveIn,
    user: dict = Depends(require_role("finance")),
):
    """
    Send an email notification to CEO/CFO about a completed and finance-approved invoice.
    Recipients configured via EXECUTIVE_NOTIFY_EMAILS env var (comma-separated).
    """
    actor_id = user.get("sub")

    import os
    recipients_raw = os.getenv("EXECUTIVE_NOTIFY_EMAILS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients:
        return {"status": "skipped", "reason": "EXECUTIVE_NOTIFY_EMAILS not configured"}

    # Fetch invoice + walk-in details
    try:
        inv_resp = (
            db.table("frontdesk_invoices")
            .select("id,walk_in_id,customer_name,total_amount,payment_method,finance_approved,items")
            .eq("id", invoice_id).limit(1).execute()
        )
        inv_rows = inv_resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch invoice")

    if not inv_rows:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv = inv_rows[0]

    if not inv.get("finance_approved"):
        raise HTTPException(
            status_code=409,
            detail="Invoice must be finance-approved before executive notification",
        )

    message = payload.message or (
        f"Walk-in sale completed for {inv.get('customer_name', 'N/A')}.\n"
        f"Invoice #{invoice_id[:8]}... | Total: \u20a6{inv.get('total_amount', 0):,} "
        f"| Payment: {inv.get('payment_method', 'N/A')}\n\n"
        f"Approved by Finance. All QC checks passed.\n\n"
        f"This is an automated notification from {BOT_BRAND} Frontdesk System."
    )

    subject = f"[{BOT_BRAND}] Walk-in Sale Approved — {inv.get('customer_name', 'N/A')}"
    sent: list[str] = []
    errors: list[str] = []

    try:
        from src.services.messaging import send_email
        for recipient in recipients:
            try:
                send_email(recipient, subject, message)
                sent.append(recipient)
            except Exception as e:
                errors.append(f"{recipient}: {e}")
    except Exception as exc:
        logger.error("Executive notification import error: %s", exc)
        raise HTTPException(status_code=500, detail="Messaging service unavailable")

    # Mark walk-in as completed
    try:
        _transition_walk_in(inv["walk_in_id"], "completed", actor_id)
    except Exception:
        pass

    try:
        audit_event(
            "frontdesk_executive_notified",
            {"invoice_id": invoice_id, "recipients": sent, "errors": errors},
            actor_id=actor_id,
            event_class="frontdesk",
            action="notify_executive",
            subject_type="invoice",
            subject_id=invoice_id,
        )
    except Exception:
        pass

    return {
        "invoice_id":  invoice_id,
        "notified":    sent,
        "errors":      errors,
        "walk_in_status": "completed",
    }


# ---------------------------------------------------------------------------
# 7b. Send for Delivery — hands a finance-approved invoice off to Logistics
#     (backend/src/routers/logistics.py). Writes to `deliveries` directly
#     (service-to-service) rather than calling POST /logistics/deliveries
#     over HTTP: that endpoint is `ops`-role-gated, and `finance` does not
#     implicitly satisfy `ops` under this app's role model (no role
#     hierarchy beyond the `admin` superrole — see middleware.py).
# ---------------------------------------------------------------------------

@router.post("/invoices/{invoice_id}/send-for-delivery")
async def send_for_delivery(
    invoice_id: str,
    user_payload: dict = Depends(verify_jwt),
):
    """Create a Logistics delivery record from a finance-approved invoice."""
    roles = {str(r).lower() for r in (user_payload.get("roles") or [])}
    if not roles & _DELIVERY_ROLES:
        raise HTTPException(status_code=403, detail="Requires finance, ops, or admin role")
    actor_id = user_payload.get("sub")

    try:
        inv_resp = (
            db.table("frontdesk_invoices")
            .select("id,walk_in_id,invoice_number,customer_name,company_name,items,status,delivery_id")
            .eq("id", invoice_id).limit(1).execute()
        )
        inv_rows = inv_resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch invoice")

    if not inv_rows:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv = inv_rows[0]

    if inv["status"] == "dispatched" and inv.get("delivery_id"):
        raise HTTPException(status_code=409, detail="Invoice has already been sent for delivery")
    if inv["status"] != "finance_approved":
        raise HTTPException(
            status_code=409,
            detail=f"Invoice must be finance_approved before dispatch (currently '{inv['status']}')",
        )

    # contact_phone lives on the walk-in, not the invoice
    contact_phone = None
    try:
        wi_resp = (
            db.table("frontdesk_walk_ins").select("contact_phone")
            .eq("id", inv["walk_in_id"]).limit(1).execute()
        )
        wi_rows = wi_resp.data or []
        if wi_rows:
            contact_phone = wi_rows[0].get("contact_phone")
    except Exception:
        pass

    items = inv.get("items") or []
    items_summary = ", ".join(
        f"{it.get('product', '?')} x{it.get('quantity', 0)}" for it in items
    ) or None
    total_quantity = sum(float(it.get("quantity") or 0) for it in items) or None

    delivery_row = {
        "id": str(uuid.uuid4()),
        "reference": inv.get("invoice_number"),
        "customer_id": None,  # frontdesk walk-ins have no customers-table row to reference
        "address": {
            "customer_name": inv.get("customer_name"),
            "company_name": inv.get("company_name"),
            "contact_phone": contact_phone,
            "items_summary": items_summary,
        },
        "quantity": total_quantity,
        "status": "unassigned",
        "source": "frontdesk_walk_in",
        "source_ref_id": invoice_id,
        "created_at": _now(),
    }

    try:
        db.table("deliveries").insert(delivery_row).execute()
    except Exception as exc:
        logger.error("Delivery creation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create delivery record")

    now = _now()
    try:
        db.table("frontdesk_invoices").update({
            "status": "dispatched",
            "delivery_id": delivery_row["id"],
            "dispatched_at": now,
            "updated_at": now,
        }).eq("id", invoice_id).execute()
    except Exception as exc:
        logger.error("Invoice dispatch-status update error: %s", exc)
        raise HTTPException(status_code=500, detail="Delivery created, but failed to update invoice status")

    try:
        audit_event(
            "frontdesk_invoice_dispatched",
            {"invoice_id": invoice_id, "delivery_id": delivery_row["id"]},
            actor_id=actor_id,
            event_class="frontdesk",
            action="send_for_delivery",
            subject_type="invoice",
            subject_id=invoice_id,
        )
    except Exception:
        pass

    await _broadcast_frontdesk("invoice_dispatched", invoice_id, inv["walk_in_id"], "dispatched")

    return {
        "invoice_id": invoice_id,
        "delivery_id": delivery_row["id"],
        "status": "dispatched",
    }


# ---------------------------------------------------------------------------
# 8. Search returning clients
#    Fuzzy search across past walk-ins by name, company, or phone.
# ---------------------------------------------------------------------------

@router.get("/clients/search")
async def search_clients(
    q: str = Query(..., min_length=2, description="Name, company, or phone fragment"),
    limit: int = Query(default=10, le=50),
    _u=Depends(verify_jwt),
):
    """
    Search historical walk-ins to identify returning clients.
    Returns distinct clients (latest visit per unique phone/name).
    """
    term = q.strip().lower()
    try:
        # LocalDBClient's TableQuery has no .or_() (discovered via live
        # verification — this endpoint 500'd on every call). It only
        # supports PostgREST-style filters that map to a single AND'd WHERE
        # clause. Mirrors ar_receipts.py's list endpoint: fetch a bounded
        # candidate set, filter across columns in Python.
        resp = (
            db.table("frontdesk_walk_ins")
            .select("id,customer_name,company_name,contact_phone,email,purpose,status,created_at")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        all_rows = resp.data or []
    except Exception as exc:
        logger.error("Client search error: %s", exc)
        raise HTTPException(status_code=500, detail="Search failed")

    rows = [
        r for r in all_rows
        if term in (r.get("customer_name") or "").lower()
        or term in (r.get("company_name") or "").lower()
        or term in (r.get("contact_phone") or "").lower()
        or term in (r.get("email") or "").lower()
    ]

    # De-duplicate by phone (keep most recent visit)
    seen: set[str] = set()
    unique: list[dict] = []
    for r in rows:
        key = (r.get("contact_phone") or r["customer_name"]).lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)

    unique = unique[:limit]
    return {"query": q, "count": len(unique), "clients": unique}


# ---------------------------------------------------------------------------
# 9. Returning client history
#    Full visit history, all invoices, total spend for a given walk-in id.
# ---------------------------------------------------------------------------

@router.get("/clients/{walk_in_id}/history")
async def client_history(
    walk_in_id: str,
    _u=Depends(verify_jwt),
):
    """
    Full history for a returning client identified by any of their walk-in IDs.
    Returns all past visits and invoices matched by phone or name.
    """
    try:
        wi_resp = db.table("frontdesk_walk_ins").select("*").eq("id", walk_in_id).limit(1).execute()
        wi_rows = wi_resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch walk-in")

    if not wi_rows:
        raise HTTPException(status_code=404, detail="Walk-in not found")

    anchor = wi_rows[0]
    phone = anchor.get("contact_phone")
    name  = anchor["customer_name"]

    # Find all visits by same phone (if available) or name
    try:
        if phone:
            all_resp = (
                db.table("frontdesk_walk_ins")
                .select("id,customer_name,company_name,purpose,products_requested,status,created_at")
                .eq("contact_phone", phone)
                .order("created_at", desc=True)
                .execute()
            )
        else:
            all_resp = (
                db.table("frontdesk_walk_ins")
                .select("id,customer_name,company_name,purpose,products_requested,status,created_at")
                .ilike("customer_name", name)
                .order("created_at", desc=True)
                .execute()
            )
        all_visits = all_resp.data or []
    except Exception:
        all_visits = [anchor]

    # Fetch all invoices for these visits
    visit_ids = [v["id"] for v in all_visits]
    invoices: list[dict] = []
    if visit_ids:
        try:
            inv_resp = (
                db.table("frontdesk_invoices")
                .select("id,invoice_number,walk_in_id,total_amount,payment_method,status,items,created_at")
                .in_("walk_in_id", visit_ids)
                .order("created_at", desc=True)
                .execute()
            )
            invoices = inv_resp.data or []
        except Exception:
            pass

    total_spend = sum(float(i.get("total_amount") or 0) for i in invoices if i.get("status") in ("completed", "finance_approved"))
    visit_count = len(all_visits)

    return {
        "client": {
            "name":    name,
            "company": anchor.get("company_name"),
            "phone":   phone,
            "email":   anchor.get("email"),
        },
        "visit_count":  visit_count,
        "total_spend":  round(total_spend, 2),
        "visits":       all_visits,
        "invoices":     invoices,
    }


# ---------------------------------------------------------------------------
# 10. List all invoices (filterable)
# ---------------------------------------------------------------------------

@router.get("/invoices")
async def list_invoices(
    status: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to:   Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    q: Optional[str] = Query(default=None, description="Search customer name"),
    limit: int = Query(default=100, le=500),
    _u=Depends(verify_jwt),
):
    """List all invoices with optional status/date/customer filters."""
    try:
        query = db.table("frontdesk_invoices").select(
            "id,invoice_number,walk_in_id,customer_name,company_name,"
            "total_amount,payment_method,status,qc_passed,finance_approved,"
            "created_at,updated_at"
        )
        if status:
            query = query.eq("status", status)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            d = dt.date.fromisoformat(date_to)
            query = query.lte("created_at", (d + dt.timedelta(days=1)).isoformat())
        if q:
            query = query.ilike("customer_name", f"%{q}%")

        resp = query.order("created_at", desc=True).limit(limit).execute()
        rows = resp.data or []
    except Exception as exc:
        logger.error("Invoice list error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list invoices")

    return {"count": len(rows), "invoices": rows}


# ---------------------------------------------------------------------------
# 11. Get single invoice with full detail
# ---------------------------------------------------------------------------

@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    _u=Depends(verify_jwt),
):
    """Return full invoice detail including walk-in context."""
    try:
        resp = db.table("frontdesk_invoices").select("*").eq("id", invoice_id).limit(1).execute()
        rows = resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch invoice")

    if not rows:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice = rows[0]

    # Fetch walk-in context
    walk_in = None
    if invoice.get("walk_in_id"):
        try:
            wi_resp = (
                db.table("frontdesk_walk_ins")
                .select("id,customer_name,company_name,contact_phone,email,purpose,created_at,customer_id")
                .eq("id", invoice["walk_in_id"])
                .limit(1)
                .execute()
            )
            wi_rows = wi_resp.data or []
            walk_in = wi_rows[0] if wi_rows else None
        except Exception:
            pass

    # "Customer ID" on the printed invoice -- resolved here rather than
    # stored, since customers.customer_code can change and the walk-in's
    # customer_id link (migration 100) is the only reliable source. Best-
    # effort: falls back to "WALK-IN" in the frontend when absent (older
    # create_invoice-path walk-ins have no customer link at all).
    if walk_in and walk_in.get("customer_id"):
        try:
            cust_resp = db.table("customers").select("customer_code").eq("id", walk_in["customer_id"]).limit(1).execute()
            cust_rows = cust_resp.data or []
            if cust_rows:
                walk_in["customer_code"] = cust_rows[0].get("customer_code")
        except Exception:
            pass

    # "Sales Rep" (meta row) and "Prepared by" (signature block) both
    # resolve from the same created_by actor -- placeware_users has no name
    # column at all (confirmed), so email (or its local-part) is the best
    # identity available in this schema today. placeware_staff is not a
    # reliable link (near-empty, per an earlier round's findings).
    if invoice.get("created_by"):
        try:
            from src.db import get_user_by_id
            creator = get_user_by_id(invoice["created_by"])
            if creator:
                invoice["created_by_email"] = creator.get("email")
        except Exception:
            pass

    # "Delivered" signature-block name on the printed invoice -- resolved
    # from the rider actually assigned to this invoice's delivery, same
    # "resolve at read time from an existing link" pattern as customer_code
    # above. No signature capture here yet (that's a separate, later round);
    # this only supplies the name to print above the blank ink line.
    if invoice.get("delivery_id"):
        try:
            del_resp = db.table("deliveries").select("assigned_rider").eq("id", invoice["delivery_id"]).limit(1).execute()
            del_rows = del_resp.data or []
            rider_id = del_rows[0].get("assigned_rider") if del_rows else None
            if rider_id:
                rider_resp = db.table("riders").select("name").eq("id", rider_id).limit(1).execute()
                rider_rows = rider_resp.data or []
                if rider_rows:
                    invoice["delivered_by"] = rider_rows[0].get("name")
        except Exception:
            pass

    return {"invoice": invoice, "walk_in": walk_in}


@router.get("/invoices/{invoice_id}/history")
async def get_invoice_history(
    invoice_id: str,
    _u=Depends(verify_jwt),
):
    """Full lifecycle trail for one invoice (create -> QC -> finance ->
    dispatch -> delivery-confirmed), sourced from placeware_audit_logs.

    Every transition in this file already called audit_event(subject_type=
    "invoice", subject_id=invoice_id) -- the data was always being written,
    it just had no query endpoint reading it back, so staff had no way to
    see an invoice's movement anywhere in the UI. Chronological (oldest
    first), unlike most audit views in this app which show newest-first,
    since this reads as a timeline of what happened to this one invoice.
    """
    from src.constants import TABLE_AUDIT_LOGS
    try:
        resp = (
            db.table(TABLE_AUDIT_LOGS)
            .select("event_type,action,outcome,actor_id,actor_role,created_at,details")
            .eq("subject_type", "invoice")
            .eq("subject_id", invoice_id)
            .order("created_at", desc=False)
            .execute()
        )
        events = resp.data or []
    except Exception as exc:
        logger.error("Invoice history fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch invoice history")

    return {"invoice_id": invoice_id, "events": events}


# ---------------------------------------------------------------------------
# 12. Real-time stock check
#    Checks placeware_stock_cache for current quantity levels.
# ---------------------------------------------------------------------------

@router.get("/stock-check")
async def stock_check(
    products: str = Query(..., description="Comma-separated product names or SKUs"),
    _u=Depends(verify_jwt),
):
    """
    Check real-time stock availability for a list of product names.
    Used during invoice creation to surface low/out-of-stock alerts.
    """
    product_list = [p.strip() for p in products.split(",") if p.strip()]
    if not product_list:
        raise HTTPException(status_code=400, detail="No products specified")
    if len(product_list) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 products per check")

    results: list[dict] = []

    for product in product_list:
        item_result: dict = {
            "product":    product,
            "sku":        None,
            "name":       None,
            "quantity":   None,
            "status":     "unknown",  # in_stock | low_stock | out_of_stock | unknown
            "unit_cost":  None,
        }

        try:
            # Search stock cache by name (case-insensitive), falling back to
            # SKU if no name match. Two queries, not .or_() — LocalDBClient's
            # TableQuery doesn't implement it (see search_clients() above,
            # where the same call pattern 500'd every time in live testing).
            resp = (
                db.table("placeware_stock_cache")
                .select("sku,name,quantity,unit_cost")
                .ilike("name", f"%{product}%")
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                resp = (
                    db.table("placeware_stock_cache")
                    .select("sku,name,quantity,unit_cost")
                    .ilike("sku", f"%{product}%")
                    .limit(1)
                    .execute()
                )
                rows = resp.data or []

            if rows:
                row = rows[0]
                qty = float(row.get("quantity") or 0)
                item_result.update({
                    "sku":       row.get("sku"),
                    "name":      row.get("name"),
                    "quantity":  qty,
                    "unit_cost": float(row.get("unit_cost") or 0),
                    "status":    (
                        "in_stock"    if qty > 10 else
                        "low_stock"   if qty > 0  else
                        "out_of_stock"
                    ),
                })
        except Exception as exc:
            logger.warning("Stock check error for '%s': %s", product, exc)

        results.append(item_result)

    return {"products": results}


# ---------------------------------------------------------------------------
# 13. Daily reports
#    Volume, revenue, top requested products, and pending approvals.
# ---------------------------------------------------------------------------

@router.get("/reports/daily")
async def daily_report(
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    _u=Depends(verify_jwt),
):
    """Daily frontdesk operational report."""
    if date:
        try:
            target_date = dt.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        target_date = dt.date.today()

    day_start = dt.datetime.combine(target_date, dt.time.min).isoformat() + "Z"
    day_end   = dt.datetime.combine(target_date, dt.time.max).isoformat() + "Z"

    # Walk-ins today
    walk_ins: list[dict] = []
    try:
        wi_resp = (
            db.table("frontdesk_walk_ins")
            .select("id,customer_name,company_name,status,products_requested,created_at")
            .gte("created_at", day_start)
            .lte("created_at", day_end)
            .execute()
        )
        walk_ins = wi_resp.data or []
    except Exception as exc:
        logger.error("Daily report walk-in query error: %s", exc)

    # Invoices today
    invoices: list[dict] = []
    try:
        inv_resp = (
            db.table("frontdesk_invoices")
            .select("id,total_amount,status,items,payment_method,created_at")
            .gte("created_at", day_start)
            .lte("created_at", day_end)
            .execute()
        )
        invoices = inv_resp.data or []
    except Exception as exc:
        logger.error("Daily report invoice query error: %s", exc)

    # Compute summary stats
    total_revenue = sum(
        float(inv.get("total_amount") or 0)
        for inv in invoices
        if inv.get("status") in ("completed", "finance_approved")
    )
    pending_qc       = sum(1 for wi in walk_ins if wi["status"] in ("qc_pending",))
    pending_finance  = sum(1 for wi in walk_ins if wi["status"] in ("finance_pending",))
    completed_today  = sum(1 for wi in walk_ins if wi["status"] == "completed")

    # Top requested products (from walk-in products_requested + invoice items)
    product_counts: dict[str, int] = {}
    for wi in walk_ins:
        for p in (wi.get("products_requested") or []):
            name = p.strip()
            if name:
                product_counts[name] = product_counts.get(name, 0) + 1
    for inv in invoices:
        for item in (inv.get("items") or []):
            if isinstance(item, dict):
                name = str(item.get("product") or "").strip()
                if name:
                    product_counts[name] = product_counts.get(name, 0) + 1

    top_products = sorted(
        [{"product": k, "count": v} for k, v in product_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    return {
        "date":              target_date.isoformat(),
        "walk_in_count":     len(walk_ins),
        "invoice_count":     len(invoices),
        "total_revenue":     round(total_revenue, 2),
        "pending_qc":        pending_qc,
        "pending_finance":   pending_finance,
        "completed_today":   completed_today,
        "top_products":      top_products,
        "walk_ins":          walk_ins,
        "invoices":          invoices,
    }


# ---------------------------------------------------------------------------
# 13. Cancel a walk-in
#    Allowed from any non-terminal status per the state machine.
# ---------------------------------------------------------------------------

@router.post("/walk-ins/{walk_in_id}/cancel", status_code=200)
async def cancel_walk_in(
    walk_in_id: str,
    reason: Optional[str] = Body(default=None, embed=True),
    user=Depends(verify_jwt),
):
    """Cancel a walk-in visit. Allowed from any non-terminal status."""
    actor_id = user.get("sub") if isinstance(user, dict) else str(user)

    try:
        resp = (
            db.table("frontdesk_walk_ins")
            .select("id,status")
            .eq("id", walk_in_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Cancel walk-in fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch walk-in")

    if not rows:
        raise HTTPException(status_code=404, detail="Walk-in not found")

    current_status = rows[0]["status"]
    allowed = WALK_IN_TRANSITIONS.get(current_status, set())
    if "cancelled" not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel a walk-in with status '{current_status}'"
        )

    now = dt.datetime.utcnow().isoformat() + "Z"
    update_data: dict = {"status": "cancelled", "updated_at": now}
    if reason:
        update_data["notes"] = reason

    try:
        db.table("frontdesk_walk_ins").update(update_data).eq("id", walk_in_id).execute()
    except Exception as exc:
        logger.error("Cancel walk-in update error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to cancel walk-in")

    # Also cancel any draft/pending invoice
    try:
        db.table("frontdesk_invoices").update(
            {"status": "cancelled", "updated_at": now}
        ).eq("walk_in_id", walk_in_id).in_("status", [
            "draft", "qc_pending", "finance_pending"
        ]).execute()
    except Exception:
        pass

    try:
        audit_event(
            "frontdesk_walk_in_cancelled",
            {"reason": reason, "previous_status": current_status},
            actor_id=actor_id,
            event_class="frontdesk",
            action="cancel_walk_in",
            subject_type="walk_in",
            subject_id=walk_in_id,
        )
    except Exception:
        pass

    return {"walk_in_id": walk_in_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# 14. Quick Request — Centralized Customer Workspace
#    Given an existing customers.id, creates BOTH the walk-in row and the
#    invoice row in one call, inserted directly at qc_pending (bypasses
#    _transition_walk_in()'s arrived->invoiced dance -- see comment below).
# ---------------------------------------------------------------------------

class QuickRequestIn(BaseModel):
    items: list[dict] = Field(
        ...,
        description="List of invoice line items: [{product, quantity, unit_price, batch_number?, manufacture_date?, expiry_date?}]",
    )
    payment_method: str = Field(default="cash", description="cash | transfer | credit")
    notes: Optional[str] = None
    purpose: str = Field(default="Customer workspace request", max_length=500)
    billing_address:  Optional[str] = None
    shipping_address: Optional[str] = None
    customer_po:      Optional[str] = None
    payment_terms:    str = Field(default="Due on Receipt")
    shipping_method:  Optional[str] = None
    tax_amount:       float = Field(default=0, ge=0)


@router.post("/customers/{customer_id}/quick-request", status_code=201)
async def quick_request(
    customer_id: int,
    payload: QuickRequestIn,
    user_payload: dict = Depends(verify_jwt),
):
    """Raise a new invoice request for an already-identified CRM customer,
    from the Centralized Customer Workspace's 'Make New Request' action.
    Role gate matches register_walk_in's existing precedent (any
    authenticated user) -- there is no frontdesk/sales/reception role in
    this app's vocabulary to gate it more tightly with.
    """
    actor_id = user_payload.get("sub") if isinstance(user_payload, dict) else str(user_payload)

    try:
        cust_resp = db.table("customers").select("id,name,contact_details").eq("id", customer_id).limit(1).execute()
        cust_rows = cust_resp.data or []
    except Exception as exc:
        logger.error("Quick-request customer fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch customer")

    if not cust_rows:
        raise HTTPException(status_code=404, detail="Customer not found")
    cust = cust_rows[0]
    cd = cust.get("contact_details") or {}

    line_items: list[dict] = []
    total_amount = 0.0
    for item in payload.items:
        _product, _qty, _price, line_item = _extract_line_item(item)
        total_amount += line_item["line_total"]
        line_items.append(line_item)

    now = _now()
    walk_in_id = str(uuid.uuid4())
    walk_in_row = {
        "id":                  walk_in_id,
        "customer_id":         customer_id,
        "customer_name":       cust.get("name") or "Unknown",
        "company_name":        None,
        "contact_phone":       cd.get("phone"),
        "email":               cd.get("email"),
        "has_appointment":     False,
        "purpose":             payload.purpose,
        "products_requested":  [it["product"] for it in line_items],
        "notes":               payload.notes,
        # Inserted directly at "qc_pending", not "arrived" -> _transition_walk_in().
        # WALK_IN_TRANSITIONS["arrived"] has no direct edge to "qc_pending"
        # (only "invoiced"), which is what silently desyncs
        # frontdesk_walk_ins.status in create_invoice() today if that's
        # called while still "arrived" (see that function's own comment
        # above). This endpoint sidesteps _transition_walk_in() entirely by
        # inserting directly at the target status -- safe because no DB
        # constraint enforces transition history on INSERT, only
        # _transition_walk_in() does, and only on UPDATE.
        "status":              "qc_pending",
        "registered_by":       actor_id,
        "created_at":          now,
        "updated_at":          now,
    }
    try:
        db.table("frontdesk_walk_ins").insert(walk_in_row).execute()
    except Exception as exc:
        logger.error("Quick-request walk-in insert error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create request")

    invoice_id = str(uuid.uuid4())
    inv_row = {
        "id":               invoice_id,
        "walk_in_id":       walk_in_id,
        "customer_name":    walk_in_row["customer_name"],
        "company_name":     None,
        "items":            line_items,
        "total_amount":     round(total_amount, 2),
        "payment_method":   payload.payment_method,
        "notes":            payload.notes,
        "billing_address":  payload.billing_address,
        "shipping_address": payload.shipping_address,
        "customer_po":      payload.customer_po,
        "payment_terms":    payload.payment_terms,
        "due_date":         _due_date_from_terms(payload.payment_terms, dt.datetime.utcnow()),
        "shipping_method":  payload.shipping_method,
        "tax_amount":       round(payload.tax_amount, 2),
        "status":           "qc_pending",
        "qc_passed":        None,
        "finance_approved": None,
        "created_by":       actor_id,
        "created_at":       now,
        "updated_at":       now,
    }
    try:
        resp = db.table("frontdesk_invoices").insert(inv_row).execute()
        created = (resp.data or [inv_row])[0]
    except Exception as exc:
        logger.error("Quick-request invoice insert error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create invoice")

    try:
        audit_event(
            "frontdesk_quick_request_created",
            {"invoice_id": invoice_id, "walk_in_id": walk_in_id, "customer_id": customer_id, "total": total_amount},
            actor_id=actor_id,
            event_class="frontdesk",
            action="quick_request",
            subject_type="invoice",
            subject_id=invoice_id,
        )
    except Exception:
        pass

    await _broadcast_frontdesk("invoice_qc_pending", invoice_id, walk_in_id, "qc_pending")

    return {"status": "created", "invoice": created, "walk_in_id": walk_in_id}

