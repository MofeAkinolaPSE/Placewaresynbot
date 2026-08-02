"""
verify_onsite.py — Pre-flight check for the client's Windows 7 / Sage 50 machine.

Run this BEFORE starting the service on a new install. It checks, in dependency
order, every assumption the bridge makes, and stops at the first hard failure so
you fix causes rather than chase symptoms.

    python verify_onsite.py            # run all checks
    python verify_onsite.py --report   # also dump real table/column names
    python verify_onsite.py --send-test  # end-to-end: enqueue + deliver 1 event

Why this exists
---------------
The bridge's schema assumptions (sage_schema.py) are unverified guesses drawn
from canonical Peachtree naming. The real names come from the .DDF files in the
client's company folder and can differ. This script tells you exactly what to
change instead of leaving you to decode ODBC errors.

Exit code 0 = ready to start the service. Non-zero = at least one hard failure.
"""
from __future__ import annotations

import argparse
import os
import platform
import struct
import sys
from typing import Callable, List, Tuple

# Results
OK, WARN, FAIL = "OK", "WARN", "FAIL"

_results: List[Tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> str:
    _results.append((name, status, detail))
    icon = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}[status]
    print("{} {}".format(icon, name))
    if detail:
        for line in detail.strip().splitlines():
            print("       " + line)
    return status


# ── 1. Interpreter / platform ────────────────────────────────────────────────

def check_python() -> str:
    bits = struct.calcsize("P") * 8
    version = "{}.{}.{}".format(*sys.version_info[:3])
    detail = "Python {} ({}-bit) on {}".format(version, bits, platform.platform())

    if bits != 32:
        return record(
            "Python is 32-bit", FAIL,
            detail + "\n"
            "The Pervasive ODBC driver shipped with Sage 50 2013 is 32-bit. A "
            "64-bit interpreter CANNOT load it — pyodbc.connect will fail with "
            "an architecture mismatch.\n"
            "Fix: install 32-bit Python 3.9.13 (python-3.9.13.exe, not -amd64) "
            "and rebuild the venv.",
        )

    if sys.version_info[:2] != (3, 9):
        return record(
            "Python version", WARN,
            detail + "\n"
            "Expected 3.9 (the last release supporting Windows 7). Other "
            "versions may work on newer Windows but are untested here.",
        )

    return record("Python 3.9, 32-bit", OK, detail)


# ── 2. Config ────────────────────────────────────────────────────────────────

def check_config() -> str:
    try:
        from config import get_settings
        s = get_settings()
    except Exception as exc:
        return record(
            "Configuration loads", FAIL,
            "{}\nFix: copy .env.example to .env and fill in real values.".format(exc),
        )

    problems = []
    if not s.SAGE_MOCK and not os.path.isdir(s.SAGE_COMPANY_PATH):
        problems.append(
            "SAGE_COMPANY_PATH does not exist: {}\n"
            "  Find it via Sage -> Help -> About -> data path.".format(
                s.SAGE_COMPANY_PATH)
        )
    if not s.SYNBOT_WEBHOOK_URL:
        problems.append("SYNBOT_WEBHOOK_URL is empty — events will queue but never send.")
    if s.BRIDGE_INSECURE_SKIP_VERIFY:
        problems.append("BRIDGE_INSECURE_SKIP_VERIFY=true — TLS verification is OFF.")

    if problems:
        return record("Configuration", WARN, "\n".join(problems))
    return record("Configuration", OK, "outbox: {}".format(s.OUTBOX_DB_PATH))


# ── 3. Outbox ────────────────────────────────────────────────────────────────

def check_outbox() -> str:
    try:
        from outbox import get_outbox
        ob = get_outbox()
        stats = ob.stats()
        ob.set_watermark("_verify_probe", "ok")
        assert ob.get_watermark("_verify_probe") == "ok"
    except Exception as exc:
        return record(
            "Outbox writable", FAIL,
            "{}\nThe outbox is the durability guarantee — the service must not "
            "run without it.\nFix: ensure the service account can write to the "
            "bridge's data/ directory.".format(exc),
        )
    return record(
        "Outbox writable", OK,
        "pending={pending} sent={sent} failed={failed}".format(**stats),
    )


# ── 4. ODBC ──────────────────────────────────────────────────────────────────

