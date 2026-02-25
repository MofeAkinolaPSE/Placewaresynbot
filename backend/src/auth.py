from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import jwt

try:
    import bcrypt  # type: ignore
except Exception:  # pragma: no cover - environment-specific dependency fallback
    bcrypt = None

from .constants import JWT_SECRET, JWT_AUDIENCE, ACCESS_TOKEN_MINUTES, REFRESH_TOKEN_DAYS


def hash_password(password: str) -> str:
    if bcrypt is None:
        raise RuntimeError("bcrypt is not installed; cannot hash password")
    encoded = password.encode("utf-8")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    if bcrypt is None:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, roles: list[str]) -> tuple[str, dt.datetime]:
    now = dt.datetime.now(dt.timezone.utc)
    exp = now + dt.timedelta(minutes=ACCESS_TOKEN_MINUTES)
    payload: dict[str, object] = {
        "sub": user_id,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if JWT_AUDIENCE:
        payload["aud"] = JWT_AUDIENCE
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return token, exp


def create_refresh_token() -> tuple[str, str, dt.datetime]:
    now = dt.datetime.now(dt.timezone.utc)
    exp = now + dt.timedelta(days=REFRESH_TOKEN_DAYS)
    raw = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw)
    return raw, token_hash, exp


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secure_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def parse_iso8601(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
