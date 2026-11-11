"""Branches (Lagos / Abuja): which branch a web request works in, and who may work where.

A branch is an ACE Books legal entity (migration 150). Every request from a signed-in person runs for exactly one
branch:

  * the branch the screen asks for (header ``X-Legal-Entity``: the entity id or code), if that person may use it;
  * otherwise the person's home branch.

Asking for a branch the person may not use is refused (403 BRANCH_NOT_ALLOWED) - never silently swapped, so nobody
records a sale in one branch while looking at the other.

The chosen branch is held in a context variable for the life of the request. The connection pool
(``src/local_db.py``) puts every database connection the request uses into that branch: the connection runs as
role ``ace_app`` with ``app.entity_id`` set, and Postgres row-level security hides every other branch's rows.
Work outside a web request (start-up, background loops, scripts) has no branch and runs unfiltered as the owner.

Who may use which branch: admin and management (CEO / CFO) - every branch; everyone else - their home branch plus
any extra branches set on User Access.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from src.local_db import branch_var

logger = logging.getLogger(__name__)

ALL_BRANCH_ROLES = {"admin", "management"}
HEADER = "x-legal-entity"

_TTL = 10.0
_lock = threading.Lock()
_branches: tuple = (0.0, None)
_users: Dict[str, tuple] = {}


class BranchNotAllowed(Exception):
    pass


# --- the request's branch -------------------------------------------------------------------------------------
def current() -> Optional[str]:
    """The branch (legal entity id) of the running request, or None outside a request."""
    return branch_var.get()


@contextmanager
def scoped(entity_id: Optional[str]) -> Iterator[None]:
    """Run a block in a given branch (e.g. a background job working through each branch in turn)."""
    token = branch_var.set(str(entity_id) if entity_id else None)
    try:
        yield
    finally:
        branch_var.reset(token)


@contextmanager
def unscoped() -> Iterator[None]:
    """Run a block across all branches (backups, admin tools). Use sparingly."""
    with scoped(None):
        yield


def cache_key(key):
    """A cache key that keeps each branch's cached figures apart (a Lagos report is never served in Abuja)."""
    e = current()
    if not e:
        return key
    return (e, key) if not isinstance(key, str) else f"{e}|{key}"


def carry(fn):
    """Wrap a function handed to a thread pool so it runs in this request's branch (a worker thread does not
    inherit the request's context: without this its queries would run unfiltered, across both branches)."""
    e = current()

    def run(*a, **k):
        with scoped(e):
            return fn(*a, **k)
    return run


# --- lookups (unscoped: these tables have no branch column) ---------------------------------------------------
def _query(sql: str, params: Any = None) -> List[Dict[str, Any]]:
    from src.db import db
    from psycopg2.extras import RealDictCursor
    with unscoped():
        conn = db.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
            conn.rollback()
            return rows
        finally:
            db.pool.putconn(conn)


def all_branches(fresh: bool = False) -> List[Dict[str, Any]]:
    """Every active branch, primary (Lagos) first."""
    global _branches
    now = time.monotonic()
    if not fresh and _branches[1] is not None and now - _branches[0] < _TTL:
        return _branches[1]
    rows = _query("""SELECT id::text AS id, code, name, COALESCE(branch_name, name) AS branch_name, is_primary
                       FROM fin_legal_entities WHERE status='ACTIVE'
                      ORDER BY is_primary DESC, sort_order, created_at""")
    _branches = (now, rows)
    return rows


def primary_branch() -> Optional[str]:
    rows = all_branches()
    return rows[0]["id"] if rows else None


def branch_label(entity_id: Optional[str]) -> str:
    for b in all_branches():
        if b["id"] == str(entity_id):
            return b["branch_name"]
    return ""


def _user_row(user_id: str) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    hit = _users.get(user_id)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    rows = _query("""SELECT home_entity_id::text AS home, COALESCE(extra_entity_ids, '{}')::text[] AS extra, roles
                       FROM placeware_users WHERE id::text=%s""", (user_id,))
    row = rows[0] if rows else None
    with _lock:
        _users[user_id] = (now, row)
    return row


def forget_user(user_id: str) -> None:
    _users.pop(str(user_id), None)


