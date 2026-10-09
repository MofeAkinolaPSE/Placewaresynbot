from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from src.middleware import verify_jwt, require_role, require_any_role
from pydantic import BaseModel
from typing import Optional, Any
from ..db import db
import hashlib, json, io, csv, logging
import datetime as dt

logger = logging.getLogger("crm")
from src.services.realtime import realtime_hub
from src.cache import invalidate_cache_tags
from src.services.oeis import process_operational_event
from src.services.places_service import search_places, cache_key as _places_cache_key

router = APIRouter(prefix="/crm", tags=["crm"])


class CustomerIn(BaseModel):
    name: str
    customer_code: Optional[str]
    contact_details: Optional[dict] = {}
    account_manager: Optional[str]


@router.post("/customers")
def create_customer(request: Request, payload: CustomerIn, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        row = payload.dict()   # created_at is defaulted by the table (sending NULL failed)
        resp = db.table("customers").insert(row).execute()
        data = resp.data or []
        return data[0] if data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# NOTE: this route must stay registered before GET /customers/{customer_id}
# below -- Starlette matches by path shape, so a request to /customers/search
# would otherwise be swallowed by the {customer_id}:int pattern and 422
# trying to coerce "search" to int.
@router.get("/customers/search")
def search_customers(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=10, le=50),
    _u=Depends(verify_jwt),
):
    """Customer search for the Centralized Customer Workspace's
    EntityAutocomplete and the bulk-message recipient picker.
    Returns {id, name, customer_code, phone, email} -- id is
    customers.id (numeric PK), matching what GET /crm/customers/{id}/360
    expects. NOT the same key space as /finance/ar/receipts/customers/search
    (that endpoint's customer_id is the Sage TEXT code from v_customers).

    TableQuery (src/local_db.py) has no .or_() -- two ILIKE queries
    (name, customer_code), merged and de-duplicated by id.
    """
    try:
        pattern = f"%{q.strip()}%"
        by_name = (
            db.table("customers").select("id,name,customer_code,contact_details")
            .ilike("name", pattern).limit(limit).execute().data or []
        )
        by_code = (
            db.table("customers").select("id,name,customer_code,contact_details")
            .ilike("customer_code", pattern).limit(limit).execute().data or []
        )
    except Exception as e:
        logger.error("customer search error: %s", e)
        raise HTTPException(status_code=500, detail="Customer search failed")

    merged: dict[int, dict] = {}
    for r in by_name + by_code:
        merged.setdefault(r["id"], r)
    ranked = sorted(merged.values(), key=lambda r: (r.get("name") or "").lower())[:limit]

    return {
        "data": [
            {
                "id": r["id"],
                "name": r.get("name"),
                "customer_code": r.get("customer_code"),
                "phone": (r.get("contact_details") or {}).get("phone"),
                "email": (r.get("contact_details") or {}).get("email"),
            }
            for r in ranked
        ]
    }


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, _u=Depends(verify_jwt)):
    try:
        resp = db.table("customers").select("*").eq("id", customer_id).limit(1).execute()
        data = resp.data or []
        if not data:
            raise HTTPException(status_code=404, detail="Customer not found")
        return data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/customers")
