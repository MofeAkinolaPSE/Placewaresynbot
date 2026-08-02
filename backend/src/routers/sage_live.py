"""
sage_live.py — Live Sage 50 proxy router for SynBot.

All requests are forwarded to the Sage Bridge service running on the
Windows 7 host machine.  The bridge handles the actual Sage SDK / ODBC
calls; this router is purely a secure proxy + audit layer.

Environment variables required (add to backend/.env):
    SAGE_BRIDGE_URL   — http://<Windows7_LAN_IP>:7070
    SAGE_BRIDGE_KEY   — shared API key (same as bridge's BRIDGE_API_KEY)

The /sage/webhook endpoint receives change-push events from the bridge's
file watcher and triggers a background sync to update Supabase caches.
"""
from __future__ import annotations

import datetime
import hmac
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.middleware import verify_jwt, require_role
from src.db import db, audit_event

logger = logging.getLogger("synbot.sage_live")

router = APIRouter(prefix="/sage/live", tags=["sage-live"])

# ── Bridge client config ──────────────────────────────────────────────────────

SAGE_BRIDGE_URL = os.getenv("SAGE_BRIDGE_URL", "http://SAGE_BRIDGE_HOST_PLACEHOLDER:7070")
SAGE_BRIDGE_KEY = os.getenv("SAGE_BRIDGE_KEY", "")

_BRIDGE_TIMEOUT = 30  # seconds


def _bridge_headers() -> Dict[str, str]:
    return {"X-Bridge-API-Key": SAGE_BRIDGE_KEY}


async def _bridge_get(path: str, params: Optional[Dict] = None) -> Any:
    """Forward a GET to the bridge. Raises HTTPException on failure."""
    url = f"{SAGE_BRIDGE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=_bridge_headers())
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=resp.json().get("detail", "Not found"))
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Sage Bridge at {SAGE_BRIDGE_URL}. "
                   "Ensure the bridge service is running on the Windows machine.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Bridge GET %s failed: %s", path, exc)
        raise HTTPException(status_code=503, detail=f"Bridge error: {exc}") from exc


async def _bridge_post(path: str, body: Dict) -> Any:
    """Forward a POST to the bridge."""
    url = f"{SAGE_BRIDGE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=_bridge_headers())
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach Sage Bridge at {SAGE_BRIDGE_URL}.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Bridge POST %s failed: %s", path, exc)
        raise HTTPException(status_code=503, detail=f"Bridge error: {exc}") from exc


async def _bridge_put(path: str, body: Dict) -> Any:
    """Forward a PUT to the bridge."""
    url = f"{SAGE_BRIDGE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as client:
            resp = await client.put(url, json=body, headers=_bridge_headers())
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Cannot reach Sage Bridge at {SAGE_BRIDGE_URL}.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Bridge PUT %s failed: %s", path, exc)
        raise HTTPException(status_code=503, detail=f"Bridge error: {exc}") from exc


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_sage_access(request: Request) -> Dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {"admin", "finance", "management", "staff"}
    if not roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Insufficient role for Sage access")
    return payload


def _require_sage_write(request: Request) -> Dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {"admin", "finance"}
    if not roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Write access requires admin or finance role")
    return payload


# ── HEALTH ────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["sage-live"])
async def bridge_health(request: Request, payload: Dict = Depends(_require_sage_access)):
    """Check connectivity to the Sage Bridge service."""
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(f"{SAGE_BRIDGE_URL}/health")
            return resp.json()
        except Exception as exc:
            return {"status": "unreachable", "error": str(exc)}


# ── SYNC STATUS ───────────────────────────────────────────────────────────────

@router.get("/sync/status")
async def sage_sync_status(request: Request, payload: Dict = Depends(_require_sage_access)):
    """Return bridge sync status + Sage company info."""
    return await _bridge_get("/sync/status")


@router.get("/sync/company")
async def sage_company_info(request: Request, payload: Dict = Depends(_require_sage_access)):
    """Return Sage company information."""
    return await _bridge_get("/sync/company")


@router.get("/sync/schema/tables")
async def sage_schema_tables(request: Request, payload: Dict = Depends(_require_sage_access)):
    """
    List all ODBC-visible table names from the Pervasive DSN.
    Use during setup to verify DSN connection and confirm table names.
    """
    return await _bridge_get("/sync/schema/tables")


