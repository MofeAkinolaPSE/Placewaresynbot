"""
Messaging Service — ACE
==================================
Handles outbound communication for bulk message jobs:
  • SMS via Termii API (set TERMII_API_KEY + TERMII_SENDER_ID)
  • Email via Gmail SMTP (set EMAIL_FROM + EMAIL_PASS)

Environment variables required (add to .env):
  TERMII_BASE_URL   — Termii's own docs say this is account-specific (shown
                       on the dashboard next to the API key), so it's
                       configurable rather than hardcoded. Defaults to the
                       standard Nigeria endpoint.
  TERMII_API_KEY    — Termii API secret key
  TERMII_SENDER_ID  — Approved Termii sender ID (e.g. "Placeware")
  EMAIL_FROM        — Gmail address used to send (e.g. "noreply@placeware.ng")
  EMAIL_PASS        — Gmail App Password (not your Google account password)

Channels supported: sms | email.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ── Configuration (read at import time — fail fast if misconfigured) ──────────

TERMII_BASE_URL = os.getenv("TERMII_BASE_URL", "https://api.ng.termii.com/api")
TERMII_API_KEY  = os.getenv("TERMII_API_KEY", "")
TERMII_SENDER   = os.getenv("TERMII_SENDER_ID", "Placeware")

# Read at call time (not import time) so .env changes and override=True take effect
# without requiring a module reload.  The _smtp_cfg() helper is used inside send_email.
SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))


def _smtp_cfg() -> tuple[str, str]:
    """Return (EMAIL_FROM, EMAIL_PASS) read fresh from the environment each call."""
    return os.getenv("EMAIL_FROM", ""), os.getenv("EMAIL_PASS", "")

# ── Termii (SMS) ──────────────────────────────────────────────────────────────

def _send_termii(to_phone: str, message: str, channel: str) -> dict[str, Any]:
    """
    Send a message via Termii's single-send endpoint.
    `to_phone` must include country code without '+' (e.g. "2348012345678").
    `channel`: "generic" (cheap, promotional, blocked for DND-registered
    numbers, MTN-restricted 8PM-8AM) | "dnd" (bypasses DND, for
    transactional/urgent).
    Returns Termii API response dict. Raises ValueError if TERMII_API_KEY is
    not configured or the phone number looks malformed.
    """
    if not TERMII_API_KEY:
        raise ValueError(
            "TERMII_API_KEY is not set. "
            "Add it to your .env file to enable Termii sending."
        )

    phone = to_phone.strip().lstrip("+")
    if not phone.isdigit():
        raise ValueError(f"Invalid phone number format: {to_phone!r}")

    payload = {
        "api_key":  TERMII_API_KEY,
        "to":       phone,
        "from":     TERMII_SENDER,
        "sms":      message,
        "type":     "plain",
        "channel":  channel,
    }

    resp = requests.post(
        f"{TERMII_BASE_URL}/sms/send",
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def send_sms(to_phone: str, message: str, channel: str = "generic") -> dict[str, Any]:
    """Send a plain SMS via Termii. See _send_termii for `channel` semantics."""
    return _send_termii(to_phone, message, channel)


# Nigerian carriers reject promotional-route ("generic") traffic overnight.
# Confirmed live against Termii's own delivery reports for this account:
# 19:54 Delivered, 20:13 Rejected, 21:11 Rejected -- all same number, same
# sender id, same route. Termii still answers {"code":"ok","message":
# "Successfully Sent"} for those and still bills for them, so the send call
# alone cannot tell us a message failed; only the delivery report can. Callers
# check this BEFORE sending so we report an honest failure instead of a
# success that never arrives.
SMS_BLACKOUT_START_HOUR = 20  # 8PM WAT
SMS_BLACKOUT_END_HOUR = 8     # 8AM WAT


def sms_blackout_active(now: "datetime | None" = None) -> bool:
    """True when the generic route will be rejected by the carrier."""
    from datetime import datetime, timedelta, timezone

    # WAT is UTC+1 year-round (no DST), so a fixed offset is correct here.
    wat = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=1)))
    hour = wat.hour
    return hour >= SMS_BLACKOUT_START_HOUR or hour < SMS_BLACKOUT_END_HOUR


def get_delivery_status(message_id: str) -> Optional[str]:
    """Look up a sent message's real delivery status ('Delivered', 'Rejected',
    'Sent', ...). Termii reports this asynchronously, so it can lag the send
    by tens of seconds."""
    if not TERMII_API_KEY or not message_id:
        return None
    try:
        resp = requests.get(
            f"{TERMII_BASE_URL}/sms/inbox",
            params={"api_key": TERMII_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        for row in resp.json() or []:
            if row.get("message_id") == message_id:
                return row.get("status")
    except Exception as exc:
        logger.warning("get_delivery_status failed for %s: %s", message_id, exc)
    return None


def find_client_contacts(name_hint: str, limit: int = 5) -> list[dict]:
    """Resolve a customer name fragment to contact details, so ACE can be told
    'text Royan that their vaccines are on the way' instead of being handed a
    raw phone number. Returns [{id, name, phone, email}] with phone already
    normalized to Termii's required format."""
    from src.db import db  # lazy import to avoid circular dependency

    hint = (name_hint or "").strip()
    if len(hint) < 2:
        return []
    try:
        rows = (
            db.table("customers")
            .select("id,name,contact_details")
            .ilike("name", f"%{hint}%")
            .limit(limit)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("find_client_contacts failed for %r: %s", hint, exc)
        return []

    out = []
    for r in rows:
        cd = r.get("contact_details") or {}
        raw = cd.get("phone")
        out.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "phone": _normalize_ng_phone(raw),
            # Kept so callers can distinguish "no number on file" from "the
            # number on file isn't textable" (22 of 302 customer numbers are
            # 8-digit landlines or 0700 VAS lines) and show it for correction.
            "phone_raw": (str(raw).strip() if raw else None),
            "email": (cd.get("email") or "").strip() or None,
        })
    return out


