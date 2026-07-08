"""
One-shot: re-parse the Inventory folder (with the fixed Item Costing
enrichment) and upload ONLY the items + stock_on_hand entities.

Creates a fresh batch in sage_items_snapshot / sage_inventory_snapshot;
v_inventory reads the latest batch, so cost_price starts flowing to the
Finance Reports inventory tab without re-running the full ingestion.

Usage:  python upload_inventory_only.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest_sage_exports import (
    ingest_inventory,
    _get_token,
    _upload_batch,
    SAGE_EXPORTS_DIR,
    BACKEND_URL,
    ADMIN_EMAIL,
    ADMIN_PASS,
)


def main() -> None:
    folder = os.path.join(SAGE_EXPORTS_DIR, "Inventory")
    datasets: dict = {}
    print(f"Parsing inventory exports from: {folder}\n")
    ingest_inventory(folder, datasets)

    upload = {k: v for k, v in datasets.items() if k in ("items", "stock_on_hand")}
    if not upload:
        sys.exit("No items/stock_on_hand rows parsed — nothing to upload.")

    for entity, rows in upload.items():
        costed = sum(1 for r in rows if float(r.get("cost_price") or r.get("unit_cost") or 0) > 0)
        print(f"  {entity:<15} {len(rows):>5} rows ({costed} with cost)")

    print("\nFetching auth token ...", end=" ", flush=True)
    token = _get_token(BACKEND_URL, ADMIN_EMAIL, ADMIN_PASS)
    print("ok")

    print("Uploading ...", flush=True)
    result = _upload_batch(upload, BACKEND_URL, token)
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
