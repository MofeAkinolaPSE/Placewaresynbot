"""
auth.py — API-key middleware for the Sage Bridge.

Every inbound request must carry the header:
    X-Bridge-API-Key: <BRIDGE_API_KEY>

Matching is done with hmac.compare_digest to prevent timing attacks.
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader

from config import get_settings

logger = logging.getLogger("bridge.auth")

_KEY_HEADER = APIKeyHeader(name="X-Bridge-API-Key", auto_error=False)


def verify_api_key(request: Request) -> None:
    """
    Dependency: raises HTTP 401 when the API key is missing or invalid.
    Usage::

        @router.get("/endpoint")
        def endpoint(request: Request, _: None = Depends(verify_api_key)):
            ...
    """
    settings = get_settings()
    provided: Optional[str] = request.headers.get("X-Bridge-API-Key")

    if not provided:
        logger.warning("Request from %s missing API key", request.client.host)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Bridge-API-Key header",
        )

    expected = settings.BRIDGE_API_KEY
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        logger.warning("Invalid API key from %s", request.client.host)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
