from fastapi import APIRouter, Request, HTTPException, Depends
from src.middleware import verify_jwt, require_role
from pydantic import BaseModel
from typing import Optional, Any
from ..db import db
import hashlib, json
import datetime as dt
from src.services.realtime import realtime_hub
from src.cache import invalidate_cache_tags
from src.services.oeis import process_operational_event

router = APIRouter(prefix="/crm", tags=["crm"])


class CustomerIn(BaseModel):
    name: str
    customer_code: Optional[str]
    contact_details: Optional[dict] = {}
    account_manager: Optional[str]


@router.post("/customers")
async def create_customer(request: Request, payload: CustomerIn, _u=Depends(require_role("crm"))):
    try:
        row = payload.dict()
        row["created_at"] = None
        resp = db.table("customers").insert(row).execute()
        data = resp.data or []
        return data[0] if data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers/{customer_id}")
async def get_customer(customer_id: int, _u=Depends(verify_jwt)):
    try:
        resp = db.table("customers").select("*").eq("id", customer_id).limit(1).execute()
        data = resp.data or []
        if not data:
            raise HTTPException(status_code=404, detail="Customer not found")
        return data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers")
async def list_customers(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("customers").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LeadIn(BaseModel):
    source: Optional[str]
    industry: Optional[str]
    assigned_rep: Optional[str]
    stage: Optional[str]
    score: Optional[float]
    expected_value: Optional[float]
    linked_campaign_id: Optional[int]
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
async def create_lead(request: Request, payload: LeadIn, _u=Depends(require_role("crm"))):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leads")
async def list_leads(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("leads").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/opportunities")
async def list_opps(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("opportunities").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/opportunities")
async def create_opp(request: Request, payload: dict, _u=Depends(require_role("crm"))):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activities")
async def create_activity(payload: dict, _u=Depends(require_role("crm"))):
    try:
        resp = db.table("crm_activities").insert(payload).execute()
        return resp.data[0] if resp.data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tickets")
async def create_ticket(payload: dict, _u=Depends(require_role("crm"))):
    try:
        resp = db.table("support_tickets").insert(payload).execute()
        return resp.data[0] if resp.data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns")
async def list_campaigns(limit: int = 50, offset: int = 0, _u=Depends(verify_jwt)):
    try:
        resp = db.table("campaigns").select("*").range(offset, offset + limit - 1).execute()
        return resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/forecasts")
async def create_forecast(payload: dict, _u=Depends(require_role("crm"))):
    try:
        resp = db.table("revenue_forecasts").insert(payload).execute()
        return resp.data[0] if resp.data else {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lead-finder/prospects/source")
async def source_prospects(request: Request, payload: ProspectSourceIn, _u=Depends(require_role("crm"))):
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
    _u=Depends(require_role("crm")),
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
async def assign_lead_and_follow_up(request: Request, payload: LeadAssignIn, _u=Depends(require_role("crm"))):
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
async def lead_finder_pipeline(limit: int = 100, _u=Depends(verify_jwt)):
    bounded_limit = max(1, min(limit, 500))
    prospects = db.table("crm_prospects").select("*").order("created_at", desc=True).limit(bounded_limit).execute().data or []
    followups = db.table("crm_followups").select("*").order("created_at", desc=True).limit(bounded_limit).execute().data or []
    return {"prospects": prospects, "followups": followups}
