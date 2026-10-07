"""sage_export.py — ACE -> Sage 50 export bridge (the reverse of sage_csv_import.py).

Sage 50 2013 has no usable write API, so ACE produces a ZIP of CSVs in the
exact layout of the client's own Sage Import/Export templates. The accountant
imports them via File > Select Import/Export and Sage posts the GL, P&L,
balance sheet and stock itself. Design: backend/docs/Latestmods-TB/sage-link/.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.db import audit_event
from src.routers.finance import _require_finance
from src.services.sage_export import service as S

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sage/export", tags=["Sage Export"])


class BatchIn(BaseModel):
    date_from: dt.date
    date_to: dt.date
    # Which Sage documents to produce (customer / sales / receipts / adjust).
    # Omitted = all of them.
    docs: Optional[List[str]] = None


class SettingsIn(BaseModel):
    cutover_date: Optional[dt.date] = None
    ar_account: Optional[str] = None
    writeoff_gl_account: Optional[str] = None
    delivery_gl_account: Optional[str] = None
    discount_gl_account: Optional[str] = None
    period_anchor_month: Optional[dt.date] = None
    period_anchor_number: Optional[int] = None
    payment_method_map: Optional[Dict[str, Dict[str, str]]] = None
    column_selection: Optional[Dict[str, List[str]]] = None
    # Last date Sage's open fiscal years cover; later records are held back.
    sage_open_until: Optional[dt.date] = None


def _actor(user: Dict[str, Any]) -> Optional[str]:
    return user.get("email") or user.get("sub")


@router.get("/preview")
async def preview(
    request: Request,
    date_from: dt.date = Query(..., alias="from"),
    date_to: dt.date = Query(..., alias="to"),
):
    _require_finance(request)
    try:
        return S.public_plan(S.plan(date_from, date_to))
    except S.ExportError as exc:
        raise HTTPException(400, detail=str(exc))


@router.post("/batches")
async def create_batch(body: BatchIn, request: Request):
    user = _require_finance(request)
    try:
        result = S.generate(body.date_from, body.date_to, _actor(user), body.docs)
    except S.ExportError as exc:
        raise HTTPException(400, detail=str(exc))
    try:
        audit_event("sage_export_batch_created", {"batch_id": result["id"], "counts": result["counts"]},
                    actor_id=user.get("sub"))
    except Exception:
        pass
    return result


@router.get("/batches")
async def list_batches(request: Request, limit: int = Query(50, ge=1, le=200)):
    _require_finance(request)
    return {"batches": S.list_batches(limit)}


@router.get("/batches/{batch_id}/download")
async def download_batch(batch_id: str, request: Request):
    _require_finance(request)
    try:
        name, payload = S.batch_zip(batch_id)
    except S.ExportError as exc:
        raise HTTPException(404, detail=str(exc))
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/batches/{batch_id}/files/{file_name}")
async def download_file(batch_id: str, file_name: str, request: Request):
    """One Sage import file (e.g. SALES.CSV) from a batch."""
    _require_finance(request)
    try:
        payload = S.batch_file(batch_id, file_name)
    except S.ExportError as exc:
        raise HTTPException(404, detail=str(exc))
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.delete("/batches/{batch_id}")
async def delete_batch(batch_id: str, request: Request):
    """Release a batch that was NOT imported into Sage so it can be re-exported."""
    user = _require_finance(request)
    if not S.delete_batch(batch_id):
        raise HTTPException(404, detail="Batch not found")
    try:
        audit_event("sage_export_batch_deleted", {"batch_id": batch_id}, actor_id=user.get("sub"))
    except Exception:
        pass
    return {"deleted": batch_id}


@router.get("/settings")
async def get_settings(request: Request):
    _require_finance(request)
    return S._public_settings(S.get_settings())


@router.put("/settings")
async def put_settings(body: SettingsIn, request: Request):
    user = _require_finance(request)
    changes = body.model_dump(exclude_unset=True)
    for k in ("writeoff_gl_account", "ar_account", "delivery_gl_account", "discount_gl_account"):
        if k in changes and isinstance(changes[k], str):
            changes[k] = changes[k].strip() or None
    for k in ("ar_account", "delivery_gl_account", "discount_gl_account", "period_anchor_month", "period_anchor_number"):
        if k in changes and changes[k] is None:
            changes.pop(k)  # NOT NULL columns: ignore a clear rather than 500
    return S._public_settings(S.update_settings(changes, _actor(user)))
