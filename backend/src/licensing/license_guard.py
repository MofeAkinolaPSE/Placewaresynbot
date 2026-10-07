"""Backend enforcement: one middleware in front of every route, plus a public status route.

The lock is applied here (not in the UI), so calling the API directly gets the same 403.
Licence file contents are never served; /license/status returns only the computed state.
"""
from __future__ import annotations

import json

from fastapi import APIRouter

from .license_manager import license_manager

# Reachable while locked: health checks, sign-in/session plumbing, and the status itself.
_ALWAYS_OPEN_EXACT = {"/", "/health", "/metrics", "/token", "/refresh", "/logout", "/license/status"}
_ALWAYS_OPEN_PREFIXES = ("/auth/", "/.well-known/")
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}

router = APIRouter(tags=["licensing"])


@router.get("/license/status", include_in_schema=False)
def license_status() -> dict:
    return license_manager.status().public_dict()


def _is_open(path: str) -> bool:
    return path in _ALWAYS_OPEN_EXACT or path.startswith(_ALWAYS_OPEN_PREFIXES)


class LicenseGuardMiddleware:
    """Pure ASGI middleware (no response buffering, covers websockets too)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        status = license_manager.status()
        if not status.locked or _is_open(scope.get("path", "")):
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET")
        if method == "OPTIONS" or (status.lock_mode == "read_only" and method in _READ_METHODS):
            return await self.app(scope, receive, send)

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        body = json.dumps({"detail": {
            "code": "LICENSE_" + status.state.upper(),
            "message": status.message,
            "license": status.public_dict(),
        }}).encode("utf-8")
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-license-state", status.state.encode()),
        ]})
        await send({"type": "http.response.body", "body": body})
