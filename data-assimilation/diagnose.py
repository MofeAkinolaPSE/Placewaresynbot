"""diagnose.py — Two-pipeline health check for the Placeware data stack.

Tests:
  Pipeline 1: DB table row counts — confirms data landed in the right tables.
  Pipeline 2: API endpoint responses — confirms data reaches the frontend format.

Usage:
    python diagnose.py

No arguments needed. Reads CONFIG from assimilate.py constants.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config (mirrors assimilate.py) ───────────────────────────────────────────
BACKEND_URL  = "http://localhost:8000"
ADMIN_EMAIL  = "admin@placeware.com"
ADMIN_PASS   = "pware1234"
DB_CONTAINER = "backend-db-1"
DB_NAME      = "synbot_demo"
DB_USER      = "postgres"

# ── Colour helpers ────────────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"

def _ok(msg: str)   -> str: return f"{_GREEN}✓  {msg}{_RESET}"
def _fail(msg: str) -> str: return f"{_RED}✗  {msg}{_RESET}"
def _warn(msg: str) -> str: return f"{_YELLOW}!  {msg}{_RESET}"


# =============================================================================
# Pipeline 1 — DB table row counts
# =============================================================================

_DB_CHECKS: List[Tuple[str, str, Optional[int], str]] = [
    # (table, label, min_expected_rows, note_if_zero)
    ("customers",               "CRM customer records",        1,  "trigger bug or assimilate not run"),
    ("sage_customers_snapshot", "Sage customers snapshot",     1,  "assimilate.py not run"),
    ("sage_inventory_snapshot", "Inventory (stock on hand)",   1,  "stock_on_hand entity not uploaded"),
    ("sage_items_snapshot",     "Items catalogue",             1,  "assimilate.py not run"),
    ("crm_prospects",           "CRM Lead Finder prospects",   1,  "contacts not pushed yet"),
    ("sage_coa_snapshot",       "Chart of accounts",           1,  "assimilate.py not run"),
    ("sage_vendors_snapshot",   "Vendors",                     1,  "assimilate.py not run"),
    ("sage_gl_snapshot",        "GL journal entries (V2)",     None, "needs GL extraction — expected empty for V1"),
    ("sage_ar_snapshot",        "AR invoices (V2)",            None, "needs AR extraction — expected empty for V1"),
    ("sage_ap_snapshot",        "AP invoices (V2)",            None, "needs AP extraction — expected empty for V1"),
]


def _psql(sql: str) -> str:
    """Run a SQL query inside the DB container and return stdout."""
    cmd = [
        "docker", "exec", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME,
        "-t", "-c", sql,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def check_pipeline_1() -> int:
    """Check DB table row counts. Returns number of failures."""
    print("\n── Pipeline 1: DB Table Row Counts ─────────────────────────────")
    failures = 0

    for table, label, min_rows, note in _DB_CHECKS:
        out = _psql(f"SELECT count(*) FROM {table};")
        try:
            count = int(out)
        except ValueError:
            print(f"  {_fail(f'{label:<40} ERROR reading table: {out[:60]}')}")
            failures += 1
            continue

        if min_rows is None:
            # V2 table — expected empty, just report
            status = _warn(f"{label:<40} {count:>6} rows  [V2 — expected empty]")
        elif count >= min_rows:
            status = _ok(f"{label:<40} {count:>6} rows")
        else:
            status = _fail(f"{label:<40} {count:>6} rows  [{note}]")
            failures += 1

        print(f"  {status}")

    return failures


# =============================================================================
# Pipeline 2 — API endpoint responses
# =============================================================================

def _get_token() -> Optional[str]:
    try:
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.post(
            f"{BACKEND_URL}/token",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASS},
            timeout=10, verify=False,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None
    except Exception:
        return None


def _get(path: str, token: str) -> Tuple[int, Any]:
    try:
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(
            f"{BACKEND_URL.rstrip('/')}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15, verify=False,
        )
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as exc:
        return 0, str(exc)


def _check_crm_customers(data: Any) -> Tuple[bool, str]:
    rows = data if isinstance(data, list) else (data or {}).get("data", [])
    if isinstance(rows, list) and len(rows) > 0:
        return True, f"{len(rows)} customer records returned"
    return False, "empty list or wrong shape"


def _check_crm_dashboard(data: Any) -> Tuple[bool, str]:
    d = data.get("data", data) if isinstance(data, dict) else {}
    pv = d.get("pipeline_value", None)
    if pv is not None:
        return True, f"pipeline_value={pv}"
    return False, "missing pipeline_value field"


def _check_dashboard_finance(data: Any) -> Tuple[bool, str]:
    d = data.get("data", data) if isinstance(data, dict) else {}
    ar = d.get("ar", {})
    if isinstance(ar, dict) and "total_amount" in ar:
        return True, f"ar.total_amount={ar.get('total_amount')}"
    return False, "missing ar.total_amount field"


def _check_analytics_trend(data: Any) -> Tuple[bool, str]:
    d = data.get("data", data) if isinstance(data, dict) else {}
    periods = d.get("periods", [])
    if isinstance(periods, list) and len(periods) > 0:
        return True, f"{len(periods)} periods"
    return False, "empty periods array — needs GL/AR data (V2)"


def _check_stock(data: Any) -> Tuple[bool, str]:
    # /stock returns {"stock": [...], "source": ..., "disclaimer": ...}
    if isinstance(data, dict):
        rows = data.get("stock", data.get("data", []))
    else:
        rows = data
    if isinstance(rows, list) and len(rows) > 0:
        return True, f"{len(rows)} SKUs"
    return False, "empty — sage_inventory_snapshot has no data"


_API_CHECKS = [
    # (path, label, validator_fn, critical)
    ("/crm/customers",      "CRM customer list",       _check_crm_customers,    True),
    ("/dashboard/crm",      "CRM dashboard metrics",   _check_crm_dashboard,    True),
    ("/dashboard/finance",  "Finance KPI summary",     _check_dashboard_finance, False),
    ("/analytics/trend",    "Cash flow trend chart",   _check_analytics_trend,  False),
    ("/stock",              "Inventory / stock page",  _check_stock,            True),
]


def check_pipeline_2() -> int:
    """Call each frontend-driving endpoint and validate the response shape. Returns failures."""
    print("\n── Pipeline 2: API → Frontend Endpoint Checks ───────────────────")

    token = _get_token()
    if not token:
        print(f"  {_fail('Could not obtain auth token — backend may be down')}")
        return len(_API_CHECKS)

    failures = 0
    for path, label, validator, critical in _API_CHECKS:
        status_code, body = _get(path, token)
        if status_code == 0:
            print(f"  {_fail(f'{label:<40} CONNECTION ERROR')}")
            if critical:
                failures += 1
            continue
        if status_code not in (200, 201):
            print(f"  {_fail(f'{label:<40} HTTP {status_code}')}")
            if critical:
                failures += 1
            continue

        ok, detail = validator(body)
        if ok:
            print(f"  {_ok(f'{label:<40} {detail}')}")
        else:
            msg = f"{label:<40} {detail}"
            if critical:
                print(f"  {_fail(msg)}")
                failures += 1
            else:
                print(f"  {_warn(msg)}")

    return failures


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 60)
    print("  Placeware Data Pipeline Diagnostic")
    print("=" * 60)

    p1_fails = check_pipeline_1()
    p2_fails = check_pipeline_2()
    total_fails = p1_fails + p2_fails

    print("\n── Summary ──────────────────────────────────────────────────────")
    if total_fails == 0:
        print(f"  {_ok('All critical checks passed — both pipelines healthy')}")
    else:
        print(f"  {_fail(f'{total_fails} critical check(s) failed')}")
        print(f"  {'Run python assimilate.py to repopulate missing tables.'}")

    print()


if __name__ == "__main__":
    main()
