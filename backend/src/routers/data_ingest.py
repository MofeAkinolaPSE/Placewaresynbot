"""
Data Ingest Router — /data/ingest/*

Provides structured JSON endpoints for pushing financial and customer data
directly into the Placeware snapshot tables without requiring a full Sage CSV
bundle upload.  Each endpoint is idempotent-friendly: GL rows are batch-stamped
and customer rows are upserted on customer_id. Both auto-promote the batch to
the active KPI batch if no promoted batch already exists.

Endpoints:
    POST /data/ingest/financials  — Insert GL P&L entries into sage_gl_snapshot
    POST /data/ingest/customers   — Upsert customer master into sage_customers_snapshot
                                    and CRM customers table
"""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.cache import invalidate_cache_tags
from src.constants import TABLE_KPI_PROMOTIONS
from src.db import db, insert_snapshot, create_import_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/ingest", tags=["data-ingest"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_roles(request: Request, allowed: set[str]) -> Dict[str, Any]:
    from src.middleware import verify_jwt
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    if not (roles & allowed):
        raise HTTPException(
            status_code=403,
            detail=f"Role required: {sorted(allowed)}. Got: {sorted(roles)}",
        )
    return payload


def _auto_promote_batch(domain: str, batch_id: str, job_id: Optional[str], quality_score: float = 100.0) -> bool:
    """Promote batch_id to the active KPI batch for this domain.

    Re-promotes on every successful ingest (upsert on domain) rather than only
    the first-ever batch — a select-then-insert-only-if-none guard used to
    leave every subsequent import unpromoted, pinning executive_summary()'s
    freshness/AR-aging batch resolution to whichever batch happened to import
    first and never updating it again.
    """
    try:
        from src.db import set_promoted_kpi_batch
        set_promoted_kpi_batch(
            domain=domain,
            batch_id=batch_id,
            job_id=job_id,
            quality_score=quality_score,
            rejection_rate=0.0,
            reason="auto_promote_latest_batch",
        )
        return True
    except Exception as exc:
        logger.warning(f"_auto_promote_batch failed for domain={domain}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GLEntry(BaseModel):
    """A single General Ledger line entry — mirrors sage_gl_snapshot columns."""
    period: str = Field(..., description="Accounting period, e.g. '2026-01'")
    account_code: str = Field(..., description="Chart-of-accounts code, e.g. '4000'")
    account_name: Optional[str] = Field(None, description="Human-readable account name")
    debit: float = Field(default=0.0, ge=0)
    credit: float = Field(default=0.0, ge=0)

    @field_validator("period")
    @classmethod
    def _validate_period(cls, v: str) -> str:
        # Allow YYYY-MM or YYYY-MM-DD
        if len(v) < 7 or v[4] != "-":
            raise ValueError("period must be YYYY-MM or YYYY-MM-DD format")
        return v[:7]  # normalise to YYYY-MM


class FinancialIngestPayload(BaseModel):
    """Payload for POST /data/ingest/financials."""
    entries: List[GLEntry] = Field(..., min_length=1, description="GL line entries")
    batch_label: Optional[str] = Field(None, description="Optional human label for this batch")


class CustomerRecord(BaseModel):
    """A single customer master record."""
    customer_id: str = Field(..., description="Unique customer identifier from Sage")
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = Field(default="active")
    segment: Optional[str] = Field(None, description="e.g. 'hospital', 'pharmacy', 'clinic'")
    region: Optional[str] = None
    contact_details: Optional[Dict[str, Any]] = None


class CustomerIngestPayload(BaseModel):
    """Payload for POST /data/ingest/customers."""
    customers: List[CustomerRecord] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/financials")
async def ingest_financials(payload: FinancialIngestPayload, request: Request):
    """Insert GL P&L entries into sage_gl_snapshot and auto-promote the batch.

    Roles: admin, finance
    """
    user = _require_roles(request, {"admin", "finance"})

    if not payload.entries:
        raise HTTPException(status_code=400, detail="entries must be a non-empty list")

    # Validate no duplicate (period, account_code) within the submitted batch
    seen: set[tuple] = set()
    for entry in payload.entries:
        key = (entry.period, entry.account_code)
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate entry: period={entry.period}, account_code={entry.account_code}",
            )
        seen.add(key)

    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()
    domain = "sage"

    # Create import job record
    job_id = create_import_job(
        domain=domain,
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={
            "source": "data_ingest_api",
            "batch_label": payload.batch_label or "manual_gl_ingest",
            "entry_count": len(payload.entries),
            "actor": user.get("sub"),
        },
        status="running",
    )

    rows = [e.model_dump() for e in payload.entries]
    try:
        inserted = insert_snapshot("sage_gl_snapshot", batch_id, imported_at, rows)
    except Exception as exc:
        logger.error(f"ingest_financials: snapshot insert failed: {exc}")
        raise HTTPException(status_code=500, detail=f"GL snapshot insert failed: {exc}")

    # Mark import job succeeded
    if job_id:
        try:
            db.table("placeware_import_jobs").update({
                "status": "succeeded",
                "finished_at": imported_at,
                "row_count": inserted,
            }).eq("id", job_id).execute()
        except Exception:
            pass

    promoted = _auto_promote_batch(domain, batch_id, job_id)

    # Bust finance caches so kpis() picks up new data immediately
    invalidate_cache_tags("finance", "finance_kpis", "finance_trend", "executive", "executive_summary")

    logger.info(
        f"ingest_financials: inserted {inserted} GL rows, batch={batch_id}, "
        f"promoted={promoted}, actor={user.get('sub')}"
    )
    return {
        "batch_id": batch_id,
        "rows_inserted": inserted,
        "promoted": promoted,
        "domain": domain,
        "imported_at": imported_at,
    }