def access_for(user_id: Optional[str], roles: List[str]) -> Dict[str, Any]:
    """{home, allowed: [branch ids], all: bool} for a login."""
    active = [b["id"] for b in all_branches()]
    row = _user_row(str(user_id)) if user_id else None
    db_roles = [str(r).lower() for r in ((row or {}).get("roles") or roles or [])]
    home = (row or {}).get("home")
    if home not in active:
        home = active[0] if active else None
    if set(db_roles) & ALL_BRANCH_ROLES:
        return {"home": home, "allowed": active, "all": True}
    allowed = [b for b in active if b == home or b in ((row or {}).get("extra") or [])]
    return {"home": home, "allowed": allowed, "all": False}


def _match(requested: str) -> Optional[str]:
    r = requested.strip()
    for b in all_branches():
        if r in (b["id"], b["code"]) or r.lower() == b["branch_name"].lower():
            return b["id"]
    return None


def resolve(user_id: Optional[str], roles: List[str], requested: Optional[str]) -> Optional[str]:
    """The branch this login works in for this request. Raises BranchNotAllowed for a branch they may not use."""
    acc = access_for(user_id, roles)
    if requested and requested.strip():
        want = _match(requested)
        if not want or want not in acc["allowed"]:
            raise BranchNotAllowed(requested)
        return want
    return acc["home"]


def describe(user_id: Optional[str], roles: List[str]) -> Dict[str, Any]:
    """What the branch switcher shows: the branch this request runs in, the home branch, the choices."""
    acc = access_for(user_id, roles)
    allowed = [b for b in all_branches() if b["id"] in acc["allowed"]]
    cur = current() or acc["home"]
    return {"current": next((b for b in allowed if b["id"] == cur), None),
            "home": acc["home"], "branches": allowed, "can_switch": len(allowed) > 1}


def users_sql(alias: str = "u") -> str:
    """SQL condition: login `alias` may work in the branch given as the next TWO parameters (pass the id twice).
    Admin and management may work in every branch; a login with no home branch belongs to the primary one."""
    return (f"(({alias}.roles && ARRAY['admin','management']::text[]) "
            f"OR COALESCE({alias}.home_entity_id, (SELECT id FROM fin_legal_entities WHERE is_primary LIMIT 1)) = %s::uuid "
            f"OR %s::uuid = ANY({alias}.extra_entity_ids))")


def link(path: str, entity_id: Optional[str] = None) -> str:
    """An in-app link that opens in the right branch (the app switches to ?branch=<code> when it can)."""
    e = entity_id or current()
    if not e or len(all_branches()) < 2:
        return path
    code = next((b["code"] for b in all_branches() if b["id"] == str(e)), None)
    if not code:
        return path
    return f"{path}{'&' if '?' in path else '?'}branch={code}"


def tag(title: str, entity_id: Optional[str] = None) -> str:
    """Prefix a notification title with the branch ("Abuja: ...") once there is more than one branch."""
    e = entity_id or current()
    if not e or len(all_branches()) < 2:
        return title
    label = branch_label(e)
    return f"{label}: {title}" if label else title


# --- ASGI middleware ------------------------------------------------------------------------------------------
class BranchMiddleware:
    """Sets the request's branch before any handler (or dependency) runs. Pure ASGI, so the context variable is
    visible to the handler, its thread-pool work and its background tasks."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        token = None
        requested = None
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                val = v.decode("latin-1")
                if val[:7].lower() == "bearer ":
                    token = val[7:].strip()
            elif k == HEADER.encode():
                requested = v.decode("latin-1")
        if not token:
            return await self.app(scope, receive, send)

        import anyio
        try:
            entity = await anyio.to_thread.run_sync(_entity_for_token, token, requested)
        except BranchNotAllowed:
            return await _refuse(send, 403, "You do not have access to that branch.", "BRANCH_NOT_ALLOWED")
        except Exception as exc:  # cannot tell which branch: refuse rather than run unfiltered
            logger.warning("branch lookup failed: %s", exc)
            return await _refuse(send, 503, "ACE is busy - please try again in a moment.", "BRANCH_UNAVAILABLE")
        ctx_token = branch_var.set(entity)
        try:
            await self.app(scope, receive, send)
        finally:
            branch_var.reset(ctx_token)


async def _refuse(send, status: int, detail: str, code: str) -> None:
    body = json.dumps({"detail": detail, "code": code}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _entity_for_token(token: str, requested: Optional[str]) -> Optional[str]:
    from src.middleware import decode_jwt_token
    try:
        payload = decode_jwt_token(token)
    except Exception:
        return None  # not signed in (or expired): the handler answers 401 itself
    return resolve(str(payload.get("sub") or ""), list(payload.get("roles") or []), requested)
