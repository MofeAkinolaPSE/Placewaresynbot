Ready for review
Select text to add comments on the plan
Plan: assimilate.py — One-Command Data Assimilation Script
Context
The pipeline works (customers, vendors, chart_of_accounts, items all upload cleanly via /sage/import/batch). The user's latest run failed with a relative path error — they ran --source "Installer Files\Sage Data 1" from inside the data-assimilation/ folder, so Python resolved it as data-assimilation/Installer Files/Sage Data 1 which doesn't exist. The real path is one level up: <project root>/Installer Files/Sage Data 1.

The user also used --token YOUR_JWT_TOKEN literally instead of an actual token.

Goal: Create a single script data-assimilation/assimilate.py that requires zero arguments — it self-discovers the Sage folder path, auto-fetches a JWT from the backend, and runs the full assimilation for all configured companies. To add a new company or entity later, just edit the config block at the top and re-run.

What's Already Done (previous sessions)
hard_reader.py — binary readers for customers, vendors, chart_of_accounts, items (LINEITEM.DAT)
loader.py — SSL/redirect fix (manual re-POST on 301), NUL byte fix in _clean_lstring
sage_csv_import.py (backend) — vendor column fix (bank_details/created_date removed)
All 4 entities successfully uploaded to Synbot DB for both planigli and plaphaen
Tier 2 DAT Files — Reality Check
The old plan listed files that do not exist in Sage 50 2013. Actual file scan of planigli/:

Entity	DAT File	Exists?	Size	Decision
staff	EMPLOYEE.DAT	YES	Small	Post-launch — needs probe
stock_on_hand	INVCOST.DAT	YES	64 MB	Post-launch — needs probe
gl_journal_entries	JRNLHDR.DAT + JRNLROW.DAT	YES	133 + 220 MB	Out of scope (too large)
purchase_orders	PURCHASEORDER.DAT	NO	—	File doesn't exist in Sage 50 2013
hr_payroll	PAYROLL.DAT	NO	—	File doesn't exist in Sage 50 2013
For V1: skip Tier 2. The 4 working entities give Synbot full knowledge of customers, vendors, GL codes, and the drug/product catalog. Tier 2 is a post-launch sprint.

Implementation Plan
New file: data-assimilation/assimilate.py
~120 lines. Three sections:

1. Config block (only thing to edit for future runs)

BACKEND_URL = "http://localhost:8000"   # direct to FastAPI, no nginx redirect
ADMIN_EMAIL = "admin@placeware.com"
ADMIN_PASS  = "pware1234"
COMPANIES   = ["planigli", "plaphaen"]  # add/remove company folder names here

# Sage root is auto-resolved relative to this file's location
_HERE     = os.path.dirname(os.path.abspath(__file__))
SAGE_ROOT = os.path.normpath(os.path.join(_HERE, "..", "Installer Files", "Sage Data 1"))
2. Token fetch

def _get_token() -> str:
    resp = requests.post(f"{BACKEND_URL}/token",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]
3. Per-company ingest (calls existing library code, no duplication)

def _ingest_company(company: str, token: str, dry_run: bool = False) -> dict:
    # uses hard_reader, field_maps, loader — no new logic
    datasets = {}
    for entity in available_entities():
        rows_raw = read_entity(entity, SAGE_ROOT, company=company)
        if not rows_raw: continue
        avail = field_names(entity)
        mapped = [m for r in rows_raw for m in [field_maps.map_row(r, entity, avail)] if m]
        if mapped: datasets[entity] = mapped
    if dry_run:
        _print_dry(company, datasets)
        return {}
    return upload_to_backend(datasets, BACKEND_URL, token)
4. main() — orchestrates all companies, prints final summary table

5. Optional --dry-run flag — shows row counts without uploading (useful for testing on the production server before committing the import).

No changes needed to existing files
ingest.py, hard_reader.py, loader.py, field_maps.py all stay as-is.

Files to Create/Change
File	Action
data-assimilation/assimilate.py	CREATE — new ~120-line script
Verification
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\data-assimilation"

# Preview (no DB writes)
python assimilate.py --dry-run

# Full run (populates Synbot DB)
python assimilate.py
Expected output:

Sage root : C:\...\Installer Files\Sage Data 1  [OK]
Backend   : http://localhost:8000
Token     : fetched OK

=== planigli ===
  customers            140 rows   succeeded
  chart_of_accounts     65 rows   succeeded
  vendors                7 rows   succeeded
  items                 57 rows   succeeded

=== plaphaen ===
  customers             15 rows   succeeded
  chart_of_accounts      3 rows   succeeded
  vendors                1 rows   succeeded
  items                  1 rows   succeeded

TOTAL: 289 rows across 2 companies