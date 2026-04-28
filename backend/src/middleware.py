from __future__ import annotations

import time
import logging
from functools import partial
from typing import Dict
from fastapi import Request, HTTPException
import jwt
from jwt import PyJWKClient
from .constants import JWT_SECRET, RATE_LIMIT, JWT_AUDIENCE, AUTH0_DOMAIN, AUTH0_AUDIENCE, AUTH0_ISSUER
from starlette.middleware.base import BaseHTTPMiddleware



_rate_store: Dict[str, list] = {}
_jwks_client: PyJWKClient | None = None


def _get_auth0_jwks_client() -> PyJWKClient | None:
    global _jwks_client
    if not AUTH0_DOMAIN:
        return None
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json")
    return _jwks_client


def decode_jwt_token(token: str, required_role: str | None = None) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg not in ("HS256", "RS256"):
            raise HTTPException(status_code=401, detail="Unsupported token algorithm")
        options = {"require": ["exp", "iat"], "verify_exp": True}
        leeway = 30
        if alg == "RS256" and AUTH0_DOMAIN and AUTH0_AUDIENCE:
            jwks_client = _get_auth0_jwks_client()
            if jwks_client is None:
                raise HTTPException(status_code=401, detail="Auth0 not configured")
            signing_key = jwks_client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                options=options,
                audience=AUTH0_AUDIENCE,
                issuer=AUTH0_ISSUER or None,
                leeway=leeway,
            )
        else:
            audience = JWT_AUDIENCE or None
            if audience:
                payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options=options, audience=audience, leeway=leeway)
            else:
                payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options=options, leeway=leeway)
    except jwt.ExpiredSignatureError:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            logging.warning(f"JWT Expired: exp={unverified.get('exp')}, now={time.time()}")
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception as e:
        logging.warning(f"JWT decode failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    if required_role:
        roles = payload.get("roles") or payload.get("permissions") or []
        # admin is a superrole — bypass all role checks
        if "admin" not in roles and required_role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
    return payload


def verify_jwt(request: Request, required_role: str | None = None) -> dict:
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    payload = decode_jwt_token(token, required_role=required_role)
    # Attach user payload to request state for downstream audit/context
    try:
        request.state.user = payload
    except Exception:
        pass
    return payload


def require_role(role: str):
    """Return a FastAPI-compatible dependency that verifies JWT and enforces *role*.

    Uses a proper closure (not functools.partial) so FastAPI v0.100+ can correctly
    introspect the `request: Request` parameter and inject the HTTP Request object
    rather than treating it as a query-string field (which partial causes in newer
    FastAPI/Starlette versions).
    """
    async def _dep(request: Request) -> dict:
        return verify_jwt(request, required_role=role)
    return _dep



def rate_limit(request: Request, key: str | None = None, limit: int | None = None) -> None:
    """Simple in-memory per-minute rate limiting keyed by IP or custom key.

    For MVP only. Replace with Redis or a gateway policy later.
    """
    limit = limit or RATE_LIMIT
    now = int(time.time())
    minute = now // 60
    ip = request.client.host if request.client else "unknown"
    k = key or ip
    bucket_key = f"{k}:{minute}"
    bucket = _rate_store.setdefault(bucket_key, [])
    bucket.append(now)
    # prune old buckets
    for old_key in list(_rate_store.keys()):
        if old_key.endswith(str(minute - 2)):
            _rate_store.pop(old_key, None)
    if len(bucket) > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            dur_ms = (time.perf_counter() - start) * 1000
            path = request.url.path
            method = request.method
            logging.info(f"{method} {path} handled in {dur_ms:.1f} ms")