# ── Email (Gmail SMTP) ────────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Send a plain-text email via Gmail SMTP (STARTTLS on port 587).
    Credentials are read fresh from the environment on every call so that
    .env updates and override=True take effect without a module reload.
    Raises ValueError if EMAIL_FROM / EMAIL_PASS are not configured.
    """
    email_from, email_pass = _smtp_cfg()
    if not email_from or not email_pass:
        raise ValueError(
            "EMAIL_FROM and EMAIL_PASS must be set in .env to enable email sending."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or "(no subject)"
    msg["From"]    = email_from
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.login(email_from, email_pass)
        server.sendmail(email_from, [to_email], msg.as_string())


# ── Bulk job dispatcher ───────────────────────────────────────────────────────

def _normalize_ng_phone(raw: str | None) -> str | None:
    """
    Normalize a Nigerian phone number to Termii's required format (234 +
    10 digits, no '+', no leading 0). Real customers.contact_details phone
    values in this DB are stored inconsistently -- some as bare 10-digit
    local numbers with no country code (e.g. "8029023458"), some with a
    leading 0 -- neither of which Termii accepts as-is (confirmed live:
    Termii rejects anything that isn't full international format). Returns
    None if the value can't be confidently normalized, so that recipient is
    skipped rather than sent to Termii and failed anyway.
    """
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("234") and len(digits) == 13:
        return digits
    if digits.startswith("0") and len(digits) == 11:
        return "234" + digits[1:]
    if len(digits) == 10:
        return "234" + digits
    return None


def _customer_rows_to_recipients(rows: list[dict]) -> list[dict]:
    """Normalize customers rows. Phone/email live in contact_details JSONB --
    customers has no flat phone/email columns (selecting a bare "phone" column
    throws "column does not exist", which previously resolved every bulk job
    to zero recipients)."""
    out = []
    for r in rows:
        cd = r.get("contact_details") or {}
        out.append({
            "kind":  "customer",
            "id":    r.get("id"),
            "name":  r.get("name"),
            "phone": _normalize_ng_phone(cd.get("phone")),
            "email": (cd.get("email") or "").strip() or None,
        })
    return out


def _supplier_rows_to_recipients(rows: list[dict]) -> list[dict]:
    """Normalize suppliers rows. Unlike customers, suppliers DO have flat
    phone / contact_email columns."""
    out = []
    for r in rows:
        out.append({
            "kind":  "supplier",
            "id":    r.get("id"),
            "name":  r.get("name"),
            "phone": _normalize_ng_phone(r.get("phone")),
            "email": (r.get("contact_email") or "").strip() or None,
        })
    return out


def resolve_bulk_recipients(recipient_filter: dict[str, Any] | None) -> list[dict]:
    """
    Resolve recipients for a bulk job -- the same resolution dispatch_job()
    uses to send, extracted so the ACE chat preview can show a real recipient
    count before anything goes out.

    Two modes:
      1. Explicit selection (preferred, used by the UI recipient picker):
         {"customer_ids": [...], "supplier_ids": [...]} -- sends to exactly
         those records and nothing else.
      2. Segment broadcast (legacy): no explicit ids, so every customer is
         resolved, optionally narrowed by {"facility_type": "..."}.

    Each returned dict is normalized to {kind, id, name, phone, email} so
    dispatch_job()'s channel branches don't need to know the per-table shape.
    """
    from src.db import db  # lazy import to avoid circular dependency

    rec_filter = recipient_filter or {}
    customer_ids = rec_filter.get("customer_ids") or []
    supplier_ids = rec_filter.get("supplier_ids") or []

    # Mode 1: explicit selection
    if customer_ids or supplier_ids:
        out: list[dict] = []
        if customer_ids:
            try:
                resp = (
                    db.table("customers")
                    .select("id,name,contact_details")
                    .in_("id", list(customer_ids))
                    .execute()
                )
                out.extend(_customer_rows_to_recipients(resp.data or []))
            except Exception as exc:
                logger.error("resolve_bulk_recipients: customer id lookup failed: %s", exc)
        if supplier_ids:
            try:
                resp = (
                    db.table("suppliers")
                    .select("id,name,phone,contact_email")
                    .in_("id", [str(s) for s in supplier_ids])
                    .execute()
                )
                out.extend(_supplier_rows_to_recipients(resp.data or []))
            except Exception as exc:
                logger.error("resolve_bulk_recipients: supplier id lookup failed: %s", exc)
        return out

    # Mode 2: segment broadcast over all customers
    def _run(q):
        resp = q.limit(500).execute()
        return _customer_rows_to_recipients(resp.data or [])

    try:
        q = db.table("customers").select("id,name,contact_details")
        if rec_filter.get("facility_type"):
            q = q.eq("facility_type", rec_filter["facility_type"])
        return _run(q)
    except Exception as exc:
        logger.error("resolve_bulk_recipients: failed to resolve recipients: %s", exc)
        try:
            return _run(db.table("customers").select("id,name,contact_details"))
        except Exception:
            return []


def dispatch_job(job: dict[str, Any]) -> dict[str, Any]:
    """
    Process a single crm_bulk_message_jobs row.
    Resolves recipients from the recipient_filter -- either an explicit
    customer_ids/supplier_ids selection or a segment broadcast.
    Returns a summary dict: {status, total, sent, failed, errors}.
    """
    channel      = (job.get("channel") or "").lower()
    message_text = job.get("message_text") or ""
    subject      = job.get("subject") or "Message from Placeware"
    rec_filter   = job.get("recipient_filter") or {}

    if channel not in {"sms", "email"}:
        raise ValueError(f"Unsupported channel: {channel!r}")
    if not message_text:
        raise ValueError("message_text is empty")

    recipients = resolve_bulk_recipients(rec_filter)

    total  = len(recipients)
    sent   = 0
    failed = 0
    errors: list[str] = []

    for recipient in recipients:
        label = f"{recipient.get('kind', 'customer')} {recipient.get('id')}"
        try:
            if channel == "sms":
                phone = (recipient.get("phone") or "").strip()
                if not phone:
                    failed += 1
                    errors.append(f"{label}: no usable phone number")
                    continue
                send_sms(phone, message_text)
                sent += 1

            elif channel == "email":
                email = (recipient.get("email") or "").strip()
                if not email or "@" not in email:
                    failed += 1
                    errors.append(f"{label}: invalid email")
                    continue
                send_email(email, subject, message_text)
                sent += 1

        except Exception as exc:
            failed += 1
            errors.append(f"{label}: {exc}")
            logger.warning("dispatch_job: send failed for %s: %s", label, exc)

    # Must match the crm_bulk_message_jobs.status CHECK constraint
    # (queued|processing|completed|failed) -- returning "sent"/"partial" here
    # previously made the caller's status write blow up on the constraint
    # after the messages had already gone out.
    status = "completed" if sent > 0 else "failed"
    logger.info(
        "dispatch_job complete: channel=%s total=%d sent=%d failed=%d",
        channel, total, sent, failed,
    )
    return {
        "status":  status,
        "total":   total,
        "sent":    sent,
        "failed":  failed,
        "errors":  errors[:20],  # cap to avoid huge response
    }
