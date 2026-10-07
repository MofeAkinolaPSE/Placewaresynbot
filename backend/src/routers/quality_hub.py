"""Inventory & Quality API (/quality): the connected QC / Compliance / ACE Books / calendar layer.
See services/quality_hub.py for the rules; the QC and Compliance routers delegate recalls and
batch release here so there is one behaviour whichever screen is used."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from src.middleware import verify_jwt
from src.services import quality_hub as qh

log = logging.getLogger(__name__)
router = APIRouter(prefix="/quality", tags=["quality"])

READ_ROLES = {"admin", "ops", "operations", "finance", "sales", "quality_assurance", "qa", "management", "procurement"}
QA_ROLES = {"admin", "quality_assurance", "qa"}
SCHEDULE_ROLES = {"admin", "quality_assurance", "qa", "ops", "operations", "management"}
WRITE_OFF_ROLES = {"admin", "quality_assurance", "qa", "ops", "operations", "finance"}


def _roles(user: Dict[str, Any]) -> set:
    return {str(r).lower() for r in (user.get("roles") or [])}


def _need(allowed: set):
    def dep(request: Request) -> Dict[str, Any]:
        user = verify_jwt(request)
        if not _roles(user) & allowed:
            raise HTTPException(403, "Your role cannot do this")
        return user
    return dep


def _call(fn, *a, **k):
    from src.fin.errors import FinError
    try:
        return fn(*a, **k)
    except HTTPException:
        raise
    except qh.QualityError as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except FinError as e:
        raise HTTPException(e.status, e.to_detail().get("message") if isinstance(e.to_detail(), dict) else str(e))
    except Exception:
        log.exception("quality endpoint failed")
        raise HTTPException(500, "Internal server error")


@router.get("/overview")
def overview(_u=Depends(_need(READ_ROLES))):
    return _call(qh.overview)


@router.get("/expiry")
def expiry(window_days: int = Query(180, ge=7, le=730), _u=Depends(_need(READ_ROLES))):
    return _call(qh.expiry_by_product, window_days)


@router.post("/lots/{batch_id}/quarantine")
def quarantine(batch_id: str, payload: Dict[str, Any] = Body(default={}), user=Depends(_need(QA_ROLES))):
    return _call(qh.quarantine_lot, user, batch_id, payload.get("reason") or "")


@router.post("/lots/{batch_id}/release")
def release_lot(batch_id: str, payload: Dict[str, Any] = Body(default={}), user=Depends(_need(QA_ROLES))):
    return _call(qh.release_lot, user, batch_id, payload.get("reason") or "")


@router.post("/lots/{batch_id}/write-off")
def write_off(batch_id: str, payload: Dict[str, Any] = Body(default={}), user=Depends(_need(WRITE_OFF_ROLES))):
    return _call(qh.write_off_lot, user, batch_id, payload.get("reason_code") or "EXPIRY", payload.get("notes"))


# Recalls ---------------------------------------------------------------------

@router.get("/recalls")
def recalls(status: Optional[str] = None, _u=Depends(_need(READ_ROLES))):
    return {"recalls": _call(qh.list_recalls, status)}


@router.get("/recalls/{recall_id}")
def recall(recall_id: str, _u=Depends(_need(READ_ROLES))):
    return _call(qh.get_recall, recall_id)


@router.post("/recalls", status_code=201)
def open_recall(payload: Dict[str, Any] = Body(...), user=Depends(_need(QA_ROLES))):
    return _call(qh.initiate_recall, user, payload)


@router.post("/recalls/{recall_id}/returns")
def recall_return(recall_id: str, payload: Dict[str, Any] = Body(...), user=Depends(_need(QA_ROLES | {"finance", "management"}))):
    """A customer brings recalled stock back: credit note on the invoice they bought it on."""
    return _call(qh.record_return, user, recall_id, payload)


@router.get("/customer-invoices")
def customer_invoices(customer_id: int, batch_id: Optional[str] = None, sku: Optional[str] = None,
                      _u=Depends(_need(READ_ROLES))):
    return {"invoices": _call(qh.customer_invoices_for_batch, customer_id, batch_id, sku)}


@router.patch("/recalls/{recall_id}")
def update_recall(recall_id: str, payload: Dict[str, Any] = Body(...), user=Depends(_need(QA_ROLES))):
    return _call(qh.update_recall, user, recall_id, payload)


# Batch release ---------------------------------------------------------------

@router.get("/batches")
def batches(_u=Depends(_need(READ_ROLES))):
    return _call(qh.list_batches)


@router.post("/batches", status_code=201)
def register_batch(payload: Dict[str, Any] = Body(...), user=Depends(_need(SCHEDULE_ROLES))):
    if payload.get("release_now") and not _roles(user) & QA_ROLES:
        raise HTTPException(403, "Only Quality Assurance can release a batch")
    return _call(qh.register_batch, user, payload)


@router.post("/batches/{registry_id}/release")
def release_batch(registry_id: str, payload: Dict[str, Any] = Body(default={}), user=Depends(_need(QA_ROLES))):
    return _call(qh.release_batch, user, registry_id, payload)


@router.post("/batches/{registry_id}/reject")
def reject_batch(registry_id: str, payload: Dict[str, Any] = Body(...), user=Depends(_need(QA_ROLES))):
    return _call(qh.reject_batch, user, registry_id, payload.get("reason") or "", payload.get("notes"))


# Deviations, audits, maintenance ---------------------------------------------

@router.get("/deviations")
def deviations(status: Optional[str] = None, _u=Depends(_need(READ_ROLES))):
    return {"deviations": _call(qh.list_deviations, status)}


@router.post("/deviations", status_code=201)
def raise_deviation(payload: Dict[str, Any] = Body(...), user=Depends(_need(SCHEDULE_ROLES))):
    return _call(qh.raise_deviation, user, payload)


@router.patch("/deviations/{dev_id}")
def update_deviation(dev_id: str, payload: Dict[str, Any] = Body(...), user=Depends(_need(SCHEDULE_ROLES))):
    return _call(qh.update_deviation, user, dev_id, payload)


@router.post("/audits", status_code=201)
def schedule_audit(payload: Dict[str, Any] = Body(...), user=Depends(_need(SCHEDULE_ROLES))):
    return _call(qh.schedule_audit, user, payload)


@router.post("/maintenance", status_code=201)
def schedule_maintenance(payload: Dict[str, Any] = Body(...), user=Depends(_need(SCHEDULE_ROLES))):
    return _call(qh.schedule_maintenance, user, payload)


# Calendar --------------------------------------------------------------------

@router.get("/calendar")
def calendar(date_from: dt.date = Query(..., alias="from"), date_to: dt.date = Query(..., alias="to"),
             _u=Depends(verify_jwt)):
    if (date_to - date_from).days > 120:
        raise HTTPException(400, "Ask for at most 120 days at a time")
    return _call(qh.calendar_feed, date_from, date_to)


@router.patch("/calendar/{kind}/{item_id:path}")
def move(kind: str, item_id: str, payload: Dict[str, Any] = Body(...), user=Depends(_need(SCHEDULE_ROLES))):
    return _call(qh.reschedule, user, kind, item_id, payload.get("date"))