# ── CUSTOMERS ─────────────────────────────────────────────────────────────────

@router.get("/customers")
async def list_customers(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/customers", params={"limit": limit, "offset": offset, "search": search})


@router.get("/customers/{customer_id}")
async def get_customer(
    request: Request,
    customer_id: str,
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get(f"/customers/{customer_id}")


class CustomerCreateReq(BaseModel):
    id: str
    name: str
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    phone: str = ""
    fax: str = ""
    email: str = ""
    contact: str = ""
    credit_limit: float = 0.0
    sales_rep: str = ""


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    request: Request,
    body: CustomerCreateReq,
    background_tasks: BackgroundTasks,
    payload: Dict = Depends(_require_sage_write),
):
    """Create a customer in Sage 50 and log the sync event."""
    result = await _bridge_post("/customers", body.model_dump())
    background_tasks.add_task(
        _log_sync_event,
        entity_type="customer",
        direction="synbot_to_sage",
        synbot_id=body.id,
        sage_id=result.get("id"),
        status="success",
    )
    await audit_event(db, payload.get("sub", "system"), "sage_customer_created", result)
    return result


@router.put("/customers/{customer_id}")
async def update_customer(
    request: Request,
    customer_id: str,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    result = await _bridge_put(f"/customers/{customer_id}", body)
    await audit_event(db, payload.get("sub", "system"), "sage_customer_updated", {"id": customer_id})
    return result


# ── INVOICES ──────────────────────────────────────────────────────────────────

@router.get("/invoices")
async def list_invoices(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    customer_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get(
        "/invoices",
        params={
            "limit": limit, "offset": offset,
            "customer_id": customer_id,
            "from_date": from_date, "to_date": to_date,
        },
    )


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    request: Request,
    invoice_id: str,
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get(f"/invoices/{invoice_id}")


class InvoiceLineReq(BaseModel):
    description: str = ""
    quantity: float = 1.0
    unit_price: float = 0.0
    gl_account: str = ""
    item_id: str = ""


class InvoiceCreateReq(BaseModel):
    customer_id: str
    date: str
    due_date: str
    lines: List[InvoiceLineReq]
    invoice_number: str = ""
    ship_date: Optional[str] = None
    po_number: str = ""
    reference: str = ""
    note: str = ""
    synbot_invoice_id: Optional[str] = Field(
        default=None,
        description="SynBot's internal invoice ID — stored in sync log for traceability",
    )


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    request: Request,
    body: InvoiceCreateReq,
    background_tasks: BackgroundTasks,
    payload: Dict = Depends(_require_sage_write),
):
    """
    Create a Sales Invoice in Sage 50.
    Triggers Sage's full ledger posting (AR, tax, GL).
    Returns the created invoice with its Sage ID.
    """
    sage_payload = body.model_dump(exclude={"synbot_invoice_id"})
    result = await _bridge_post("/invoices", sage_payload)
    sage_id = result.get("sage_id")

    background_tasks.add_task(
        _log_sync_event,
        entity_type="invoice",
        direction="synbot_to_sage",
        synbot_id=body.synbot_invoice_id,
        sage_id=sage_id,
        status="success",
    )
    await audit_event(db, payload.get("sub", "system"), "sage_invoice_created", result)
    return result


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def void_invoice(
    request: Request,
    invoice_id: str,
    payload: Dict = Depends(_require_sage_write),
):
    """Void a sales invoice in Sage. Restricted to admin/finance."""
    url = f"{SAGE_BRIDGE_URL}/invoices/{invoice_id}"
    async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as client:
        resp = await client.delete(url, headers=_bridge_headers())
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    await audit_event(db, payload.get("sub", "system"), "sage_invoice_voided", {"invoice_id": invoice_id})


# ── VENDORS ───────────────────────────────────────────────────────────────────

@router.get("/vendors")
async def list_vendors(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    search: Optional[str] = Query(default=None),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/vendors", params={"limit": limit, "search": search})


@router.get("/vendors/{vendor_id}")
async def get_vendor(request: Request, vendor_id: str, payload: Dict = Depends(_require_sage_access)):
    return await _bridge_get(f"/vendors/{vendor_id}")


@router.post("/vendors", status_code=status.HTTP_201_CREATED)
async def create_vendor(
    request: Request,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    return await _bridge_post("/vendors", body)


@router.get("/vendors/bills")
async def list_vendor_bills(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/vendors/bills", params={"limit": limit})


@router.post("/vendors/bills", status_code=status.HTTP_201_CREATED)
async def create_vendor_bill(
    request: Request,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    return await _bridge_post("/vendors/bills", body)


# ── INVENTORY ─────────────────────────────────────────────────────────────────

@router.get("/inventory")
async def list_inventory(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/inventory", params={"limit": limit, "offset": offset, "search": search})


@router.get("/inventory/low-stock")
async def low_stock(request: Request, payload: Dict = Depends(_require_sage_access)):
    return await _bridge_get("/inventory/low-stock")


@router.get("/inventory/{item_id}")
async def get_inventory_item(
    request: Request,
    item_id: str,
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get(f"/inventory/{item_id}")


# ── EMPLOYEES ─────────────────────────────────────────────────────────────────

@router.get("/employees")
async def list_employees(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/employees", params={"limit": limit})


@router.get("/employees/payroll")
async def employee_payroll(
    request: Request,
    from_date: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/employees/payroll", params={"from_date": from_date, "limit": limit})


# ── CHART OF ACCOUNTS ─────────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=5000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/accounts", params={"limit": limit})


# ── SALES ORDERS ──────────────────────────────────────────────────────────────

@router.get("/sales-orders")
async def list_sales_orders(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/sales-orders", params={"limit": limit})


@router.post("/sales-orders", status_code=status.HTTP_201_CREATED)
async def create_sales_order(
    request: Request,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    return await _bridge_post("/sales-orders", body)


# ── PURCHASE ORDERS ───────────────────────────────────────────────────────────

@router.get("/purchase-orders")
async def list_purchase_orders(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/purchase-orders", params={"limit": limit})


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    request: Request,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    return await _bridge_post("/purchase-orders", body)


# ── PAYMENTS ──────────────────────────────────────────────────────────────────

@router.get("/payments/received")
async def list_receipts(
    request: Request,
    customer_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get(
        "/payments/received",
        params={"customer_id": customer_id, "from_date": from_date, "limit": limit},
    )


@router.post("/payments/received", status_code=status.HTTP_201_CREATED)
async def apply_receipt(
    request: Request,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    return await _bridge_post("/payments/received", body)


# ── JOURNAL ENTRIES ───────────────────────────────────────────────────────────

@router.get("/journal")
async def list_journal(
    request: Request,
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get(
        "/journal",
        params={"from_date": from_date, "to_date": to_date, "limit": limit},
    )


@router.post("/journal", status_code=status.HTTP_201_CREATED)
async def create_journal_entry(
    request: Request,
    body: Dict[str, Any],
    payload: Dict = Depends(_require_sage_write),
):
    return await _bridge_post("/journal", body)


# ── QUOTES ────────────────────────────────────────────────────────────────────

@router.get("/quotes")
async def list_quotes(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/sync/quotes", params={"limit": limit})


# ── JOBS ──────────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = Query(default=500, ge=1, le=2000),
    payload: Dict = Depends(_require_sage_access),
):
    return await _bridge_get("/sync/jobs", params={"limit": limit})


# ── HISTORICAL BULK PULL ─────────────────────────────────────────────────────

@router.get("/historical/{entity_type}")
async def bulk_historical(
    request: Request,
    entity_type: str,
    limit: int = Query(default=2000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    payload: Dict = Depends(_require_sage_access),
):
    """
    Pull historical records for any entity type.
    Used for the one-time migration job to seed Supabase cache.
    """
    return await _bridge_get(
        f"/sync/historical/{entity_type}",
        params={"limit": limit, "offset": offset},
    )


# ── WEBHOOK (Sage → SynBot push) ──────────────────────────────────────────────

WEBHOOK_SECRET = os.getenv("SAGE_BRIDGE_WEBHOOK_SECRET", "")

webhook_router = APIRouter(prefix="/sage", tags=["sage-webhook"])


@webhook_router.post("/webhook")
async def sage_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Receives event pushes from the Sage Bridge.

    No JWT here — protected by the shared webhook secret header instead.

    Idempotency
    -----------
    The bridge guarantees AT-LEAST-once delivery: it retries until we return
    2xx, so the same event can legitimately arrive more than once (a retry
    after a timeout where we actually succeeded, a replay after a bridge crash,
    an operator-triggered rescan).

    Every event carries a deterministic ``event_id``. We record applied IDs and
    return **409** for one we have already processed. The bridge treats 409 as
    success and stops retrying, which turns at-least-once delivery into
    at-most-once application. This is the "never duplicate a sync" half of the
    guarantee — the bridge's durable outbox is the "never drop one" half.

    Two envelope shapes are accepted:
      * ``event=record_upserted`` — carries the full record in ``data``; applied
        directly with no pull-back to the bridge.
      * ``event=data_changed``    — legacy change ping; triggers the existing
        pull-based entity sync. Kept so entity types the bridge does not yet
        extract in full keep working unchanged.
    """
    provided_key = request.headers.get("X-Webhook-Key", "")
    if WEBHOOK_SECRET and not hmac.compare_digest(provided_key, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    entity_type = payload.get("entity_type")
    event = payload.get("event")
    event_id = payload.get("event_id") or request.headers.get("X-Event-Id", "")

    logger.info(
        "Sage webhook: event=%s entity=%s event_id=%s", event, entity_type, event_id
    )

    # ── Idempotency gate ─────────────────────────────────────────────────────
    if event_id:
        if _event_already_applied(event_id):
            logger.info("Duplicate event %s ignored (already applied).", event_id)
            # 409 tells the bridge "already done" so it stops retrying.
            return JSONResponse(
                status_code=409,
                content={"received": True, "duplicate": True, "event_id": event_id},
            )
    else:
        # An event with no ID cannot be deduplicated. Accept it (dropping it
        # would violate the no-loss guarantee) but make the gap visible.
        logger.warning(
            "Sage webhook event has no event_id — cannot deduplicate. "
            "Is the bridge older than v2.0.0?"
        )

    # ── Dispatch ─────────────────────────────────────────────────────────────
    if event == "record_upserted" and entity_type:
        from src.services.sage_sync_engine import apply_record_event
        background_tasks.add_task(apply_record_event, payload)
    elif event == "data_changed" and entity_type:
        from src.services.sage_sync_engine import schedule_entity_sync
        background_tasks.add_task(schedule_entity_sync, entity_type)
    else:
        logger.warning("Unhandled Sage webhook event=%s entity=%s", event, entity_type)

    if event_id:
        _mark_event_applied(event_id, entity_type or "", event or "")

    return {"received": True, "event_id": event_id}


def _event_already_applied(event_id: str) -> bool:
    """
    True when this event_id has already been processed.

    Fails OPEN on a database error: if we cannot tell, we process the event.
    Reprocessing is safe (the downstream upserts are idempotent on sage_id),
    whereas failing closed would drop the event entirely — the worse outcome
    given the no-loss requirement.
    """
    try:
        existing = (
            db.table("placeware_sage_event_log")
            .select("event_id")
            .eq("event_id", event_id)
            .limit(1)
            .execute()
        )
        return bool(existing.data)
    except Exception as exc:
        logger.warning(
            "Idempotency check failed for %s (%s) — processing anyway.", event_id, exc
        )
        return False


def _mark_event_applied(event_id: str, entity_type: str, event: str) -> None:
    """Record an applied event_id so a later redelivery is recognised."""
    try:
        db.table("placeware_sage_event_log").insert({
            "event_id": event_id,
            "entity_type": entity_type,
            "event": event,
            "applied_at": datetime.datetime.utcnow().isoformat() + "Z",
        }).execute()
    except Exception as exc:
        # Non-fatal: worst case is a duplicate application later, which the
        # idempotent upserts absorb.
        logger.warning("Could not record event_id %s: %s", event_id, exc)


# ── Sync log helper ───────────────────────────────────────────────────────────

async def _log_sync_event(
    entity_type: str,
    direction: str,
    synbot_id: Optional[str],
    sage_id: Optional[str],
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Insert a row into placeware_sage_sync_log for audit trail."""
    try:
        await db.table("placeware_sage_sync_log").insert({
            "entity_type": entity_type,
            "direction": direction,
            "synbot_id": synbot_id,
            "sage_id": sage_id,
            "status": status,
            "error_message": error_message,
        }).execute()
    except Exception as exc:
        logger.error("Failed to write sync log: %s", exc)
