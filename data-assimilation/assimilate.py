"""assimilate.py — One-command Placeware data assimilation.

Run this script (no arguments) to populate Synbot with all Placeware
Sage 50 data.  It self-discovers the Sage folder, auto-fetches a JWT
from the backend, and ingests every company in the COMPANIES list.

Usage
-----
    # Preview counts without writing to the DB
    python assimilate.py --dry-run

    # Full run — writes all data into Synbot
    python assimilate.py

To add a new company or change any setting, edit the CONFIG block below
and re-run.  The script is idempotent — safe to run multiple times.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ── Ensure stdout handles Unicode on Windows (CP1252 console) ────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Add data-assimilation/ to path so sage50.* imports work ─────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


# =============================================================================
# CONFIG — edit this block for future runs
# =============================================================================

BACKEND_URL = "http://localhost:8000"   # direct to FastAPI (no nginx redirect)
ADMIN_EMAIL = "admin@placeware.com"
ADMIN_PASS  = "pware1234"

# Company folder names inside the Sage Data 1 directory.
# Add a name here whenever a new company folder needs to be ingested.
COMPANIES: List[str] = [
    "planigli",
    "plaphaen",
]

# Sage Data 1 folder is auto-resolved as: <this file>/../Installer Files/Sage Data 1
# Override here only if the folder is in a different location.
SAGE_ROOT: Optional[str] = None   # None = auto-resolve

# =============================================================================
# END CONFIG
# =============================================================================


def _resolve_sage_root() -> str:
    """Return the absolute path to the Sage Data 1 folder."""
    if SAGE_ROOT:
        return os.path.normpath(SAGE_ROOT)
    # data-assimilation/ is one level below the project root
    project_root = os.path.dirname(_HERE)
    path = os.path.normpath(os.path.join(project_root, "Installer Files", "Sage Data 1"))
    return path


def _get_token() -> str:
    """POST /token with admin credentials; return the JWT string."""
    try:
        import requests
    except ImportError:
        sys.exit("ERROR: 'requests' not installed.  Run: pip install requests")

    try:
        resp = requests.post(
            f"{BACKEND_URL}/token",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASS},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:
        sys.exit(f"ERROR: Could not fetch token from {BACKEND_URL}\n  {exc}")


def _extract_datasets(
    company: str,
    sage_root: str,
    dry_run: bool,
) -> Dict[str, List[Dict[str, Any]]]:
    """Read all available entities for one company. Returns {entity: [mapped_rows]}."""
    from sage50.hard_reader import read_entity, field_names, available_entities
    import field_maps

    datasets: Dict[str, List[Dict[str, Any]]] = {}

    for entity in available_entities():
        raw_rows = read_entity(
            entity, sage_root, company=company,
            max_rows=10 if dry_run else None,
        )
        if not raw_rows:
            continue

        avail = field_names(entity)
        mapped: List[Dict[str, Any]] = []
        for raw in raw_rows:
            row = field_maps.map_row(raw, entity, avail)
            if row:
                mapped.append(row)

        if mapped:
            datasets[entity] = mapped

    return datasets


def _upload(
    company: str,
    datasets: Dict[str, List[Dict[str, Any]]],
    token: str,
) -> Dict[str, Any]:
    """Upload datasets to the backend. Returns the API response dict."""
    from sage50.loader import upload_to_backend
    try:
        return upload_to_backend(datasets, BACKEND_URL, token)
    except Exception as exc:
        return {"status": "error", "error": str(exc), "total_rows_inserted": 0}


def _normalize_name(s: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation — for fuzzy name matching."""
    import re as _re
    return _re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _count_table_rows(table: str, where: str = "") -> int:
    """Return row count for a DB table via docker exec psql. Returns -1 on failure."""
    import subprocess
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += ";"
    try:
        result = subprocess.run(
            ["docker", "exec", "backend-db-1",
             "psql", "-U", "postgres", "-d", "synbot_demo", "-t", "-c", sql],
            capture_output=True, text=True, timeout=15,
        )
        return int(result.stdout.strip())
    except Exception:
        return -1


