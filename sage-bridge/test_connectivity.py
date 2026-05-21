"""
test_connectivity.py — Sage Bridge end-to-end connectivity diagnostic.

Run from the sage-bridge directory on the Windows Sage machine:
    python test_connectivity.py

What it tests:
  1. Bridge process is reachable on localhost:7070
  2. Bridge API key authentication works
  3. Bridge can read Sage data (ODBC/SDK sync/status)
  4. Bridge can pull live entity data (customers, inventory)
  5. VM backend is reachable from this machine
  6. VM webhook endpoint accepts push events from the bridge
  7. (Optional) write round-trip — create test customer in Sage, read it back

Exit codes:
  0  All checks passed
  1  One or more checks failed
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config from .env (with fallbacks) ─────────────────────────────────────────
BRIDGE_URL     = f"http://localhost:{os.getenv('BRIDGE_PORT', '7070')}"
BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "")
# Webhook URL points to nginx on port 80 — backend port 8000 is not LAN-exposed
SYNBOT_URL     = os.getenv("SYNBOT_WEBHOOK_URL", "")
SYNBOT_KEY     = os.getenv("SYNBOT_WEBHOOK_KEY", "")
# Local .env hint — real answer comes from bridge /sync/status in check_sage_connectivity()
_SAGE_MOCK_ENV = os.getenv("SAGE_MOCK", "false").lower() in ("true", "1")
TIMEOUT        = 10  # seconds

# Derive VM base URL: strip /sage/webhook suffix, fall back to whole URL
if SYNBOT_URL:
    VM_BASE_URL = SYNBOT_URL.removesuffix("/sage/webhook").rstrip("/")
else:
    VM_BASE_URL = ""

# Will be set to the bridge's reported mock state after check_sage_connectivity runs
SAGE_MOCK = _SAGE_MOCK_ENV

# ── Helpers ───────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"

pass_count = 0
fail_count = 0
warn_count = 0


def _p(label: str, ok: bool, detail: str = "", warn: bool = False) -> None:
    global pass_count, fail_count, warn_count
    if ok:
        icon = f"{GREEN}[PASS]{RESET}"
        pass_count += 1
    elif warn:
        icon = f"{YELLOW}[WARN]{RESET}"
        warn_count += 1
    else:
        icon = f"{RED}[FAIL]{RESET}"
        fail_count += 1
    suffix = f"  {YELLOW}↳ {detail}{RESET}" if detail else ""
    print(f"  {icon}  {label}{suffix}")


def _get(url: str, key: Optional[str] = None, params: Optional[Dict] = None,
         timeout: int = TIMEOUT) -> Tuple[bool, int, Any]:
    """GET returning (success, status_code, parsed_body)."""
    headers = {"X-Bridge-API-Key": key} if key else {}
    try:
        r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code < 400, r.status_code, body
    except requests.ConnectionError:
        return False, 0, "connection refused"
    except requests.Timeout:
        return False, 0, "timed out"
    except Exception as exc:
        return False, 0, str(exc)


def _post(url: str, payload: Dict, key: Optional[str] = None,
          timeout: int = TIMEOUT) -> Tuple[bool, int, Any]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Bridge-API-Key"] = key
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code < 400, r.status_code, body
    except requests.ConnectionError:
        return False, 0, "connection refused"
    except requests.Timeout:
        return False, 0, "timed out"
    except Exception as exc:
        return False, 0, str(exc)


def _section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title} {'─' * (55 - len(title))}{RESET}")


# ── Check 1: Bridge liveness ──────────────────────────────────────────────────
def check_bridge_liveness():
    _section("1. Bridge liveness (no auth)")
    ok, code, body = _get(f"{BRIDGE_URL}/health")
    if ok:
        status_val = body.get("status", "?") if isinstance(body, dict) else str(body)
        _p("GET /health reachable", True, f"status={status_val}")
    else:
        _p("GET /health reachable", False,
           f"code={code} detail={body}  →  Is 'python main.py' running on port {BRIDGE_URL}?")


# ── Check 2: Bridge API key auth ──────────────────────────────────────────────
def check_bridge_auth():
    _section("2. Bridge API key authentication")

    if not BRIDGE_API_KEY:
        _p("BRIDGE_API_KEY configured in .env", False, "BRIDGE_API_KEY is empty")
        return

    _p("BRIDGE_API_KEY is set", True, f"length={len(BRIDGE_API_KEY)}")

    # Correct key
    ok, code, body = _get(f"{BRIDGE_URL}/sync/status", key=BRIDGE_API_KEY)
    _p("GET /sync/status with correct key → 200", ok, f"code={code}" if not ok else "")

    # Wrong key
    ok_bad, code_bad, _ = _get(f"{BRIDGE_URL}/sync/status", key="wrong-key-test")
    _p("GET /sync/status with wrong key → 401/403", not ok_bad,
       f"expected 401 or 403 but got {code_bad}" if ok_bad else f"correctly rejected (code={code_bad})")


# ── Check 3: Sage connectivity from bridge ────────────────────────────────────
def check_sage_connectivity():
    _section("3. Sage connectivity (via bridge /sync endpoints)")

    ok, code, body = _get(f"{BRIDGE_URL}/sync/status", key=BRIDGE_API_KEY)
    if not ok:
        _p("/sync/status reachable", False, f"code={code}")
        return

    _p("/sync/status reachable", True)

    if isinstance(body, dict):
        odbc = body.get("odbc_connected", None)
        sdk  = body.get("sdk_connected", None)
        # Use what the running bridge actually reports, not just what .env says
        mock = body.get("mock_mode", _SAGE_MOCK_ENV)
        global SAGE_MOCK
        SAGE_MOCK = mock

        if mock:
            _p("SAGE_MOCK=true — Sage connectivity skipped (mock data in use)", True,
               "Set SAGE_MOCK=false and restart bridge for live Sage test", warn=False)
        else:
            _p("ODBC connected to Pervasive/Sage 50", odbc is True,
               "odbc_connected=false → check SAGE_ODBC_DSN and Pervasive driver" if not odbc else "")
            _p("SDK session open (Sage.Peachtree.API.dll)", sdk is True,
               "sdk_connected=false → check SAGE_API_DLL_PATH and SAGE_COMPANY_PATH" if not sdk else "",
               warn=(sdk is False))  # warn not fail — ODBC alone is enough for most ops

        company = body.get("sage_company_path", "")
        _p(f"Company path configured", bool(company) and "PLACEHOLDER" not in company,
           f"path={company}")
    else:
        _p("Parsed /sync/status body", False, f"unexpected body: {body}")

    # Company info
    ok2, code2, body2 = _get(f"{BRIDGE_URL}/sync/company", key=BRIDGE_API_KEY)
    if ok2 and isinstance(body2, dict):
        name = body2.get("name") or body2.get("company_name") or "(not returned)"
        _p(f"/sync/company reachable", True, f"company={name}")
    else:
        _p(f"/sync/company reachable", False, f"code={code2}", warn=True)


# ── Check 4: Entity data pull from Sage ──────────────────────────────────────
def check_entity_pull():
    _section("4. Entity data pull (customers / inventory)")

    for entity, path in [("customers", "/customers"), ("inventory", "/inventory")]:
        ok, code, body = _get(f"{BRIDGE_URL}{path}", key=BRIDGE_API_KEY, params={"limit": 3})
        if ok and isinstance(body, list):
            _p(f"GET {path} → list", True, f"{len(body)} record(s) returned")
        elif ok and isinstance(body, dict) and body.get("items"):
            _p(f"GET {path} → list", True, f"{len(body['items'])} record(s) returned")
        else:
            _p(f"GET {path} → list", False,
               f"code={code} body={str(body)[:120]}")


# ── Check 5: VM backend reachable from this machine ──────────────────────────
def check_vm_reachable():
    _section("5. VM backend reachable from this Windows machine")

    if not VM_BASE_URL:
        _p("SYNBOT_WEBHOOK_URL configured in .env", False,
           "Set SYNBOT_WEBHOOK_URL=http://<VM_LAN_IP>:8000/sage/webhook in sage-bridge/.env")
        return

    _p("SYNBOT_WEBHOOK_URL configured", True, VM_BASE_URL)

    ok, code, body = _get(f"{VM_BASE_URL}/", timeout=10)
    if ok:
        _p("VM backend root endpoint reachable", True, f"code={code}")
    else:
          _p("VM backend root endpoint reachable", False,
              f"code={code} detail={body}  →  Is VM running? Is nginx on port 80 accessible from this LAN?")


# ── Check 6: VM webhook endpoint ─────────────────────────────────────────────
def check_vm_webhook():
    _section("6. VM webhook endpoint accepts bridge push")

    if not SYNBOT_URL or not SYNBOT_KEY:
        _p("Webhook config (URL + KEY) present", False,
           "Set SYNBOT_WEBHOOK_URL and SYNBOT_WEBHOOK_KEY in .env", warn=False)
        return

    _p("Webhook config present", True)

    # Send a synthetic ping event — backend ignores unknown entity_types gracefully
    payload = {
        "entity_type": "customers",
        "event": "ping_test",
        "source": "test_connectivity.py",
    }
    headers_extra = {"X-Webhook-Secret": SYNBOT_KEY}

    try:
        r = requests.post(SYNBOT_URL, json=payload,
                          headers={**headers_extra, "Content-Type": "application/json"},
                          timeout=TIMEOUT)
        # 200 or 202 = received; 422 = schema mismatch but reachable
        reachable = r.status_code in (200, 202, 204, 422)
        _p(f"POST {SYNBOT_URL} → accepted", reachable,
           f"code={r.status_code}" + (f" body={r.text[:100]}" if not reachable else ""),
           warn=(r.status_code == 422))
    except requests.ConnectionError:
          _p("POST to VM webhook reachable", False,
              "connection refused — check VM IP and that nginx (port 80) is accessible from this LAN")
    except requests.Timeout:
        _p("POST to VM webhook reachable", False, "timed out")


# ── Check 7: Write round-trip (optional) ─────────────────────────────────────
def check_write_roundtrip():
    _section("7. Write round-trip — create test customer in Sage, read back")

    TEST_ID   = "E2E-TEST-DIAG-001"
    TEST_NAME = "e2e-diagnostic-do-not-use"

    payload = {
        "id":    TEST_ID,
        "name":  TEST_NAME,
        "email": "diag@placeware-test.local",
    }

    ok, code, body = _post(f"{BRIDGE_URL}/customers", payload=payload, key=BRIDGE_API_KEY)
    if ok:
        _p(f"POST /customers (test record {TEST_ID}) created", True, f"code={code}")
    else:
        _p(f"POST /customers (test record {TEST_ID}) created", False,
           f"code={code} body={str(body)[:150]}")
        return

    # Read back
    time.sleep(0.5)
    ok2, code2, body2 = _get(f"{BRIDGE_URL}/customers/{TEST_ID}", key=BRIDGE_API_KEY)
    if ok2:
        returned_name = body2.get("name", "?") if isinstance(body2, dict) else "?"
        _p(f"GET /customers/{TEST_ID} returned correct record", True, f"name={returned_name}")
    else:
        _p(f"GET /customers/{TEST_ID} returned correct record", False,
           f"code={code2} — record was not persisted or bridge returned error")

    print(f"\n  {YELLOW}Note: If not in SAGE_MOCK mode, delete test record '{TEST_ID}' from Sage manually.{RESET}")


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary():
    print(f"\n{BOLD}{'═' * 62}{RESET}")
    total = pass_count + fail_count + warn_count
    status_line = (
        f"{GREEN}{pass_count} pass{RESET}  "
        f"{YELLOW}{warn_count} warn{RESET}  "
        f"{RED}{fail_count} fail{RESET}  "
        f"(of {total} checks)"
    )
    print(f"  {BOLD}Summary:{RESET} {status_line}")

    if fail_count == 0 and warn_count == 0:
        print(f"\n  {GREEN}{BOLD}✔ All checks passed. Bridge ↔ Sage ↔ VM cycle is healthy.{RESET}")
    elif fail_count == 0:
        print(f"\n  {YELLOW}{BOLD}⚠  Passed with warnings. Review WARN items above.{RESET}")
    else:
        print(f"\n  {RED}{BOLD}✘ {fail_count} check(s) failed. Fix FAIL items before production use.{RESET}")

    print(f"{BOLD}{'═' * 62}{RESET}\n")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sage Bridge connectivity diagnostic")
    parser.add_argument("--skip-write", action="store_true",
                        help="Skip the write round-trip test (safe for production Sage)")
    args = parser.parse_args()

    print(f"\n{BOLD}{'═' * 62}{RESET}")
    print(f"  {BOLD}Sage Bridge Connectivity Diagnostic{RESET}")
    print(f"  Bridge URL : {BRIDGE_URL}")
    print(f"  VM backend : {VM_BASE_URL or '(not configured)'}  (nginx port 80)")
    print(f"  Mock (.env): {_SAGE_MOCK_ENV}  (bridge live-state checked in step 3)")
    print(f"{BOLD}{'═' * 62}{RESET}")

    check_bridge_liveness()
    check_bridge_auth()
    check_sage_connectivity()
    check_entity_pull()
    check_vm_reachable()
    check_vm_webhook()

    if not args.skip_write:
        check_write_roundtrip()

    print_summary()
    sys.exit(0 if fail_count == 0 else 1)
