"""Staff Workspace API (services/staff_workspace.py) - every signed-in team member.

Everything is about the caller: the user id comes from the token, never from the
request, so nobody can read or clock someone else's work through this API.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import anyio
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from src.middleware import verify_jwt
from src.services import staff_workspace as sw

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace", tags=["workspace"])


def _user(request: Request) -> Dict[str, Any]:
    return verify_jwt(request)


def _ping(event: str, users: Optional[List[Optional[str]]] = None) -> None:
    """Tell open workspaces (and HR) to refresh. Content never travels on the socket."""
    try:
        from src.services.realtime import realtime_hub
        payload = {"event": event, "users": [u for u in (users or []) if u]}
        anyio.from_thread.run(realtime_hub.broadcast, "workspace_updates", payload)
        if event.startswith("clock"):
            anyio.from_thread.run(realtime_hub.broadcast, "staff_updates", {"event": event})
    except Exception:
        pass


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except HTTPException:
        raise
    except sw.WorkspaceError as e:
        msg = str(e)
        if msg.startswith("NEEDS_END_TIME: "):
            raise HTTPException(409, {"code": "needs_end_time", "message": msg.split(": ", 1)[1]})
        raise HTTPException(409, msg)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        log.exception("workspace endpoint failed")
        raise HTTPException(500, "Internal server error")


# My Day ------------------------------------------------------------------------

@router.get("/day")
def my_day(u=Depends(_user)):
    return _call(sw.my_day, u)


@router.get("/operational")
def operational(u=Depends(_user)):
    return _call(sw.signals, u)


@router.post("/operational/take")
def take(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.take_signal, u, str(data.get("rule") or ""), str(data.get("id") or ""), data.get("assign_to"))
    _ping("task", [r.get("assigned_to")])
    return r


# Time clock --------------------------------------------------------------------

@router.get("/time")
def my_time(u=Depends(_user)):
    return _call(sw.my_time, u)


@router.post("/time/start")
def clock_in(data: Dict[str, Any] = Body(default={}), u=Depends(_user)):
    r = _call(sw.clock_start, u, data or {})
    _ping("clock", [u.get("sub")])
    return r


@router.post("/time/break")
def take_break(u=Depends(_user)):
    r = _call(sw.clock_break, u, False)
    _ping("clock", [u.get("sub")])
    return r


@router.post("/time/resume")
def resume(u=Depends(_user)):
    r = _call(sw.clock_break, u, True)
    _ping("clock", [u.get("sub")])
    return r


@router.post("/time/stop")
def clock_out(data: Dict[str, Any] = Body(default={}), u=Depends(_user)):
    r = _call(sw.clock_stop, u, data or {})
    _ping("clock", [u.get("sub")])
    return r


# Tasks -------------------------------------------------------------------------

@router.get("/tasks")
def tasks(u=Depends(_user)):
    return _call(sw.list_tasks, u)


@router.post("/tasks")
def new_task(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.create_task, u, data)
    _ping("task", [r.get("assigned_to"), r.get("created_by")])
    return r


@router.get("/tasks/{task_id}")
def task(task_id: str, u=Depends(_user)):
    return _call(sw.get_task, u, task_id)


@router.patch("/tasks/{task_id}")
def edit_task(task_id: str, data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.update_task, u, task_id, data)
    _ping("task", [r.get("assigned_to"), r.get("created_by")])
    return r


@router.post("/tasks/{task_id}/status")
def task_status(task_id: str, data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.set_status, u, task_id, str(data.get("status") or ""), data)
    _ping("task", [r.get("assigned_to"), r.get("created_by")])
    return r


@router.post("/tasks/{task_id}/comment")
def task_comment(task_id: str, data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.comment, u, task_id, str(data.get("body") or ""))
    _ping("task", [r.get("assigned_to"), r.get("created_by")])
    return r


@router.post("/parse")
def parse_sentence(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    """Typed sentence -> task draft (shown to the person before anything is saved)."""
    from src.services.task_language import parse
    return _call(parse, str(data.get("text") or ""), u)


@router.post("/quick")
def quick_add(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    """Typed sentence -> task, in one step."""
    from src.services.task_language import parse
    draft = _call(parse, str(data.get("text") or ""), u)
    r = _call(sw.create_task, u, {k: draft[k] for k in ("title", "kind", "priority", "due_at", "assigned_to", "department",
                                                          "recurrence", "recurrence_until")})
    _ping("task", [r.get("assigned_to"), r.get("created_by")])
    return {**r, "understood": draft["understood"]}


# Escalation rules --------------------------------------------------------------

@router.get("/escalation-policy")
def escalation_policy(u=Depends(_user)):
    from src.services.workspace_automation import policies
    return _call(policies)


@router.put("/escalation-policy")
def save_escalation_policy(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    from src.services.workspace_automation import set_policy
    return _call(set_policy, u, str(data.get("subject") or ""), str(data.get("priority") or ""), data.get("steps") or [])


@router.post("/escalations/run")
def run_escalations_now(u=Depends(_user)):
    """Run the escalation sweep now (it also runs every 5 minutes in the background)."""
    if not {str(r).lower() for r in u.get("roles") or []} & {"admin", "management"}:
        raise HTTPException(403, "Admin or management only")
    from src.services.workspace_automation import run_escalations
    r = _call(run_escalations)
    _ping("escalation")
    return r


# Requests ----------------------------------------------------------------------

@router.get("/requests")
def requests_(u=Depends(_user)):
    return _call(sw.list_requests, u)


@router.post("/requests")
def new_request(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.create_request, u, data)
    _ping("request", [r.get("to_user")] if r.get("to_user") else None)
    return r


@router.get("/requests/{request_id}")
def request_(request_id: str, u=Depends(_user)):
    return _call(sw.get_request, u, request_id)


@router.post("/requests/{request_id}/{action}")
def request_action(request_id: str, action: str, data: Dict[str, Any] = Body(default={}), u=Depends(_user)):
    r = _call(sw.act_request, u, request_id, action, data or {})
    _ping("request", [r.get("from_user"), r.get("to_user")])
    return r


# Inbox -------------------------------------------------------------------------

@router.get("/inbox")
def inbox(filter: str = Query("all"), u=Depends(_user)):
    return _call(sw.inbox, u, filter)


@router.post("/inbox/read")
def inbox_read(data: Dict[str, Any] = Body(default={}), u=Depends(_user)):
    return _call(sw.mark_read, u, (data or {}).get("ids"))


# Messages ----------------------------------------------------------------------

@router.get("/conversations")
def conversations(u=Depends(_user)):
    return _call(sw.conversations, u)


@router.get("/messages/{other}")
def messages(other: str, u=Depends(_user)):
    return _call(sw.messages, u, other)


@router.post("/messages/{other}")
def send(other: str, data: Dict[str, Any] = Body(...), u=Depends(_user)):
    r = _call(sw.send_message, u, other, str(data.get("body") or ""))
    _ping("message", None if other == "team" else [other, u.get("sub")])
    return r


# Team, progress, journal, preferences ---------------------------------------------

@router.get("/team")
def team(u=Depends(_user)):
    return _call(sw.team, u)


@router.get("/progress")
def progress(range: str = Query("week"), u=Depends(_user)):
    return _call(sw.progress, u, range)


@router.get("/journal")
def journal(range: str = Query("today"), u=Depends(_user)):
    return _call(sw.work_journal, u, range)


@router.get("/prefs")
def prefs(u=Depends(_user)):
    return _call(sw.get_prefs, u)


@router.put("/prefs")
def save_prefs(data: Dict[str, Any] = Body(...), u=Depends(_user)):
    return _call(sw.set_prefs, u, data)