def _push_contacts_as_prospects(
    contacts: List[Dict[str, Any]],
    token: str,
    reimport: bool = False,
) -> int:
    """POST contacts to /crm/lead-finder/prospects/source → CRM Lead Finder page.

    Each contact becomes a prospect record with company_name + contact_phone.
    Sent in batches of 50 to respect any endpoint size limits.
    Idempotent: skips push if sage_import prospects already exist unless reimport=True.
    """
    try:
        import requests
    except ImportError:
        return 0
    if not contacts:
        return 0

    if not reimport:
        existing = _count_table_rows("crm_prospects", where="source='sage_import'")
        if existing >= int(len(contacts) * 0.8):
            print(f"  → Contacts already imported ({existing} rows in CRM). Use --reimport to overwrite.")
            return existing

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = f"{BACKEND_URL.rstrip('/')}/crm/lead-finder/prospects/source"
    total = 0
    batch_size = 50

    for start in range(0, len(contacts), batch_size):
        batch = contacts[start : start + batch_size]
        seed_companies = [
            {
                "company_name":  c.get("ContactName", ""),
                "contact_name":  c.get("ContactName", ""),
                "contact_phone": c.get("Phone", ""),
                "industry":      "pharma",
                "region":        "Nigeria",
                "fit_signals":   {},
            }
            for c in batch
            if c.get("ContactName")
        ]
        if not seed_companies:
            continue

        payload = {
            "source":         "sage_import",
            "industry":       "pharma",
            "region":         "Nigeria",
            "seed_companies": seed_companies,
        }
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
                verify=False,
            )
            if resp.status_code in (200, 201):
                total += resp.json().get("count", len(seed_companies))
            # Non-fatal — continue with remaining batches
        except Exception:
            pass

    return total


def _enrich_customers_with_contacts(
    customers: List[Dict[str, Any]],
    contacts: List[Dict[str, Any]],
    addresses: List[Dict[str, Any]],
    token: str,
) -> int:
    """Name-match contacts/addresses to customers and re-POST enriched records.

    Builds a phone lookup (ContactName → phone) and address lookup
    (CompanyName → {street, city}) then merges into matched customer records
    and upserts via /data/ingest/customers (which updates contact_details JSONB).
    """
    try:
        import requests
    except ImportError:
        return 0
    if not customers:
        return 0

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Build normalised lookup tables
    phone_map: Dict[str, str] = {
        _normalize_name(c["ContactName"]): c["Phone"]
        for c in contacts
        if c.get("ContactName") and c.get("Phone")
    }
    addr_map: Dict[str, Dict] = {
        _normalize_name(a["CompanyName"]): {
            "address": a.get("Street", ""),
            "city":    a.get("City", ""),
        }
        for a in addresses
        if a.get("CompanyName")
    }

    enriched = []
    for cust in customers:
        cid = cust.get("customer_id", "")
        if not cid:
            continue
        key = _normalize_name(cid)
        phone = phone_map.get(key, "")
        addr  = addr_map.get(key, {})
        if not phone and not addr:
            continue

        contact_details: Dict[str, Any] = {}
        if phone:
            contact_details["phone"]   = phone
        if addr.get("address"):
            contact_details["address"] = addr["address"]
        if addr.get("city"):
            contact_details["city"]    = addr["city"]

        enriched.append({
            "customer_id":     cid,
            "name":            cust.get("name") or cid,
            "email":           cust.get("email") or None,
            "phone":           phone or cust.get("phone") or None,
            "status":          cust.get("status") or "active",
            "segment":         "pharmacy",
            "contact_details": contact_details,
        })

    if not enriched:
        return 0

    resp = requests.post(
        f"{BACKEND_URL.rstrip('/')}/data/ingest/customers",
        json={"customers": enriched},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
        verify=False,
    )
    resp.raise_for_status()
    return len(enriched)


def _push_customers_to_crm(
    customers: List[Dict[str, Any]],
    token: str,
) -> int:
    """POST customer data to /data/ingest/customers to populate the live CRM table.

    /sage/import/batch only writes to sage_customers_snapshot; the frontend CRM
    dashboard reads from the live `customers` table which is only populated here.
    """
    try:
        import requests
    except ImportError:
        return 0

    records = [
        {
            "customer_id": r.get("customer_id", ""),
            # Sage 50 often stores company name only in customer_id; fall back if name is blank
            "name":        r.get("name") or r.get("customer_id", ""),
            "email":       r.get("email") or None,
            "phone":       r.get("phone") or None,
            "status":      r.get("status") or "active",
            "segment":     "pharmacy",
        }
        for r in customers
        if r.get("customer_id")
    ]
    if not records:
        return 0

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    resp = requests.post(
        f"{BACKEND_URL.rstrip('/')}/data/ingest/customers",
        json={"customers": records},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
        verify=False,
    )
    resp.raise_for_status()
    return len(records)


