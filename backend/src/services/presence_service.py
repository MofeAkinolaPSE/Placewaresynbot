"""Who's-currently-online tracking.

Heartbeat-based, not WebSocket-connection-based: realtime_hub (services/
realtime.py) is a pure per-channel broadcast with no connection->user
registry, and its coverage would depend on which realtime channel a given
page happens to open. A heartbeat mounted once at the app root instead gives
accurate, app-wide "has the app open right now" coverage regardless of
which page is active.

Storage is the same shared cache every other module already uses
(cache_ui.get_shared_cache() -- Redis-backed with an automatic in-memory
fallback) rather than new infra. One key per user (not per browser tab/
session): a person with the app open in two browsers is one online person,
not two -- this also avoids needing any new client-side session-id
plumbing. TTL-based expiry means no manual reaper is needed for someone who
closes their laptop without a clean logout.
"""
import datetime as dt

from src.db import db
from src.constants import TABLE_USERS

PRESENCE_TTL_SECONDS = 90  # heartbeat fires every 30s -- tolerates 2 missed beats


def _key(user_id: str) -> str:
    return f"presence:{user_id}"


def _get_cache():
    # Deferred import: cache_ui is a router module; importing at module load
    # time here would risk a load-order coupling with app.py's router
    # registration, matching this codebase's existing deferred-import
    # convention for the same reason (see intelligence.py's docstring on
    # deferred imports from routers).
    from src.routers.cache_ui import get_shared_cache
    return get_shared_cache()


def record_heartbeat(user_id: str, roles: list[str]) -> None:
    if not user_id:
        return
    cache = _get_cache()
    cache.set(_key(user_id), {
        "roles": roles or [],
        "last_seen": dt.datetime.utcnow().isoformat() + "Z",
    }, ttl=PRESENCE_TTL_SECONDS)


def get_online_users() -> list[dict]:
    cache = _get_cache()
    try:
        resp = db.table(TABLE_USERS).select("id,email").execute()
        users = resp.data or []
    except Exception:
        return []

    online: list[dict] = []
    for u in users:
        payload = cache.get(_key(u["id"]))
        if payload:
            online.append({
                "user_id": u["id"],
                "email": u.get("email"),
                "roles": payload.get("roles") or [],
                "last_seen": payload.get("last_seen"),
            })
    return online


def get_online_count() -> int:
    return len(get_online_users())
