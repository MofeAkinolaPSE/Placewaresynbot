"""
One-shot: parse the AR folder and upload ONLY the customer_sales entity
(per-customer profitability from "Customer sales History.xlsx") into the new
sage_customer_sales_snapshot table.

Usage:  python upload_customer_sales_only.py
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
    ingest_ar(folder, datasets)

    rows = datasets.get("customer_sales", [])
    print(f"\ncustomer_sales rows parsed: {len(rows)}")
    if not rows:
        sys.exit("Nothing to upload.")

    print("Fetching auth token ...", end=" ", flush=True)
    token = _get_token(BACKEND_URL, ADMIN_EMAIL, ADMIN_PASS)
    print("ok")
    result = _upload_batch({"customer_sales": rows}, BACKEND_URL, token)
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