def _synthesize_stock_on_hand(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive sage_inventory_snapshot records from items catalogue.

    Sage binary extraction gives us item definitions (item_id, name, cost)
    but not live stock counts. We seed quantity_on_hand=0 so the inventory
    page shows the SKU list; actual counts can be updated via inventory events.
    """
    return [
        {
            "item_id":          row.get("item_id", ""),
            "quantity_on_hand": 0,
            "unit_cost":        row.get("cost_price") or row.get("unit_cost") or 0,
            "reorder_level":    row.get("reorder_level") or 0,
        }
        for row in items
        if row.get("item_id")
    ]


def _print_company_result(
    company: str,
    datasets: Dict[str, List[Dict[str, Any]]],
    api_result: Optional[Dict[str, Any]],
) -> int:
    """Print per-entity results for one company. Returns total rows inserted."""
    print(f"\n=== {company} ===")

    if api_result is None:
        # dry-run mode
        total = 0
        for entity, rows in sorted(datasets.items()):
            print(f"  {entity:<30} {len(rows):>6} rows   [dry run]")
            total += len(rows)
        return total

    status = api_result.get("status", "unknown")
    total = api_result.get("total_rows_inserted", 0)

    ds_map: Dict[str, Any] = {}
    for ds in api_result.get("datasets", []):
        ft = ds.get("file_type") or ds.get("file", "?")
        ds_map[ft] = ds

    for entity, rows in sorted(datasets.items()):
        ds_info = ds_map.get(entity, {})
        inserted = ds_info.get("rows_inserted", 0)
        st = ds_info.get("status", "?")
        err = ds_info.get("insert_error", "")
        err_str = f"  ERR: {err[:60]}" if err else ""
        print(f"  {entity:<30} {str(inserted):>6} rows   [{st}]{err_str}")

    if status not in ("succeeded", "partial_success"):
        err = api_result.get("error", "")
        if err:
            print(f"  Upload error: {err[:100]}")

    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Placeware Sage 50 → Synbot data assimilation (one-command runner)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show row counts per entity without writing to the database.",
    )
    parser.add_argument(
        "--reimport", action="store_true",
        help="Force re-import of contacts even if already present in CRM Lead Finder.",
    )
    args = parser.parse_args()

    t0 = time.time()

    # ── Resolve paths ─────────────────────────────────────────────────────────
    sage_root = _resolve_sage_root()
    print(f"Sage root : {sage_root}")
    if not os.path.isdir(sage_root):
        sys.exit(
            f"\nERROR: Sage folder not found at:\n  {sage_root}\n\n"
            "Set SAGE_ROOT at the top of assimilate.py to override."
        )
    print(f"  [OK] folder exists")
    print(f"Backend   : {BACKEND_URL}")
    print(f"Companies : {', '.join(COMPANIES)}")

    # ── Auth ──────────────────────────────────────────────────────────────────
    token = ""
    if not args.dry_run:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("\nFetching auth token ...", end=" ", flush=True)
        token = _get_token()
        print("OK")

    # ── Ingest each company ───────────────────────────────────────────────────
    grand_total = 0

    for company in COMPANIES:
        datasets = _extract_datasets(company, sage_root, args.dry_run)
        if not datasets:
            print(f"\n=== {company} ===")
            print("  (no data extracted — check company folder name)")
            continue

        if args.dry_run:
            rows = _print_company_result(company, datasets, api_result=None)
            grand_total += rows
        else:
            # Synthesise stock_on_hand from items so sage_inventory_snapshot is populated
            if "items" in datasets and "stock_on_hand" not in datasets:
                soh = _synthesize_stock_on_hand(datasets["items"])
                if soh:
                    datasets["stock_on_hand"] = soh

            api_result = _upload(company, datasets, token)
            rows = _print_company_result(company, datasets, api_result)
            grand_total += rows

            if "customers" in datasets:
                try:
                    promoted = _push_customers_to_crm(datasets["customers"], token)
                    print(f"  → Promoted {promoted} customers to live CRM table")
                except Exception as exc:
                    print(f"  → CRM promotion failed: {str(exc)[:80]}")

            from sage50.hard_reader import read_contacts, read_addresses
            contacts  = read_contacts(sage_root, company=company)
            addresses = read_addresses(sage_root, company=company)

            if contacts:
                try:
                    n = _push_contacts_as_prospects(contacts, token, reimport=args.reimport)
                    print(f"  → Sourced {n} contacts to CRM Lead Finder")
                except Exception as exc:
                    print(f"  → Contacts push failed: {str(exc)[:80]}")

            if contacts or addresses:
                try:
                    n = _enrich_customers_with_contacts(
                        datasets.get("customers", []), contacts, addresses, token
                    )
                    if n:
                        print(f"  → Enriched {n} customers with phone/address data")
                except Exception as exc:
                    print(f"  → Enrichment failed: {str(exc)[:80]}")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = round(time.time() - t0, 1)
    mode = "[DRY RUN — nothing written]" if args.dry_run else "[LIVE — data written to Synbot]"
    print(f"\n{'─'*50}")
    print(f"  TOTAL   {grand_total:>6} rows across {len(COMPANIES)} companies")
    print(f"  Time    {elapsed}s")
    print(f"  Mode    {mode}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