@router.post("/customers")
async def ingest_customers(payload: CustomerIngestPayload, request: Request):
    """Upsert customer master into sage_customers_snapshot and the CRM customers table.

    Roles: admin, sales, finance
    """
    user = _require_roles(request, {"admin", "sales", "finance"})

    imported_at = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()
    upserted_snapshot = 0
    upserted_crm = 0
    skipped: List[str] = []

    for rec in payload.customers:
        customer_dict = rec.model_dump()

        # --- sage_customers_snapshot upsert ---
        # Non-fatal: snapshot table has no unique index on customer_id (batch upload
        # owns that path). If this upsert fails, proceed to the CRM write anyway.
        try:
            sage_row = {
                "customer_id": rec.customer_id,
                "name": rec.name,
                "email": rec.email,
                "phone": rec.phone,
                "status": rec.status or "active",
                "imported_at": imported_at,
            }
            db.table("sage_customers_snapshot").insert(sage_row).execute()
            upserted_snapshot += 1
        except Exception as exc:
            logger.debug(f"ingest_customers: sage_customers_snapshot insert skipped for {rec.customer_id}: {exc}")

        # --- CRM customers table upsert ---
        try:
            contact_details = rec.contact_details or {}
            if rec.email:
                contact_details.setdefault("email", rec.email)
            if rec.phone:
                contact_details.setdefault("phone", rec.phone)
            if rec.segment:
                contact_details.setdefault("segment", rec.segment)
            if rec.region:
                contact_details.setdefault("region", rec.region)

            crm_row = {
                "name": rec.name,
                "customer_code": rec.customer_id,
                "contact_details": contact_details,
                "risk_score": 0,
            }
            db.table("customers").upsert(crm_row, on_conflict="customer_code").execute()
            upserted_crm += 1
        except Exception as exc:
            # CRM upsert is best-effort — snapshot already succeeded
            logger.warning(f"ingest_customers: CRM upsert failed for {rec.customer_id}: {exc}")

    # Bust relevant caches
    invalidate_cache_tags("crm", "executive", "finance_kpis", "executive_summary")

    logger.info(
        f"ingest_customers: snapshot={upserted_snapshot}, crm={upserted_crm}, "
        f"skipped={len(skipped)}, actor={user.get('sub')}"
    )
    return {
        "upserted_snapshot": upserted_snapshot,
        "upserted_crm": upserted_crm,
        "skipped_count": len(skipped),
        "skipped_ids": skipped[:20],
        "imported_at": imported_at,
    }