def check_odbc() -> str:
    try:
        import pyodbc
    except ImportError as exc:
        return record("pyodbc importable", FAIL, str(exc))

    try:
        from config import get_settings
        if get_settings().SAGE_MOCK:
            return record("ODBC connection", WARN, "SAGE_MOCK=true — ODBC not tested.")
    except Exception:
        pass

    drivers = [d for d in pyodbc.drivers()]
    pervasive = [d for d in drivers if "pervasive" in d.lower() or "zen" in d.lower()]
    if not pervasive:
        record(
            "Pervasive ODBC driver present", WARN,
            "No Pervasive/Zen driver in the 32-bit ODBC driver list.\n"
            "Visible drivers: {}\n"
            "Check C:\\Windows\\SysWOW64\\odbcad32.exe (the 32-bit administrator "
            "— NOT the one in Control Panel, which is 64-bit).".format(drivers),
        )

    try:
        import odbc_client as odbc
        ok, msg = odbc.check_connection()
    except Exception as exc:
        return record("ODBC connection", FAIL, str(exc))

    if not ok:
        return record(
            "ODBC connection", FAIL,
            "{}\nCommon causes:\n"
            "  1. 64-bit Python vs 32-bit driver (see the Python check above)\n"
            "  2. DSN not created in the 32-bit ODBC administrator\n"
            "  3. Pervasive Workgroup Engine service not running\n"
            "  4. Sage company folder not readable by this account".format(msg),
        )
    return record("ODBC connection", OK)


# ── 5. Schema ────────────────────────────────────────────────────────────────

def check_schema(report: bool = False) -> str:
    try:
        from config import get_settings
        if get_settings().SAGE_MOCK:
            return record("Schema names", WARN, "SAGE_MOCK=true — schema not verified.")
        import odbc_client as odbc
        import sage_schema as schema
    except Exception as exc:
        return record("Schema names", FAIL, str(exc))

    try:
        actual = set(t.upper() for t in odbc.list_odbc_tables())
    except Exception as exc:
        return record("Schema names", FAIL, "Could not list tables: {}".format(exc))

    if report:
        print("\n--- Tables visible via ODBC ---")
        for t in sorted(actual):
            print("    " + t)
        print()

    missing = []
    for key in schema.REQUIRED_TABLES:
        expected = schema.TABLE_MAP[key].upper()
        if expected not in actual:
            missing.append("  {} -> expected table '{}' NOT FOUND".format(key, expected))

    if missing:
        return record(
            "Required tables exist", FAIL,
            "\n".join(missing) + "\n"
            "The names in sage_schema.py are canonical Peachtree names and may "
            "not match this company file.\n"
            "Fix: find the real names in the list above (re-run with --report) "
            "and update TABLE_MAP in sage_schema.py. No other file needs changing.",
        )
    record("Required tables exist", OK)

    # Column-level check
    col_problems = []
    for table_key, needed in schema.REQUIRED_COLUMNS.items():
        try:
            real_cols = set(c.upper() for c in odbc.list_columns(table_key))
        except Exception as exc:
            col_problems.append("  {}: could not read columns ({})".format(table_key, exc))
            continue
        if report:
            print("--- Columns in {} ({}) ---".format(
                schema.TABLE_MAP[table_key], table_key))
            for c in sorted(real_cols):
                print("    " + c)
            print()
        for col in needed:
            if col.upper() not in real_cols:
                col_problems.append(
                    "  {}.{} NOT FOUND".format(schema.TABLE_MAP[table_key], col)
                )

    if col_problems:
        return record(
            "Required columns exist", FAIL,
            "\n".join(col_problems) + "\n"
            "Fix: update the column constants in sage_schema.py to match. "
            "Re-run with --report to see every real column name.",
        )
    return record("Required columns exist", OK)


# ── 6. SDK ───────────────────────────────────────────────────────────────────

def check_sdk() -> str:
    try:
        from config import get_settings
        s = get_settings()
        if s.SAGE_MOCK:
            return record("Sage SDK", WARN, "SAGE_MOCK=true — SDK not tested.")
    except Exception as exc:
        return record("Sage SDK", FAIL, str(exc))

    if not os.path.isfile(s.SAGE_API_DLL_PATH):
        return record(
            "Sage SDK DLL present", WARN,
            "Not found: {}\n"
            "The bridge still runs in ODBC-only mode, but invoices will be "
            "marked completeness=partial and tax will be missing.".format(
                s.SAGE_API_DLL_PATH),
        )

    try:
        import sdk_client as sdk
        sdk.load_sdk(s.SAGE_API_DLL_PATH)
    except Exception as exc:
        return record(
            "Sage SDK loads", WARN,
            "{}\nCheck .NET Framework 4.x is installed.".format(exc),
        )

    try:
        import sdk_client as sdk
        sdk.init_session(s.SAGE_COMPANY_PATH)
    except Exception as exc:
        return record(
            "Sage SDK session opens", WARN,
            "{}\n"
            "MOST LIKELY CAUSE ON A FRESH INSTALL: the Sage 50 SDK requires a "
            "one-time interactive authorization. Open Sage 50 as an admin user, "
            "then run this script again from an interactive desktop session (NOT "
            "as a service) and approve the prompt when it appears.\n"
            "The service cannot answer that dialog, so this must be done once by "
            "hand before installing the service.".format(exc),
        )
    return record("Sage SDK session opens", OK)


