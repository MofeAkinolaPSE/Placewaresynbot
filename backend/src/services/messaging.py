"""
Messaging Service — ACE
==================================
Handles outbound communication for bulk message jobs:
  • SMS via Termii API (set TERMII_API_KEY + TERMII_SENDER_ID)
  • WhatsApp via Termii API (same credentials — see send_whatsapp)
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

Channels supported: sms | email | whatsapp (whatsapp currently unused by the
bulk-message flow -- SMS and email are the two production channels).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

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

# ── Termii (SMS / WhatsApp) ───────────────────────────────────────────────────
# Confirmed against Termii's own API docs (developers.termii.com/messaging-api):
# SMS and WhatsApp are the SAME endpoint (POST /api/sms/send) -- the only
# difference is the `channel` value. This one function backs both.

def _send_termii(to_phone: str, message: str, channel: str) -> dict[str, Any]:
    """
    Send a message via Termii's single-send endpoint.
    `to_phone` must include country code without '+' (e.g. "2348012345678").
    `channel`: "generic" (cheap, promotional, blocked for DND-registered
    numbers, MTN-restricted 8PM-8AM) | "dnd" (bypasses DND, for
    transactional/urgent) | "whatsapp".
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


def send_whatsapp(to_phone: str, message: str) -> dict[str, Any]:
    """Send a WhatsApp message via Termii. Not currently used by the bulk-
    message flow (SMS + email are the two production channels for now)."""
    return _send_termii(to_phone, message, "whatsapp")


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


def resolve_bulk_recipients(recipient_filter: dict[str, Any] | None) -> list[dict]:
    """
    Resolve the customers table against a recipient_filter, the same
    resolution dispatch_job() uses to actually send -- extracted so the ACE
    chat bulk-message preview step (service.py's
    _handle_send_bulk_message_action) can show a real recipient count before
    anything is sent, without duplicating this query.
    Supports filter keys: facility_type (the only one dispatch_job actually
    applies today -- stage/last_ordered_days are accepted in the API shape
    but not yet implemented as real filters).

    IMPORTANT: customers has no flat phone/email columns -- both live inside
    contact_details JSONB (confirmed live: selecting a bare "phone" column
    throws "column does not exist", which silently resolved to zero
    recipients for every bulk job, SMS or email, before this fix -- this
    predates today's SMS work entirely). Each returned dict is normalized to
    {id, name, phone, email} so dispatch_job()'s channel branches don't need
    to know about the JSONB shape.
    """
    from src.db import db  # lazy import to avoid circular dependency

    rec_filter = recipient_filter or {}

    def _run(q):
        resp = q.limit(500).execute()
        rows = resp.data or []
        out = []
        for r in rows:
            cd = r.get("contact_details") or {}
            out.append({
                "id":    r.get("id"),
                "name":  r.get("name"),
                "phone": _normalize_ng_phone(cd.get("phone")),
                "email": (cd.get("email") or "").strip() or None,
            })
        return out

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
    Resolves recipients from the recipient_filter (or broadcasts to all active customers).
    Returns a summary dict: {status, total, sent, failed, errors}.
    """
    channel      = (job.get("channel") or "").lower()
    message_text = job.get("message_text") or ""
    subject      = job.get("subject") or "Message from Placeware"
    rec_filter   = job.get("recipient_filter") or {}

    if channel not in {"sms", "whatsapp", "email"}:
        raise ValueError(f"Unsupported channel: {channel!r}")
    if not message_text:
        raise ValueError("message_text is empty")

    recipients = resolve_bulk_recipients(rec_filter)

    total  = len(recipients)
    sent   = 0
    failed = 0
    errors: list[str] = []

    for customer in recipients:
        try:
            if channel == "sms":
                phone = (customer.get("phone") or "").strip()
                if not phone:
                    failed += 1
                    errors.append(f"customer {customer.get('id')}: no phone number")
                    continue
                send_sms(phone, message_text)
                sent += 1

            elif channel == "whatsapp":
                phone = (customer.get("phone") or "").strip()
                if not phone:
                    failed += 1
                    errors.append(f"customer {customer.get('id')}: no phone number")
                    continue
                send_whatsapp(phone, message_text)
                sent += 1

            elif channel == "email":
                email = (customer.get("email") or "").strip()
                if not email or "@" not in email:
                    failed += 1
                    errors.append(f"customer {customer.get('id')}: invalid email")
                    continue
                send_email(email, subject, message_text)
                sent += 1

        except Exception as exc:
            failed += 1
            errors.append(f"customer {customer.get('id')}: {exc}")
            logger.warning("dispatch_job: send failed for customer %s: %s", customer.get("id"), exc)

    status = "sent" if failed == 0 else ("partial" if sent > 0 else "failed")
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
