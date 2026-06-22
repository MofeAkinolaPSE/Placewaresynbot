"""
Quick email credential smoke-test for ACE.
Sends two test emails to the address in config.yaml (akinolamofe2@gmail.com):
  1. A plain-text lead notification (via db.send_lead_email path)
  2. A plain-text EOS summary notification (via messaging.send_email)

Run from backend/ directory:
    python test_email_creds.py
"""

import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
TEST_RECIPIENT = "akinolamofe2@gmail.com"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
def _check_env():
    missing = []
    if not EMAIL_FROM:
        missing.append("EMAIL_FROM")
    if not EMAIL_PASS:
        missing.append("EMAIL_PASS")
    if missing:
        print(f"[FAIL] Missing env vars: {', '.join(missing)}")
        print(f"       Check backend/.env — ensure EMAIL_FROM and EMAIL_PASS are set.")
        sys.exit(1)
    print(f"[OK]   EMAIL_FROM  = {EMAIL_FROM}")
    print(f"[OK]   EMAIL_PASS  = {'*' * len(EMAIL_PASS)}  (length={len(EMAIL_PASS)})")
    print(f"[OK]   Recipient   = {TEST_RECIPIENT}")


# ── Core send helper (mirrors messaging.py logic) ─────────────────────────────
def _send(subject: str, body_html: str, body_text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = TEST_RECIPIENT
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.sendmail(EMAIL_FROM, [TEST_RECIPIENT], msg.as_string())


# ── Test 1: Lead notification ─────────────────────────────────────────────────
def test_lead_email():
    print("\n── Test 1: Lead notification email ──")
    subject = "[ACE TEST] New Lead Received"
    body_text = (
        "ACE – Test Lead Alert\n"
        "================================\n"
        "Name   : Test User\n"
        "Email  : test@example.com\n"
        "Service: Vaccine Distribution\n"
        "Message: This is a credential smoke-test. No action needed.\n"
    )
    body_html = f"""
    <html><body>
      <h2 style="color:#2c7be5;">ACE – Test Lead Alert</h2>
      <p>This is an automated <strong>credential smoke-test</strong>. No action required.</p>
      <table cellpadding="6" style="border-collapse:collapse">
        <tr><td><b>Name</b></td><td>Test User</td></tr>
        <tr><td><b>Email</b></td><td>test@example.com</td></tr>
        <tr><td><b>Service</b></td><td>Vaccine Distribution</td></tr>
        <tr><td><b>Message</b></td><td>Smoke-test run on backend email path.</td></tr>
      </table>
    </body></html>"""

    try:
        _send(subject, body_html, body_text)
        print(f"[PASS] Lead email sent → {TEST_RECIPIENT}")
    except smtplib.SMTPAuthenticationError as exc:
        print(f"[FAIL] Authentication error: {exc}")
        print("       Ensure EMAIL_PASS is a Gmail App Password (not your account password).")
        print("       Generate one at: https://myaccount.google.com/apppasswords")
        raise
    except Exception as exc:
        print(f"[FAIL] Unexpected error: {exc}")
        raise


# ── Test 2: EOS summary notification ──────────────────────────────────────────
def test_eos_email():
    print("\n── Test 2: EOS summary notification email ──")
    subject = "[ACE TEST] EOS Daily Summary"
    body_text = (
        "ACE – EOS Summary (Test)\n"
        "====================================\n"
        "Date    : 2026-04-26\n"
        "Orders  : 3 processed\n"
        "Leads   : 2 captured\n"
        "Status  : All systems operational\n\n"
        "Note: This is a credential smoke-test only.\n"
    )
    body_html = f"""
    <html><body>
      <h2 style="color:#2c7be5;">ACE – EOS Daily Summary (Test)</h2>
      <p>This is an automated <strong>credential smoke-test</strong>. No action required.</p>
      <table cellpadding="6" style="border-collapse:collapse">
        <tr><td><b>Date</b></td><td>2026-04-26</td></tr>
        <tr><td><b>Orders Processed</b></td><td>3</td></tr>
        <tr><td><b>Leads Captured</b></td><td>2</td></tr>
        <tr><td><b>System Status</b></td><td style="color:green;">All systems operational</td></tr>
      </table>
      <p style="color:#888;font-size:12px;">Sent by ACE · credential smoke-test</p>
    </body></html>"""

    try:
        _send(subject, body_html, body_text)
        print(f"[PASS] EOS email sent → {TEST_RECIPIENT}")
    except smtplib.SMTPAuthenticationError as exc:
        print(f"[FAIL] Authentication error: {exc}")
        raise
    except Exception as exc:
        print(f"[FAIL] Unexpected error: {exc}")
        raise


# ── Runner ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  ACE – Email Credential Smoke-Test")
    print("=" * 55)
    _check_env()

    failures = []
    for test_fn in [test_lead_email, test_eos_email]:
        try:
            test_fn()
        except Exception:
            failures.append(test_fn.__name__)

    print()
    if failures:
        print(f"[RESULT] {len(failures)} test(s) FAILED: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("[RESULT] All tests PASSED. Check akinolamofe2@gmail.com for 2 test emails.")
        sys.exit(0)
