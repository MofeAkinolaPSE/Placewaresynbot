"""Signed licence token format, shared by the backend and the NeuroLayer issuing tool.

A licence is one line of text:

    PWL1.<base64url(payload JSON)>.<base64url(Ed25519 signature)>

The signature covers the bytes "PWL1.<payload part>". Only the NeuroLayer private key
can produce it; the application holds the public key and can only verify. Editing any
field (dates, duration, grace) breaks the signature.

This module has no dependency on the rest of the app so tools/licensing can import it.
"""
from __future__ import annotations

import base64
import calendar
import datetime as dt
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

TOKEN_PREFIX = "PWL1"
LOCK_MODES = ("full", "read_only")


class LicenseFormatError(ValueError):
    """The licence text is malformed or its signature does not verify."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def add_months(start: dt.date, months: int) -> dt.date:
    """Calendar-month addition, clamped to month end (31 Jan + 1 month = 28/29 Feb)."""
    idx = start.month - 1 + months
    year, month = start.year + idx // 12, idx % 12 + 1
    return dt.date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def validate_payload(payload: dict) -> None:
    required = ("license_id", "issued_to", "start_date", "duration_months", "issued_at")
    missing = [k for k in required if payload.get(k) in (None, "")]
    if missing:
        raise LicenseFormatError(f"licence is missing fields: {', '.join(missing)}")
    dt.date.fromisoformat(payload["start_date"])
    parse_ts(payload["issued_at"])
    if not isinstance(payload["duration_months"], int) or payload["duration_months"] < 1:
        raise LicenseFormatError("duration_months must be a whole number >= 1")
    grace = payload.get("grace_period_days", 7)
    if not isinstance(grace, int) or grace < 0:
        raise LicenseFormatError("grace_period_days must be a whole number >= 0")
    if payload.get("lock_mode", "full") not in LOCK_MODES:
        raise LicenseFormatError(f"lock_mode must be one of {LOCK_MODES}")


def parse_ts(value: str) -> dt.datetime:
    ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def sign_license(payload: dict, private_key: Ed25519PrivateKey) -> str:
    validate_payload(payload)
    body = _b64e(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signed = f"{TOKEN_PREFIX}.{body}".encode("ascii")
    return f"{TOKEN_PREFIX}.{body}.{_b64e(private_key.sign(signed))}"


def extract_token(file_text: str) -> str:
    """The token is the first line that is not blank and not a '#' comment."""
    for line in file_text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise LicenseFormatError("licence file contains no licence token")


def verify_license(token: str, public_key: Ed25519PublicKey) -> dict:
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LicenseFormatError("not a Placeware licence token")
    try:
        public_key.verify(_b64d(parts[2]), f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (InvalidSignature, ValueError) as exc:
        raise LicenseFormatError("licence signature is not valid") from exc
    try:
        payload = json.loads(_b64d(parts[1]))
    except ValueError as exc:
        raise LicenseFormatError("licence payload is unreadable") from exc
    validate_payload(payload)
    return payload


def load_public_key(b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def license_window(payload: dict) -> tuple[dt.date, dt.date, dt.date]:
    """(start, expiry, grace_end). Licence runs start <= day < expiry; grace runs to grace_end."""
    start = dt.date.fromisoformat(payload["start_date"])
    expiry = add_months(start, payload["duration_months"])
    return start, expiry, expiry + dt.timedelta(days=payload.get("grace_period_days", 7))
