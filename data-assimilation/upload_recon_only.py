"""One-shot script: parse reconciliation files and POST the 5 recon rows.

Does NOT re-upload cash_register data (already in DB from full run).
"""
import os, sys, json, requests, urllib3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BACKEND_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@placeware.com"
ADMIN_PASS  = "pware1234"
RECON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "sage-exports", "Account reconciliation")

urllib3.disable_warnings()

# ── Auth ──────────────────────────────────────────────────────────────────────
resp = requests.post(
    f"{BACKEND_URL}/token",
    data={"username": ADMIN_EMAIL, "password": ADMIN_PASS},
    timeout=15, verify=False,
)
resp.raise_for_status()
token = resp.json().get("access_token") or resp.json().get("token")
print(f"Auth OK (token: {token[:20]}...)")

# ── Parse ─────────────────────────────────────────────────────────────────────
from ingest_sage_exports import (
    ingest_reconciliation, _safe_float_or_none, _safe_date, _get, _norm_header, _read_xlsx, _read_xlsx_raw
)

recon_rows: list = []
dummy_datasets: dict = {}
ingest_reconciliation(RECON_FOLDER, recon_rows, dummy_datasets)

print(f"\nParsed {len(recon_rows)} reconciliation rows")
for r in recon_rows:
    print(f"  {r['snapshot_type']}: outstanding_total={r.get('outstanding_total')} "
          f"count={r.get('outstanding_count')}")

# ── Upload ────────────────────────────────────────────────────────────────────
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
ok = 0
for row in recon_rows:
    payload = {k: v for k, v in row.items() if v is not None}
    r = requests.post(f"{BACKEND_URL}/finance/reconciliation/log",
                      headers=headers, data=json.dumps(payload), timeout=15, verify=False)
    if r.status_code in (200, 201):
        ok += 1
        print(f"  ✓ {row['snapshot_type']}")
    else:
        print(f"  ✗ {row['snapshot_type']}: {r.status_code} {r.text[:120]}")

print(f"\nDone: {ok}/{len(recon_rows)} reconciliation rows uploaded.")
