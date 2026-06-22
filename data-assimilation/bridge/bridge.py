"""bridge.py — Sage 50 (Peachtree) -> Placeware ACE invoice bridge.

Polls a live Sage 50 company folder for newly-posted transactions
(JrnlHdr.DAT) and pushes them to the Placeware backend through the
existing /sage/import/csv endpoint — no ODBC, no DDF parsing, no Sage
API. Pure byte-pattern scan of the Btrieve .DAT files, validated against
Sage's own bundled "Bellwether Garden Supply" sample company (see
data-assimilation/sage50/btrieve_scanner.py for the discovered record
format).

KNOWN LIMITATION (flagged, not yet resolved): JrnlHdr.DAT stores every
transaction type Sage posts (Sales Invoices, Receipts, Payments, General
Journal entries, ...) — this bridge does not yet distinguish Sales
Invoices from other transaction types, and does not yet extract dollar
amounts (they live on JrnlRow GL distribution rows, not decoded yet).
Every new JrnlHdr record is currently synced as a candidate "invoice"
with reference/customer-name/date only, amount=0. Treat this as a
proof-of-pipeline trial, not a production-accurate AR feed, until that
gap is closed.

Usage:
    python bridge.py --config bridge_config.ini
    python bridge.py --config bridge_config.ini --once   # single poll, then exit (for testing)
"""
from __future__ import annotations

import argparse
import configparser
import csv
import io
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

# ── Make sage50.* importable regardless of where this script is run from ───
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_ASSIM_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _DATA_ASSIM_ROOT)

from sage50.hard_reader import read_entity  # noqa: E402

log = logging.getLogger("bridge")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str) -> Dict[str, Any]:
    cp = configparser.ConfigParser()
    cp.read(path)
    s = cp["bridge"]

    def _resolve(value: str) -> str:
        # Relative paths are resolved against this script's directory, not
        # the current working directory, so the bridge behaves the same
        # regardless of where it's launched from (Task Scheduler, etc).
        return value if os.path.isabs(value) else os.path.join(_HERE, value)

    return {
        "sage_company_path": s.get("sage_company_path"),
        "backend_url": s.get("backend_url", "http://localhost:8000").rstrip("/"),
        "company_id": s.get("company_id", ""),
        "poll_seconds": s.getint("poll_seconds", 60),
        "admin_email": s.get("admin_email", "admin@placeware.com"),
        "admin_pass": s.get("admin_pass", "pware1234"),
        "state_file": _resolve(s.get("state_file", "state.json")),
        "log_file": _resolve(s.get("log_file", "bridge.log")),
    }


# ---------------------------------------------------------------------------
# State (idempotency)
# ---------------------------------------------------------------------------

def load_state(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            log.warning("state file unreadable, starting fresh: %s", path)
    return {"synced_references": [], "last_jrnlhdr_mtime": 0.0}


def save_state(state: Dict[str, Any], path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Auth — same flow as assimilate.py's _get_token()
# ---------------------------------------------------------------------------

class TokenCache:
    def __init__(self, cfg: Dict[str, Any]):
        self._cfg = cfg
        self._token: Optional[str] = None
        self._fetched_at: float = 0.0
        self._ttl_seconds = 40 * 60  # refresh a bit before the ~45 min server expiry

    def get(self) -> str:
        if self._token and (time.time() - self._fetched_at) < self._ttl_seconds:
            return self._token
        self._token = self._fetch()
        self._fetched_at = time.time()
        return self._token

    def invalidate(self) -> None:
        self._token = None

    def _fetch(self) -> str:
        resp = requests.post(
            f"{self._cfg['backend_url']}/token",
            data={"username": self._cfg["admin_email"], "password": self._cfg["admin_pass"]},
            timeout=15,
        )
        resp.raise_for_status()
        log.info("fetched new JWT")
        return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# CSV upload — reuse the existing /sage/import/csv endpoint, no backend changes
# ---------------------------------------------------------------------------

def _rows_to_csv_bytes(rows: List[Dict[str, Any]], fieldnames: List[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return buf.getvalue().encode("utf-8")


def post_csv(
    cfg: Dict[str, Any],
    tokens: TokenCache,
    file_type: str,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
) -> Dict[str, Any]:
    csv_bytes = _rows_to_csv_bytes(rows, fieldnames)
    url = f"{cfg['backend_url']}/sage/import/csv"

    def _do_post(token: str) -> requests.Response:
        return requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"file_type": file_type, "company_id": cfg["company_id"]},
            files={"file": (f"{file_type}.csv", csv_bytes, "text/csv")},
            timeout=60,
        )

    resp = _do_post(tokens.get())
    if resp.status_code == 401:
        tokens.invalidate()
        resp = _do_post(tokens.get())
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------

INVOICE_HEADER_FIELDS = ["invoice_id", "customer_id", "invoice_date", "due_date", "net_amount", "status"]


def _jrnlhdr_path(sage_company_path: str) -> str:
    return os.path.join(sage_company_path, "JRNLHDR.DAT")


def _jrnlhdr_mtime(sage_company_path: str) -> float:
    path = _jrnlhdr_path(sage_company_path)
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def poll_once(cfg: Dict[str, Any], state: Dict[str, Any], tokens: TokenCache) -> int:
    """Run one poll cycle. Returns the number of new invoices synced."""
    mtime = _jrnlhdr_mtime(cfg["sage_company_path"])
    if mtime == 0.0:
        log.warning("JRNLHDR.DAT not found under %s", cfg["sage_company_path"])
        return 0
    if mtime == state.get("last_jrnlhdr_mtime"):
        return 0  # no change since last check — skip the expensive re-scan

    log.info("JRNLHDR.DAT changed (mtime=%s) — re-scanning", mtime)
    headers = read_entity("invoice_headers", cfg["sage_company_path"], company=None, max_rows=None) or []

    synced = set(state.get("synced_references", []))
    new_headers = [h for h in headers if h.get("reference") and h["reference"] not in synced]

    if not new_headers:
        state["last_jrnlhdr_mtime"] = mtime
        return 0

    rows = []
    for h in new_headers:
        rows.append({
            "invoice_id": h["reference"],
            "customer_id": h.get("name") or "",
            "invoice_date": h.get("date") or "",
            "due_date": h.get("date2") or "",
            "net_amount": 0,  # not yet decoded — see module docstring
            "status": "unpaid",
        })

    result = post_csv(cfg, tokens, "sales_invoices", rows, INVOICE_HEADER_FIELDS)
    log.info("posted %d header(s): %s", len(rows), result.get("status"))

    for h in new_headers:
        synced.add(h["reference"])
    state["synced_references"] = sorted(synced)
    state["last_jrnlhdr_mtime"] = mtime
    return len(rows)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Placeware Sage 50 invoice bridge")
    parser.add_argument("--config", default=os.path.join(_HERE, "bridge_config.ini"))
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit (for testing)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(cfg["log_file"], encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    log.info("bridge starting — sage_company_path=%s backend_url=%s company_id=%s",
              cfg["sage_company_path"], cfg["backend_url"], cfg["company_id"])

    state = load_state(cfg["state_file"])
    tokens = TokenCache(cfg)

    if args.once:
        n = poll_once(cfg, state, tokens)
        save_state(state, cfg["state_file"])
        log.info("single poll complete — %d new invoice(s) synced", n)
        return

    while True:
        try:
            n = poll_once(cfg, state, tokens)
            if n:
                log.info("synced %d new invoice(s)", n)
        except Exception:
            log.exception("poll cycle failed")
        finally:
            save_state(state, cfg["state_file"])
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    main()
