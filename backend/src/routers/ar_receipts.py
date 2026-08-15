"""ar_receipts.py — Customer Receipts & Accounts.

The AR write-side counterpart to finance.py's existing read-only
/finance/ar/aging and /finance/ar/match endpoints. See
backend/docs/ACE-Customer-Receipts-Workspace.md for the full design.

Records a customer payment against one or more open invoices. Immutable
after posting — the only allowed transition is posted -> voided (terminal,
requires a reason). Never writes to sage_ar_snapshot; true outstanding
balance is read from the v_ar_receivables_open view (migration 098).
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.db import db, audit_event
from src.routers.finance import _require_finance

log = logging.getLogger(__name__)
router = APIRouter(prefix="/finance/ar/receipts", tags=["Finance"])

_VALID_METHODS = {
    "cash", "card", "bank_transfer", "mobile_payment",
    "corporate_account", "split_payment", "cheque", "pos",
}

_VALID_TRANSITIONS = {
    "posted": ["voided"],
    "voided": [],
}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ReceiptApplicationIn(BaseModel):
    invoice_id: str
    amount_applied: float = Field(gt=0)


class ReceiptIn(BaseModel):
    customer_id: str
    customer_name: Optional[str] = None
    amount: float = Field(gt=0)
    payment_method: str
    reference: Optional[str] = None
    collector: Optional[str] = None
    receipt_date: Optional[str] = None
    notes: Optional[str] = None
    applications: List[ReceiptApplicationIn] = Field(default_factory=list)


class VoidIn(BaseModel):
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.date.today().isoformat()


def _open_invoices_for(customer_id: str) -> List[Dict[str, Any]]:
    rows = (
        db.table("v_ar_receivables_open")
        .select("*")
        .eq("customer_id", customer_id)
        .gt("true_outstanding_balance", 0)
        .order("due_date")
        .limit(500)
        .execute()
        .data
        or []
    )
    return rows


def _receipt_applications(receipt_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Applications grouped by receipt_id, for a batch of receipt ids."""
    if not receipt_ids:
        return {}
    rows = (
        db.table("ar_receipt_applications")
        .select("*")
        .in_("receipt_id", receipt_ids)
        .execute()
        .data
        or []
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["receipt_id"], []).append(r)
    return grouped


# ---------------------------------------------------------------------------
# List + summary
# ---------------------------------------------------------------------------

@router.get("")
def list_receipts(
    request: Request,
    status: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    payment_method: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    _require_finance(request)
    try:
        query = db.table("ar_receipts").select("*").order("created_at", desc=True)
        if status:
            query = query.eq("status", status)
        if customer_id:
            query = query.eq("customer_id", customer_id)
        if payment_method:
            query = query.eq("payment_method", payment_method)
        if date_from:
            query = query.gte("receipt_date", date_from)
        if date_to:
            query = query.lte("receipt_date", date_to)

        # No OR-across-columns support in the DB wrapper — fetch a bounded
        # candidate set with the structured filters applied, then filter `q`
        # across receipt_number/customer_name/reference in Python before
        # paginating. Mirrors finance.py's own /ar/match style (fetch via
        # .table(), aggregate/filter in Python).
        all_rows = query.limit(2000).execute().data or []
        if q:
            needle = q.strip().lower()
            all_rows = [
                r for r in all_rows
                if needle in (r.get("receipt_number") or "").lower()
                or needle in (r.get("customer_name") or "").lower()
                or needle in (r.get("reference") or "").lower()
            ]

        total = len(all_rows)
        page = all_rows[offset: offset + limit]

        # Summary block — computed from the full (unpaginated, but
        # status/date/customer/method-filtered) set so the KPI strip is
        # never wrong under pagination.
        today = _today()
        today_rows = [r for r in all_rows if r.get("status") == "posted" and r.get("receipt_date") == today]
        posted_rows = [r for r in all_rows if r.get("status") == "posted"]
        thirty_days_ago = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        voided_30d = [
            r for r in all_rows
            if r.get("status") == "voided" and (r.get("voided_at") or "")[:10] >= thirty_days_ago
        ]

        posted_ids = [r["id"] for r in posted_rows]
        apps_by_receipt = _receipt_applications(posted_ids)
        unapplied_total = 0.0
        for r in posted_rows:
            allocated = sum(a["amount_applied"] for a in apps_by_receipt.get(r["id"], []))
            unapplied_total += max(float(r["amount"]) - allocated, 0.0)

        summary = {
            "today_total": round(sum(float(r["amount"]) for r in today_rows), 2),
            "today_count": len(today_rows),
            "unapplied_total": round(unapplied_total, 2),
            "voided_30d_count": len(voided_30d),
        }

        return {"data": page, "count": total, "limit": limit, "offset": offset, "summary": summary}
    except Exception as e:
        log.error("/finance/ar/receipts list error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list receipts")


@router.get("/{receipt_id}")
def get_receipt(request: Request, receipt_id: str):
    _require_finance(request)
    try:
        rows = db.table("ar_receipts").select("*").eq("id", receipt_id).limit(1).execute().data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Receipt not found")
        receipt = rows[0]

        applications = (
            db.table("ar_receipt_applications")
            .select("*")
            .eq("receipt_id", receipt_id)
            .execute()
            .data
            or []
        )
        # Enrich each allocation with light invoice display fields so a
        # voided/old receipt still displays correctly even if the invoice
        # has since dropped out of the customer's "open" list.
        invoice_ids = [a["invoice_id"] for a in applications]
        invoice_info: Dict[str, Any] = {}
        if invoice_ids:
            inv_rows = (
                db.table("v_ar_invoices")
                .select("invoice_id,invoice_date,total_amount")
                .in_("invoice_id", invoice_ids)
                .execute()
                .data
                or []
            )
            invoice_info = {r["invoice_id"]: r for r in inv_rows}
        for a in applications:
            a["invoice"] = invoice_info.get(a["invoice_id"])

        return {**receipt, "applications": applications}
    except HTTPException:
        raise
    except Exception as e:
        log.error("/finance/ar/receipts/%s get error: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch receipt")


# ---------------------------------------------------------------------------
# Create / post
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_receipt(request: Request, body: ReceiptIn):
    """Create and post a receipt in one call — no draft/approval step.

    Immutable after confirmation (SHAS-107): there is no PATCH/PUT on the
    core fields, only /void.
    """
    user = _require_finance(request)

    if body.payment_method not in _VALID_METHODS:
        raise HTTPException(status_code=422, detail=f"Invalid payment_method. Allowed: {sorted(_VALID_METHODS)}")

    applications = body.applications
    allocated_total = sum(a.amount_applied for a in applications)
    if allocated_total - body.amount > 0.01:
        raise HTTPException(
            status_code=422,
            detail=f"Sum of applications ({allocated_total}) exceeds receipt amount ({body.amount})",
        )

    try:
        # Validate each allocation against the invoice's true outstanding
        # balance at write time — over-application is rejected, not clamped.
        if applications:
            open_rows = _open_invoices_for(body.customer_id)
            open_by_invoice = {r["invoice_id"]: r for r in open_rows}
            for app in applications:
                inv = open_by_invoice.get(app.invoice_id)
                available = float(inv["true_outstanding_balance"]) if inv else 0.0
                if app.amount_applied - available > 0.01:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Allocation of {app.amount_applied} to invoice {app.invoice_id} "
                            f"exceeds its outstanding balance ({available})"
                        ),
                    )

        receipt_row = {
            "customer_id": body.customer_id,
            "customer_name": body.customer_name,
            "amount": body.amount,
            "payment_method": body.payment_method,
            "reference": body.reference,
            "collector": body.collector,
            "receipt_date": body.receipt_date or _today(),
            "status": "posted",
            "notes": body.notes,
            "created_by": user.get("sub") or user.get("email") or "unknown",
        }
        created = db.table("ar_receipts").insert(receipt_row).execute().data
        receipt = created[0] if created else receipt_row
        receipt_id = receipt["id"]

        for app in applications:
            db.table("ar_receipt_applications").insert({
                "receipt_id": receipt_id,
                "invoice_id": app.invoice_id,
                "amount_applied": app.amount_applied,
            }).execute()

        audit_event(
            "ar_receipt_posted",
            {"amount": body.amount, "payment_method": body.payment_method, "applications": len(applications)},
            actor_id=user.get("sub"),
            subject_type="ar_receipt",
            subject_id=receipt_id,
        )
        log.info("AR receipt posted: customer=%s amount=%s by=%s", body.customer_id, body.amount, user.get("sub"))
        return {**receipt, "applications": [a.model_dump() for a in applications]}
    except HTTPException:
        raise
    except Exception as e:
        log.error("/finance/ar/receipts create error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create receipt")