def list_customers(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("customers").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    contact_details: Optional[dict] = None
    account_manager: Optional[str] = None
    credit_limit: Optional[float] = None
    payment_terms_days: Optional[int] = None
    facility_type: Optional[str] = None
    client_type: Optional[str] = None
    last_ordered_at: Optional[str] = None
    storage_capacity: Optional[float] = None
    competing_supplier: Optional[str] = None


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: int, payload: CustomerUpdate, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        updates = {k: v for k, v in payload.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields provided to update")
        updates["updated_at"] = dt.datetime.utcnow().isoformat()
        resp = db.table("customers").update(updates).eq("id", customer_id).execute()
        data = resp.data or []
        if not data:
            raise HTTPException(status_code=404, detail="Customer not found")
        return data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


class LeadIn(BaseModel):
    source: Optional[str] = None
    industry: Optional[str] = None
    assigned_rep: Optional[str] = None
    stage: Optional[str] = None
    score: Optional[float] = None
    expected_value: Optional[float] = None
    linked_campaign_id: Optional[int] = None
    metadata: Optional[dict] = {}


class ProspectSourceIn(BaseModel):
    industry: Optional[str] = None
    region: Optional[str] = None
    source: Optional[str] = "internal"
    limit: Optional[int] = 20
    seed_companies: Optional[list[dict]] = None


class ProspectScoreIn(BaseModel):
    expected_value: Optional[float] = 0
    urgency: Optional[str] = "medium"
    fit_signals: Optional[dict] = None
    source: Optional[str] = "lead_finder"
    assigned_rep: Optional[str] = None
    stage: Optional[str] = "qualified"


class LeadAssignIn(BaseModel):
    lead_id: int
    rep_user_id: str
    follow_up_type: Optional[str] = "call"
    follow_up_hours: Optional[int] = 24
    notes: Optional[str] = None


class LocationSearchIn(BaseModel):
    """Input for Google Places-powered prospect discovery."""
    location: str                          # e.g. "Lekki, Lagos"
    business_type: str = "pharmacy"        # e.g. "pharmacy", "hospital"
    radius_m: Optional[int] = 5000         # search radius in metres
    limit: Optional[int] = 20
    industry: Optional[str] = "pharma"    # used to tag the inserted prospect
    region: Optional[str] = None          # fallback tag if not derived from location


def _score_lead(expected_value: float, urgency: str, fit_signals: dict | None) -> float:
    signals = fit_signals or {}
    score = 35.0
    score += min(max(expected_value, 0.0) / 100000.0, 25.0)
    urgency_norm = (urgency or "medium").strip().lower()
    if urgency_norm == "high":
        score += 20.0
    elif urgency_norm == "medium":
        score += 10.0
    elif urgency_norm == "low":
        score += 5.0
    if signals.get("decision_maker_identified"):
        score += 8.0
    if signals.get("budget_confirmed"):
        score += 8.0
    if signals.get("product_fit"):
        score += 6.0
    if signals.get("urgent_need"):
        score += 6.0
    return round(max(0.0, min(score, 100.0)), 2)


def _normalize_seed(seed: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "company_name": seed.get("company_name") or seed.get("name") or "Unknown Prospect",
        "industry": seed.get("industry"),
        "region": seed.get("region"),
        "contact_name": seed.get("contact_name"),
        "contact_email": seed.get("contact_email"),
        "contact_phone": seed.get("contact_phone"),
        "source": seed.get("source") or source,
        "enrichment": {
            "fit_signals": seed.get("fit_signals") or {},
            "company_size": seed.get("company_size"),
            "website": seed.get("website"),
        },
        "status": "enriched",
    }


@router.post("/leads")
async def create_lead(request: Request, payload: LeadIn, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        lead_payload = payload.dict(exclude_none=True)

        # Event-ledger-first: ensure immutable event exists before business write
        auth = verify_jwt(request)
        actor = auth.get("sub") or auth.get("user_id")
        oeis_result = await process_operational_event(
            {
                "department": "crm",
                "event_type": "lead_created",
                "payload": lead_payload,
                "created_by": actor,
                "status": "submitted",
            },
            actor_id=actor,
        )

        if oeis_result.event_id:
            lead_payload["event_ledger_id"] = oeis_result.event_id

        resp = db.table("leads").insert(lead_payload).execute()
        data = resp.data or []
        if not data:
            return {"status": "ok"}
        lead = data[0]
        await realtime_hub.broadcast("crm_updates", {
            "event": "lead_created",
            "lead_id": lead.get("id"),
            "stage": lead.get("stage"),
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        })
        invalidate_cache_tags("crm", "crm_dashboard", "crm_risk_scores", "executive")
        return lead
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/leads")
def list_leads(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("leads").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/opportunities")
def list_opps(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("opportunities").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/opportunities")
async def create_opp(request: Request, payload: dict, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        auth = verify_jwt(request)
        actor = auth.get("sub") or auth.get("user_id")
        oeis_result = await process_operational_event(
            {
                "department": "crm",
                "event_type": "opportunity_created",
                "payload": payload,
                "linked_customer_id": payload.get("customer_id"),
                "created_by": actor,
                "status": "submitted",
            },
            actor_id=actor,
        )
        resp = db.table("opportunities").insert(payload).execute()
        data = resp.data or []
        if not data:
            return {"status": "ok"}
        opp = data[0]
        if oeis_result.event_id:
            try:
                db.table("opportunities").update({"event_ledger_id": oeis_result.event_id}).eq("id", opp.get("id")).execute()
            except Exception:
                pass
        await realtime_hub.broadcast("crm_updates", {
            "event": "opportunity_created",
            "opportunity_id": opp.get("id"),
            "customer_id": opp.get("customer_id"),
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        })
        invalidate_cache_tags("crm", "crm_dashboard", "crm_risk_scores", "executive")
        return opp
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/activities")
def create_activity(payload: dict, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        resp = db.table("crm_activities").insert(payload).execute()
        return resp.data[0] if resp.data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tickets")
def create_ticket(payload: dict, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        resp = db.table("support_tickets").insert(payload).execute()
        return resp.data[0] if resp.data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/campaigns")
def list_campaigns(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("campaigns").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/forecasts")
def create_forecast(payload: dict, _u=Depends(require_any_role("sales", "management", "crm"))):
    try:
        resp = db.table("revenue_forecasts").insert(payload).execute()
        return resp.data[0] if resp.data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/lead-finder/prospects/source")
async def source_prospects(request: Request, payload: ProspectSourceIn, _u=Depends(require_any_role("sales", "management", "crm"))):
    auth = verify_jwt(request)
    actor = auth.get("sub") or auth.get("user_id")
    limit = max(1, min(int(payload.limit or 20), 100))
    source = (payload.source or "internal").strip().lower()

    prospects: list[dict[str, Any]] = []

    # Optional seed prospects from caller (import/sourcing adapters)
    for seed in payload.seed_companies or []:
        prospects.append(_normalize_seed(seed, source))

    # Internal sourcing from existing customers if not enough seeds
    if len(prospects) < limit:
        try:
            customers = db.table("customers").select("name,contact_details,metadata").limit(limit).execute()
            for customer in customers.data or []:
                contact = customer.get("contact_details") or {}
                meta = customer.get("metadata") or {}
                prospects.append(
                    {
                        "company_name": customer.get("name") or "Unknown Prospect",
                        "industry": payload.industry or meta.get("industry"),
                        "region": payload.region or meta.get("region"),
                        "contact_name": contact.get("name"),
                        "contact_email": contact.get("email"),
                        "contact_phone": contact.get("phone"),
                        "source": source,
                        "enrichment": {
                            "fit_signals": meta.get("fit_signals") or {},
                            "company_size": meta.get("company_size"),
                            "website": contact.get("website"),
                        },
                        "status": "enriched",
                    }
                )
                if len(prospects) >= limit:
                    break
        except Exception:
            pass

    prospects = prospects[:limit]

    inserted: list[dict[str, Any]] = []
    for prospect in prospects:
        prospect["created_by"] = actor
        try:
            ins = db.table("crm_prospects").insert(prospect).execute()
            rows = ins.data or []
            if rows:
                inserted.append(rows[0])
        except Exception:
            continue

    await realtime_hub.broadcast(
        "crm_updates",
        {
            "event": "prospects_sourced",
            "count": len(inserted),
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )
    invalidate_cache_tags("crm", "crm_dashboard", "executive")
    return {"status": "ok", "count": len(inserted), "prospects": inserted}


@router.post("/lead-finder/prospects/{prospect_id}/score-ingest")
async def score_and_ingest_prospect(
    request: Request,
    prospect_id: str,
    payload: ProspectScoreIn,
    _u=Depends(require_any_role("sales", "management", "crm")),
):
    auth = verify_jwt(request)
    actor = auth.get("sub") or auth.get("user_id")

    try:
        prospect_resp = db.table("crm_prospects").select("*").eq("id", prospect_id).limit(1).execute()
        rows = prospect_resp.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Prospect not found")
        prospect = rows[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load prospect: {exc}")

    score = _score_lead(float(payload.expected_value or 0), payload.urgency or "medium", payload.fit_signals)
    lead_payload = {
        "source": payload.source or prospect.get("source") or "lead_finder",
        "industry": prospect.get("industry"),
        "assigned_rep": payload.assigned_rep,
        "stage": payload.stage or "qualified",
        "score": score,
        "expected_value": payload.expected_value or 0,
        "metadata": {
            "prospect_id": prospect_id,
            "prospect_company_name": prospect.get("company_name"),
            "prospect_region": prospect.get("region"),
            "fit_signals": payload.fit_signals or (prospect.get("enrichment") or {}).get("fit_signals") or {},
        },
    }

    oeis_result = await process_operational_event(
        {
            "department": "crm",
            "event_type": "lead_finder_ingest",
            "payload": lead_payload,
            "created_by": actor,
            "status": "submitted",
        },
        actor_id=actor,
    )
    if oeis_result.event_id:
        lead_payload["event_ledger_id"] = oeis_result.event_id

    try:
        ins = db.table("leads").insert(lead_payload).execute()
        lead_rows = ins.data or []
        if not lead_rows:
            raise HTTPException(status_code=500, detail="Lead insert failed")
        lead = lead_rows[0]
        db.table("crm_prospects").update(
            {
                "score": score,
                "status": "converted",
                "converted_lead_id": lead.get("id"),
            }
        ).eq("id", prospect_id).execute()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lead ingest failed: {exc}")

    await realtime_hub.broadcast(
        "crm_updates",
        {
            "event": "lead_ingested",
            "lead_id": lead.get("id"),
            "prospect_id": prospect_id,
            "score": score,
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )
    invalidate_cache_tags("crm", "crm_dashboard", "crm_risk_scores", "executive")
    return {"status": "ok", "lead": lead, "score": score, "prospect_id": prospect_id}


@router.post("/lead-finder/assign")
async def assign_lead_and_follow_up(request: Request, payload: LeadAssignIn, _u=Depends(require_any_role("sales", "management", "crm"))):
    auth = verify_jwt(request)
    actor = auth.get("sub") or auth.get("user_id")
    due_at = dt.datetime.utcnow() + dt.timedelta(hours=max(1, min(int(payload.follow_up_hours or 24), 24 * 30)))
    due_at_iso = due_at.replace(microsecond=0).isoformat() + "Z"

    try:
        db.table("leads").update({"assigned_rep": payload.rep_user_id, "stage": "qualified"}).eq("id", payload.lead_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lead assignment failed: {exc}")

    followup_record = {
        "lead_id": payload.lead_id,
        "assigned_to": payload.rep_user_id,
        "follow_up_type": payload.follow_up_type or "call",
        "due_at": due_at_iso,
        "status": "open",
        "notes": payload.notes,
        "created_by": actor,
    }
    followup = None
    try:
        ins = db.table("crm_followups").insert(followup_record).execute()
        followup = (ins.data or [None])[0]
    except Exception:
        followup = None

    try:
        db.table("crm_activities").insert(
            {
                "type": "followup",
                "subject": "Lead follow-up assigned",
                "body": payload.notes or "Follow up with lead",
                "metadata": {
                    "lead_id": payload.lead_id,
                    "assigned_to": payload.rep_user_id,
                    "due_at": due_at_iso,
                    "follow_up_type": payload.follow_up_type or "call",
                },
            }
        ).execute()
    except Exception:
        pass

    try:
        db.table("placeware_tasks").insert(
            {
                "title": f"CRM follow-up: lead #{payload.lead_id}",
                "description": payload.notes or "Revenue officer lead follow-up",
                "status": "pending",
                "priority": "high",
                "due_date": due_at_iso,
                "assigned_to": payload.rep_user_id,
                "source": "workflow",
                "source_ref": f"lead:{payload.lead_id}",
                "tags": ["crm", "lead-finder", payload.follow_up_type or "call"],
                "metadata": {
                    "lead_id": payload.lead_id,
                    "follow_up_type": payload.follow_up_type or "call",
                },
            }
        ).execute()
    except Exception:
        pass

    try:
        # mirror lightweight staff task for staff dashboard
        from src.routers.staff_dashboard import _read_tasks, _write_tasks

        tasks = _read_tasks()
        tasks.append(
            {
                "task_id": f"lead-followup-{payload.lead_id}-{int(dt.datetime.utcnow().timestamp())}",
                "title": f"Lead #{payload.lead_id} follow-up",
                "description": payload.notes or "Contact and qualify assigned lead",
                "assigned_to": payload.rep_user_id,
                "status": "open",
                "due_date": due_at_iso,
            }
        )
        _write_tasks(tasks)
    except Exception:
        pass

    await realtime_hub.broadcast(
        "crm_updates",
        {
            "event": "lead_assigned",
            "lead_id": payload.lead_id,
            "assigned_to": payload.rep_user_id,
            "due_at": due_at_iso,
            "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )
    await realtime_hub.broadcast(
        "staff_updates",
        {
            "event": "staff_followup_assigned",
            "lead_id": payload.lead_id,
            "assigned_to": payload.rep_user_id,
            "due_at": due_at_iso,
        },
    )

    invalidate_cache_tags("crm", "crm_dashboard", "staff", "workforce_dashboard", "executive")
    return {"status": "ok", "assignment": {"lead_id": payload.lead_id, "assigned_to": payload.rep_user_id, "due_at": due_at_iso}, "followup": followup}


@router.get("/lead-finder/pipeline")
def lead_finder_pipeline(limit: int = 100, _u=Depends(verify_jwt)):
    bounded_limit = max(1, min(limit, 500))
    prospects = db.table("crm_prospects").select("*").order("created_at", desc=True).limit(bounded_limit).execute().data or []
    followups = db.table("crm_followups").select("*").order("created_at", desc=True).limit(bounded_limit).execute().data or []
    return {"prospects": prospects, "followups": followups}


# =============================================================================
# GOOGLE PLACES-POWERED DISCOVERY  (Migration 085)
# =============================================================================

@router.post("/lead-finder/search")
async def search_leads_by_location(
    request: Request,
    payload: LocationSearchIn,
    _u=Depends(require_any_role("sales", "management", "crm")),
):
    """
    Discover leads via Google Places API (or mock fallback).
    Deduplicates by place_id — already-indexed prospects are skipped.
    Results are cached in prospect_search_cache to avoid repeated API calls.
    """
    auth = verify_jwt(request)
    actor = auth.get("sub") or auth.get("user_id")

    location     = (payload.location or "").strip()
    business_type = (payload.business_type or "pharmacy").strip()
    radius_m     = max(500, min(int(payload.radius_m or 5000), 50_000))
    limit        = max(1, min(int(payload.limit or 20), 60))

    if not location:
        raise HTTPException(status_code=400, detail="location is required")

    q_key = _places_cache_key(location, business_type, radius_m)
    query_label = f"{business_type} near {location} ({radius_m}m)"

    # ── Call Places service (mock fallback built-in) ──────────────────────────
    try:
        places = search_places(location, business_type, radius_m=radius_m, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Places lookup failed: {exc}")

    # ── Insert, deduplicating by place_id (single batch check) ──────────────
    inserted: list[dict] = []
    skipped_ids: list[str] = []
    skipped = 0
    errors  = 0

    # Batch dedup: one IN query instead of one query per place
    incoming_place_ids = [p.get("place_id") for p in places if p.get("place_id")]
    existing_place_ids: set[str] = set()
    if incoming_place_ids:
        try:
            ex_check = db.table("crm_prospects").select("place_id").in_("place_id", incoming_place_ids).execute()
            existing_place_ids = {r["place_id"] for r in (ex_check.data or []) if r.get("place_id")}
        except Exception as e:
            logger.warning("crm batch dedup check failed: %s", e)

    for place in places:
        row = {
            **place,
            "industry":      payload.industry or "pharma",
            "region":        payload.region or location,
            "score":         place.get("places_score") or 0,
            "status":        "enriched",
            "source":        place.get("source", "google_places"),
            "search_query":  query_label,
            "created_by":    actor,
        }
        row["source"] = place.get("source", "google_places")

        place_id = row.get("place_id")
        if place_id and place_id in existing_place_ids:
            skipped += 1
            skipped_ids.append(place_id)
            continue

        try:
            ins = db.table("crm_prospects").insert(row).execute()
            rows = ins.data or []
            if rows:
                inserted.append(rows[0])
        except Exception as e:
            logger.error("crm prospect insert failed (place_id=%s): %s", place_id, e)
            errors += 1
            continue

    # ── Fetch existing records for skipped place_ids so UI can display them ──
    existing_records: list[dict] = []
    if skipped_ids:
        try:
            ex_res = db.table("crm_prospects").select("*").in_("place_id", skipped_ids).execute()
            existing_records = ex_res.data or []
        except Exception as e:
            logger.error("crm batch-fetch of skipped prospects failed: %s", e)

    all_prospects = inserted + existing_records

    # ── Update search cache ───────────────────────────────────────────────────
    try:
        db.table("prospect_search_cache").upsert({
            "query_key":       q_key,
            "search_location": location,
            "business_type":   business_type,
            "radius_m":        radius_m,
            "result_count":    len(inserted),
            "cached_at":       dt.datetime.utcnow().isoformat() + "Z",
        }).execute()
    except Exception:
        pass

    await realtime_hub.broadcast("crm_updates", {
        "event": "prospects_sourced",
        "count": len(inserted),
        "source": "google_places",
        "at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    })
    invalidate_cache_tags("crm", "crm_dashboard", "executive")

    return {
        "status":  "ok",
        "count":   len(inserted),
        "skipped": skipped,
        "errors":  errors,
        "query":   query_label,
        "prospects": all_prospects,
    }


@router.get("/lead-finder/export")
def export_prospects(limit: int = 1000, _u=Depends(verify_jwt)):
    """
    Download all crm_prospects as a CSV file.
    Returns a streaming CSV response (suitable for browser download).
    """
    try:
        resp = db.table("crm_prospects").select("*").order("created_at", desc=True).limit(max(1, min(limit, 5000))).execute()
        rows = resp.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    FIELDS = [
        "id", "company_name", "industry", "region", "formatted_address",
        "contact_name", "contact_email", "contact_phone", "phone_number",
        "website", "rating", "user_ratings_total", "places_score", "score",
        "status", "source", "search_query", "assigned_rep",
        "converted_lead_id", "created_at",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (row.get(k) or "") for k in FIELDS})

    buffer.seek(0)
    filename = f"prospects_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
