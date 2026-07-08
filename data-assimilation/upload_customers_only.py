"""
One-shot: re-parse the Account-Receivable folder (with the enriched Customer
Master mapping) and upload ONLY the customers entity.

Keeps only rows from the Customer Master file (identified by the presence of
the 'terms' key) so the fresh sage_customers_snapshot batch holds one enriched
row per customer instead of four partial rows from the supplemental files.

Usage:  python upload_customers_only.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest_sage_exports import (
    ingest_ar,
    _get_token,
    _upload_batch,
    SUBFOLDERS,
    BACKEND_URL,
    ADMIN_EMAIL,
    ADMIN_PASS,
)


def main() -> None:
    folder = SUBFOLDERS["Account Receivable"]
    datasets: dict = {}
    print(f"Parsing AR exports from: {folder}\n")
    ingest_ar(folder, datasets)

    all_cust = datasets.get("customers", [])
    master_rows = [r for r in all_cust if "terms" in r]
    seen: set = set()
    deduped = []
    for r in master_rows:
        cid = r.get("customer_id")
        if cid and cid not in seen:
            seen.add(cid)
            deduped.append(r)

    enriched = sum(1 for r in deduped if r.get("address") or r.get("city") or r.get("phone"))
    print(f"\ncustomers: {len(all_cust)} parsed total, {len(deduped)} master rows "
          f"({enriched} with contact/address data)")
    if not deduped:
        sys.exit("No master customer rows parsed — nothing to upload.")

    print("Fetching auth token ...", end=" ", flush=True)
    token = _get_token(BACKEND_URL, ADMIN_EMAIL, ADMIN_PASS)
    print("ok")

    print("Uploading ...", flush=True)
    result = _upload_batch({"customers": deduped}, BACKEND_URL, token)
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
