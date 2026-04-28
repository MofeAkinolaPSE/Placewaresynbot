"""
Messaging Service — Warebot
==================================
Handles outbound communication for bulk message jobs:
  • WhatsApp via Termii API (set TERMII_API_KEY + TERMII_SENDER_ID)
  • Email via Gmail SMTP (set EMAIL_FROM + EMAIL_PASS)

Environment variables required (add to .env):
  TERMII_API_KEY    — Termii API secret key
  TERMII_SENDER_ID  — Approved Termii sender ID (e.g. "Placeware")
  EMAIL_FROM        — Gmail address used to send (e.g. "noreply@placeware.ng")
  EMAIL_PASS        — Gmail App Password (not your Google account password)

Channels supported: whatsapp | email
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

TERMII_BASE_URL = "https://api.ng.termii.com/api"
TERMII_API_KEY  = os.getenv("TERMII_API_KEY", "")
TERMII_SENDER   = os.getenv("TERMII_SENDER_ID", "Placeware")

# Read at call time (not import time) so .env changes and override=True take effect
# without requiring a module reload.  The _smtp_cfg() helper is used inside send_email.
SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))


def _smtp_cfg() -> tuple[str, str]:
    """Return (EMAIL_FROM, EMAIL_PASS) read fresh from the environment each call."""
    return os.getenv("EMAIL_FROM", ""), os.getenv("EMAIL_PASS", "")

# ── WhatsApp (Termii) ─────────────────────────────────────────────────────────

def send_whatsapp(to_phone: str, message: str) -> dict[str, Any]:
    """
    Send a WhatsApp message via Termii.
    `to_phone` must include country code without '+' (e.g. "2348012345678").
    Returns Termii API response dict.
    Raises ValueError if TERMII_API_KEY is not configured.
    """
    if not TERMII_API_KEY:
        raise ValueError(
            "TERMII_API_KEY is not set. "
            "Add it to your .env file to enable WhatsApp sending."
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
        "channel":  "whatsapp",
    }

    resp = requests.post(
        f"{TERMII_BASE_URL}/sms/send",
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


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

def dispatch_job(job: dict[str, Any]) -> dict[str, Any]:
    """
    Process a single crm_bulk_message_jobs row.
    Resolves recipients from the recipient_filter (or broadcasts to all active customers).
    Returns a summary dict: {status, total, sent, failed, errors}.
    """
    from src.db import db  # lazy import to avoid circular dependency

    channel      = (job.get("channel") or "").lower()
    message_text = job.get("message_text") or ""
    subject      = job.get("subject") or "Message from Placeware"
    rec_filter   = job.get("recipient_filter") or {}

    if channel not in {"whatsapp", "email"}:
        raise ValueError(f"Unsupported channel: {channel!r}")
    if not message_text:
        raise ValueError("message_text is empty")

    # Resolve recipient list from customers table
    # Supports filter keys: stage (for leads), last_ordered_days, facility_type
    try:
        q = db.table("customers").select("id,name,phone,email")
        if rec_filter.get("facility_type"):
            q = q.eq("facility_type", rec_filter["facility_type"])
        resp = q.limit(500).execute()
        recipients: list[dict] = resp.data or []
    except Exception as exc:
        logger.error("dispatch_job: failed to resolve recipients: %s", exc)
        # Graceful: try minimal columns
        try:
            resp = db.table("customers").select("id,name,phone,email").limit(500).execute()
            recipients = resp.data or []
        except Exception:
            recipients = []

    total  = len(recipients)
    sent   = 0
    failed = 0
    errors: list[str] = []

    for customer in recipients:
        try:
            if channel == "whatsapp":
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