# ── 7. SynBot reachability ───────────────────────────────────────────────────

def check_synbot() -> str:
    try:
        import httpx
        from config import get_settings
        s = get_settings()
    except Exception as exc:
        return record("SynBot reachable", FAIL, str(exc))

    if not s.SYNBOT_WEBHOOK_URL:
        return record("SynBot reachable", WARN, "SYNBOT_WEBHOOK_URL not set.")

    verify = False if s.BRIDGE_INSECURE_SKIP_VERIFY else (s.BRIDGE_CA_CERT_PATH or True)
    try:
        resp = httpx.post(
            s.SYNBOT_WEBHOOK_URL,
            json={"source": "sage_bridge", "event": "connectivity_probe",
                  "entity_type": "_probe", "event_id": "_probe_ignore_me"},
            headers={"X-Webhook-Key": s.SYNBOT_WEBHOOK_KEY},
            timeout=15,
            verify=verify,
        )
    except Exception as exc:
        return record(
            "SynBot reachable", FAIL,
            "{}\nCheck: VM is running, VirtualBox uses a Bridged Adapter, the "
            "Windows firewall allows outbound, and the URL/port are right.".format(exc),
        )

    if resp.status_code == 403:
        return record(
            "SynBot reachable", FAIL,
            "HTTP 403 — webhook secret rejected.\n"
            "SYNBOT_WEBHOOK_KEY here must equal SAGE_BRIDGE_WEBHOOK_SECRET in "
            "SynBot's backend/.env.",
        )
    if resp.status_code >= 500:
        return record("SynBot reachable", WARN,
                      "Reached SynBot but it returned HTTP {}.".format(resp.status_code))
    return record("SynBot reachable", OK, "HTTP {}".format(resp.status_code))


# ── 8. End-to-end ────────────────────────────────────────────────────────────

def check_end_to_end() -> str:
    """Enqueue a real event and confirm the sender delivers it."""
    import time
    try:
        import events as ev
        from outbox import get_outbox
        from sender import _sender
    except Exception as exc:
        return record("End-to-end delivery", FAIL, str(exc))

    ob = get_outbox()
    payload = {"probe": True, "note": "verify_onsite end-to-end test"}
    envelope = ev.build_envelope("_probe", "verify-{}".format(int(time.time())), payload)
    ob.enqueue_batch([{
        "event_id": envelope["event_id"],
        "entity_type": "_probe",
        "sage_id": envelope["sage_id"],
        "payload": envelope,
    }])

    _sender.start()
    deadline = time.time() + 60
    try:
        while time.time() < deadline:
            row = ob._conn().execute(
                "SELECT status, last_error FROM outbox WHERE event_id=?",
                (envelope["event_id"],),
            ).fetchone()
            if row and row["status"] == "sent":
                return record("End-to-end delivery", OK,
                              "Event {} delivered.".format(envelope["event_id"]))
            if row and row["status"] == "failed":
                return record("End-to-end delivery", FAIL,
                              "Event parked as failed: {}".format(row["last_error"]))
            time.sleep(2)
    finally:
        _sender.stop()
    return record("End-to-end delivery", FAIL, "Not delivered within 60s.")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Sage Bridge on-site verification")
    parser.add_argument("--report", action="store_true",
                        help="dump real table and column names")
    parser.add_argument("--send-test", action="store_true",
                        help="enqueue and deliver a real test event")
    args = parser.parse_args()

    print("=" * 68)
    print(" Sage Bridge — on-site verification")
    print("=" * 68)

    checks: List[Callable[[], str]] = [
        check_python,
        check_config,
        check_outbox,
        check_odbc,
        lambda: check_schema(args.report),
        check_sdk,
        check_synbot,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:
            record(getattr(check, "__name__", "check"), FAIL,
                   "unexpected error: {}".format(exc))
        print()

    if args.send_test:
        check_end_to_end()
        print()

    fails = [r for r in _results if r[1] == FAIL]
    warns = [r for r in _results if r[1] == WARN]

    print("=" * 68)
    print(" {} passed, {} warnings, {} failures".format(
        len(_results) - len(fails) - len(warns), len(warns), len(fails)))
    print("=" * 68)

    if fails:
        print("\nBLOCKING — fix these before starting the service:")
        for name, _, _ in fails:
            print("  * " + name)
        return 1
    if warns:
        print("\nUsable, but degraded. Review the warnings above.")
    else:
        print("\nAll checks passed. Safe to start the service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
