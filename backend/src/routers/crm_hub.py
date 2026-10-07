"""CRM API on real data (services/crm_hub.py): overview from ACE Books, the deal pipeline,
prospecting near the rep, reminders, weekly report, targets and leaderboard.

Sales actions accept the roles that actually exist (admin, sales, management); the old
endpoints required a "crm" role that no account can be given, so only admins could search
for leads or create customers."""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.middleware import verify_jwt
from src.services import crm_hub as ch

log = logging.getLogger(__name__)
router = APIRouter(prefix="/crm", tags=["crm"])

READ = {"admin", "sales", "management", "finance", "crm"}
ACT = ch.SALES_ROLES


def _need(allowed: set):
    def dep(request: Request) -> Dict[str, Any]:
        u = verify_jwt(request)
        if not {str(r).lower() for r in (u.get("roles") or [])} & allowed:
            raise HTTPException(403, "Sales role required")
        return u
    return dep


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except HTTPException:
        raise
    except ch.CrmError as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:   # places_service.PlacesUnavailable: every map server busy
        raise HTTPException(503, str(e))
    except Exception:
        log.exception("crm endpoint failed")
        raise HTTPException(500, "Internal server error")


@router.get("/overview")
def overview(_u=Depends(_need(READ))):
    return _call(ch.overview)


# Pipeline -----------------------------------------------------------------------

@router.get("/pipeline")
def pipeline(rep: Optional[str] = None, _u=Depends(_need(READ))):
    return _call(ch.pipeline, rep)


@router.post("/deals", status_code=201)
def create_deal(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.create_lead, user, payload)


@router.get("/deals/{lead_id}")
def deal(lead_id: int, _u=Depends(_need(READ))):
    return _call(ch.lead_detail, lead_id)


@router.patch("/deals/{lead_id}")
def update_deal(lead_id: int, payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.update_lead, user, lead_id, payload)


@router.post("/deals/{lead_id}/stage")
def move(lead_id: int, payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.move_stage, user, lead_id, payload.get("stage"), payload)


@router.post("/activity", status_code=201)
def activity(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.log_activity, user, payload)


# Reminders ----------------------------------------------------------------------

@router.get("/reminders")
def reminders(scope: str = Query("mine", pattern="^(mine|all)$"), user=Depends(_need(READ))):
    return _call(ch.reminders, user, scope)


@router.post("/reminders", status_code=201)
def create_reminder(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.create_reminder, user, payload)


@router.post("/reminders/{reminder_id}/{action}")
def reminder_action(reminder_id: str, action: str, days: int = 1, user=Depends(_need(ACT))):
    return _call(ch.update_reminder, user, reminder_id, action, days)


# Prospecting & inbound ------------------------------------------------------------

@router.post("/prospects/search")
def search(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.search, user, payload)


@router.get("/prospects")
def prospects(status: Optional[str] = None, user=Depends(_need(READ))):
    return {"prospects": _call(ch.prospects, user, status)}


@router.post("/prospects/save")
def save_prospect(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.save_prospect, user, payload.get("place") or {}, payload.get("status") or "saved", payload.get("note"))


@router.post("/prospects/to-pipeline", status_code=201)
def to_pipeline(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT))):
    return _call(ch.prospect_to_lead, user, payload.get("place") or {}, payload)


@router.get("/inbound")
def inbound(_u=Depends(_need(READ))):
    return {"inbound": _call(ch.inbound)}


# Reports ------------------------------------------------------------------------

def _week(week_start: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(week_start) if week_start else None


@router.get("/weekly-report")
def weekly(week_start: Optional[str] = None, _u=Depends(_need(READ))):
    return _call(ch.weekly_report, _week(week_start))


@router.get("/weekly-report.csv")
def weekly_csv(week_start: Optional[str] = None, _u=Depends(_need(READ))):
    r = _call(ch.weekly_report, _week(week_start))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"Weekly sales report {r['week_start']} to {r['week_end']}"])
    w.writerow([])
    for k, v in r["summary"].items():
        w.writerow([k.replace("_", " "), v])
    w.writerow([]); w.writerow(["By rep", "new leads", "activities", "won", "won value", "lost"])
    for p in r["per_rep"]:
        w.writerow([p["rep"], p["new_leads"], p["activities"], p["won"], p["won_value"], p["lost"]])
    w.writerow([]); w.writerow(["New leads", "source", "rep", "expected value", "stage", "created"])
    for l in r["new_leads"]:
        w.writerow([l["company_name"], l["source"], l.get("rep_name") or "", l["expected_value"], l["stage"], l["created_at"]])
    w.writerow([]); w.writerow(["Won", "value", "rep", "date"])
    for l in r["won"]:
        w.writerow([l["company_name"], l["expected_value"], l.get("rep_name") or "", l["won_at"]])
    w.writerow([]); w.writerow(["Lost", "value", "rep", "reason"])
    for l in r["lost"]:
        w.writerow([l["company_name"], l["expected_value"], l.get("rep_name") or "", l["lost_reason"]])
    w.writerow([]); w.writerow(["Activity", "type", "by", "summary", "outcome", "when"])
    for a in r["activity"]:
        w.writerow([a.get("company_name") or "", a["interaction_type"], a.get("by") or "", a["summary"], a.get("outcome") or "", a["occurred_at"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=weekly_sales_{r['week_start']}.csv"})


@router.get("/targets")
def targets(period: str, _u=Depends(_need(READ))):
    return _call(ch.targets, period)


@router.post("/targets", status_code=201)
def set_target(payload: Dict[str, Any] = Body(...), user=Depends(_need({"admin", "management"}))):
    return _call(ch.set_target, user, payload)


@router.get("/leaderboard")
def leaderboard(days: int = Query(30, ge=7, le=365), _u=Depends(_need(READ))):
    return {"days": days, "reps": _call(ch.leaderboard, days)}


@router.get("/reps")
def reps(_u=Depends(_need(READ))):
    return {"reps": _call(ch.reps)}


@router.post("/new-customer", status_code=201)
def new_customer(payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT | {"finance"}))):
    return _call(ch.create_customer, user, payload)



@router.get("/directory")
def directory(_u=Depends(_need(READ))):
    return _call(ch.customer_directory)


@router.get("/customer/{customer_id}")
def customer(customer_id: int, _u=Depends(_need(READ))):
    return _call(ch.customer_profile, customer_id)


@router.patch("/customer/{customer_id}")
def edit_customer(customer_id: int, payload: Dict[str, Any] = Body(...), user=Depends(_need(ACT | {"finance"}))):
    return _call(ch.update_customer, user, customer_id, payload)
