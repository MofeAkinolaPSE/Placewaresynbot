"""HR API (services/hr_hub.py): live workforce overview, the staff directory built from
User Access, and timesheet review. HR and admin act; management can read."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from src.middleware import verify_jwt
from src.services import hr_hub as hr
from src.services.staff_workspace import WorkspaceError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/hr", tags=["hr"])

READ = {"admin", "hr", "management"}
WRITE = {"admin", "hr"}


def _need(allowed: set):
    def dep(request: Request) -> Dict[str, Any]:
        u = verify_jwt(request)
        if not {str(r).lower() for r in (u.get("roles") or [])} & allowed:
            raise HTTPException(403, "HR role required")
        return u
    return dep


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except HTTPException:
        raise
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        log.exception("hr endpoint failed")
        raise HTTPException(500, "Internal server error")


@router.get("/overview")
def overview(week: Optional[str] = Query(None), _u=Depends(_need(READ))):
    return _call(hr.overview, week)


@router.get("/people")
def directory(_u=Depends(_need(READ))):
    return _call(hr.directory)


@router.post("/people")
def add_person(data: Dict[str, Any] = Body(...), u=Depends(_need(WRITE))):
    return _call(hr.create_person, u, data)


@router.get("/people/{key:path}")
def person(key: str, _u=Depends(_need(READ))):
    return _call(hr.person, key)


@router.patch("/people/{key:path}")
def update_person(key: str, data: Dict[str, Any] = Body(...), u=Depends(_need(WRITE))):
    return _call(hr.update_person, u, key, data)


@router.get("/timesheets")
def timesheets(week: Optional[str] = Query(None), person: Optional[str] = Query(None), status: Optional[str] = Query(None),
               pending: bool = Query(False), _u=Depends(_need(READ))):
    return _call(hr.timesheets, week, person, status, pending)


@router.get("/timesheets.csv")
def timesheets_csv(week: Optional[str] = Query(None), _u=Depends(_need(READ))):
    body = _call(hr.timesheets_csv, week)
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="timesheets-{week or "this-week"}.csv"'})


@router.post("/timesheets")
def add_entry(data: Dict[str, Any] = Body(...), u=Depends(_need(WRITE))):
    return _call(hr.add_entry, u, data)


@router.post("/timesheets/approve-week")
def approve_week(data: Dict[str, Any] = Body(default={}), u=Depends(_need(WRITE))):
    data = data or {}
    return _call(hr.approve_week, u, data.get("person"), data.get("week"), bool(data.get("all_weeks")))


@router.post("/timesheets/{entry_id}/{action}")
def review(entry_id: int, action: str, data: Dict[str, Any] = Body(default={}), u=Depends(_need(WRITE))):
    return _call(hr.review, u, entry_id, action, data or {})
