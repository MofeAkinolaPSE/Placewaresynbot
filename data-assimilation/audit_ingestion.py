"""
audit_ingestion.py — parse every sage-exports folder (read-only, no uploads)
and print entity row counts so they can be compared with the snapshot tables.

Usage:  python audit_ingestion.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest_sage_exports import (
    ingest_general_ledger,
    ingest_financial_statements,
    ingest_ar,
    ingest_inventory,
    ingest_reconciliation,
    ingest_ap,
    SUBFOLDERS,
)

ENTITY_TABLE = {
    "coa":                    "sage_coa_snapshot",
    "chart_of_accounts":      "sage_coa_snapshot",
    "vendors":                "sage_vendors_snapshot",
    "customers":              "sage_customers_snapshot",
    "items":                  "sage_items_snapshot",
    "stock_on_hand":          "sage_inventory_snapshot",
    "purchase_orders":        "sage_purchase_orders_snapshot",
    "sales_invoices":         "sage_ar_snapshot",
    "sales_invoice_lines":    "sage_invoice_lines_snapshot",
    "inventory_transactions": "sage_inv_transactions_snapshot",
    "gl_journal_entries":     "sage_gl_snapshot",
    "gl_detail":              "sage_gl_detail_snapshot",
    "cash_register":          "sage_cash_register_snapshot",
    "gl_account_summary":     "sage_gl_account_summary_snapshot",
}


def main() -> None:
    per_category: dict = {}

    def run(label, fn, *args):
        datasets: dict = {}
        print(f"\n=== {label} ===")
        fn(*args, datasets) if args else fn(SUBFOLDERS[label], datasets)
        per_category[label] = {k: len(v) for k, v in datasets.items()}

    run("General Ledger", ingest_general_ledger)
    run("Financial Statements", ingest_financial_statements)
    run("Account Receivable", ingest_ar)
    run("Inventory", ingest_inventory)
    recon_rows: list = []
    datasets_recon: dict = {}
    print("\n=== Account Reconciliation ===")
    ingest_reconciliation(SUBFOLDERS["Account Reconciliation"], recon_rows, datasets_recon)
    per_category["Account Reconciliation"] = {
        **{k: len(v) for k, v in datasets_recon.items()},
        "reconciliation_rows(http)": len(recon_rows),
    }
    run("Account Payable", ingest_ap)

    print("\n" + "=" * 72)
    print("PARSED ROW COUNTS PER CATEGORY / ENTITY")
    print("=" * 72)
    totals: dict = {}
    for cat, entities in per_category.items():
        print(f"\n{cat}:")
        for ent, n in sorted(entities.items()):
            table = ENTITY_TABLE.get(ent, "-")
            print(f"  {ent:<26} {n:>8}   → {table}")
            totals[ent] = totals.get(ent, 0) + n

    print("\n" + "=" * 72)
    print("TOTAL PARSED PER ENTITY (all categories combined)")
    print("=" * 72)
    for ent, n in sorted(totals.items()):
        print(f"  {ent:<26} {n:>8}   → {ENTITY_TABLE.get(ent, '-')}")


if __name__ == "__main__":
    main()