# ---------------------------------------------------------------------------
# Void
# ---------------------------------------------------------------------------

@router.patch("/{receipt_id}/void")
def void_receipt(request: Request, receipt_id: str, body: VoidIn):
    user = _require_finance(request)
    try:
        rows = db.table("ar_receipts").select("id,status").eq("id", receipt_id).limit(1).execute().data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Receipt not found")
        current_status = rows[0]["status"]
        allowed = _VALID_TRANSITIONS.get(current_status, [])
        if "voided" not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot void a receipt in status '{current_status}'",
            )

        update = {
            "status": "voided",
            "void_reason": body.reason,
            "voided_by": user.get("sub") or user.get("email") or "unknown",
            "voided_at": datetime.datetime.utcnow().isoformat(),
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }
        result = db.table("ar_receipts").update(update).eq("id", receipt_id).execute().data
        updated = result[0] if result else {**rows[0], **update}

        audit_event(
            "ar_receipt_voided",
            {"reason": body.reason},
            actor_id=user.get("sub"),
            subject_type="ar_receipt",
            subject_id=receipt_id,
            reason_code=body.reason,
        )
        log.info("AR receipt %s voided by %s: %s", receipt_id, user.get("sub"), body.reason)
        return updated
    except HTTPException:
        raise
    except Exception as e:
        log.error("/finance/ar/receipts/%s/void error: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to void receipt")


# ---------------------------------------------------------------------------
# Customer lookup (autocomplete) + open invoices
# ---------------------------------------------------------------------------

@router.get("/customers/search")
def search_customers(request: Request, q: str = Query(..., min_length=1)):
    _require_finance(request)
    try:
        rows = (
            db.table("v_customers")
            .select("customer_id,name,phone,email")
            .ilike("name", f"%{q}%")
            .limit(15)
            .execute()
            .data
            or []
        )
        return {"data": [r for r in rows if (r.get("name") or "").strip()]}
    except Exception as e:
        log.error("/finance/ar/receipts/customers/search error: %s", e)
        raise HTTPException(status_code=500, detail="Customer search failed")


@router.get("/customers/{customer_id}/open-invoices")
def customer_open_invoices(request: Request, customer_id: str):
    _require_finance(request)
    try:
        return {"data": _open_invoices_for(customer_id)}
    except Exception as e:
        log.error("/finance/ar/receipts/customers/%s/open-invoices error: %s", customer_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch open invoices")
