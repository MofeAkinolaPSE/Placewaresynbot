"""soft_relationships.py — declarative registry of "soft FK" edges.

Most linkage in this schema is via untyped text columns (`customer_id`,
`sku`, `account_code`, ...) rather than DB-enforced foreign keys — a live
`information_schema` FK scan (see relationship_auditor_service.py) will
return only a handful of rows. This registry is the actual relationship
graph, bootstrapped from joins already exercised in code: crm_360.py's
`.eq('customer_id', code)` calls, the Silver-view JOINs in migrations
086/087, and audit_ingestion.py's ENTITY_TABLE.

**The `sold_items_to_customer` gotcha**: `sage_invoice_lines_snapshot.invoice_id`
is overloaded. Real invoice lines carry a real invoice number (joins to
`v_ar_invoices.invoice_id`). But `crm_360.py` also writes a synthetic
`SOLD_<customer_code>` pseudo-invoice-id for its "top purchased items"
aggregation. These are deliberately modelled as two SEPARATE edges with
mutually-exclusive filters, so the synthetic convention never gets scored
as an orphan against the real-invoice edge (which would falsely read as
~100% orphaned otherwise).

Every edge prefers a Silver view (`v_customers`, `v_vendors`, `v_inventory`,
`v_chart_of_accounts`, `v_ar_invoices`) as the parent side when one exists —
those views already encapsulate the latest-batch `DISTINCT ON` dedup from
migrations 086/087. `child_has_batch_id=True` tells the auditor to restrict
the child side to its latest `batch_id` too (mirrors the Silver-view
convention for tables that don't have a dedicated view yet).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SoftRelationship:
    name: str
    description: str
    child_table: str
    child_key: str
    parent_view: str
    parent_key: str
    cardinality: str = "many_to_one"
    child_has_batch_id: bool = True
    # Optional raw SQL fragment appended to the child-side WHERE clause,
    # e.g. to exclude/include the SOLD_% synthetic-invoice convention.
    child_filter_sql: Optional[str] = None
    # Optional SQL expression transforming the child key before matching
    # (e.g. stripping the "SOLD_" prefix). Must reference `child_key` as a
    # bare column reference; applied as f"{expr}" in the SELECT/JOIN.
    child_key_expr: Optional[str] = None
    required: bool = True
    notes: str = ""


RELATIONSHIPS: list[SoftRelationship] = [

    SoftRelationship(
        name="ar_invoice_to_customer",
        description="AR invoice headers reference a customer",
        child_table="sage_ar_snapshot",
        child_key="customer_id",
        parent_view="v_customers",
        parent_key="customer_id",
    ),

    SoftRelationship(
        name="ar_invoice_lines_to_invoice",
        description="Real invoice lines reference a real AR invoice header",
        child_table="sage_invoice_lines_snapshot",
        child_key="invoice_id",
        parent_view="v_ar_invoices",
        parent_key="invoice_id",
        child_filter_sql="invoice_id NOT LIKE 'SOLD\\_%' ESCAPE '\\'",
        notes="Excludes the synthetic SOLD_<customer_code> aggregation rows — see sold_items_to_customer.",
    ),

    SoftRelationship(
        name="sold_items_to_customer",
        description="crm_360.py's synthetic 'top purchased items' rows reference a customer",
        child_table="sage_invoice_lines_snapshot",
        child_key="invoice_id",
        parent_view="v_customers",
        parent_key="customer_id",
        child_filter_sql="invoice_id LIKE 'SOLD\\_%' ESCAPE '\\'",
        child_key_expr="REPLACE(invoice_id, 'SOLD_', '')",
        required=False,
        notes="Synthetic convention from crm_360.py, not a real invoice. Modelled separately so it never pollutes ar_invoice_lines_to_invoice's orphan count.",
    ),

    SoftRelationship(
        name="invoice_lines_to_item",
        description="Invoice line items reference a product catalog SKU",
        child_table="sage_invoice_lines_snapshot",
        child_key="item_id",
        parent_view="v_inventory",
        parent_key="sku",
    ),

    SoftRelationship(
        name="inventory_to_item_catalog",
        description="Stock-on-hand rows reference a product catalog SKU",
        child_table="sage_inventory_snapshot",
        child_key="sku",
        parent_view="v_inventory",
        parent_key="sku",
    ),

    SoftRelationship(
        name="purchase_orders_to_vendor",
        description="Purchase orders reference a vendor",
        child_table="sage_purchase_orders_snapshot",
        child_key="vendor_id",
        parent_view="v_vendors",
        parent_key="vendor_id",
    ),

    SoftRelationship(
        name="inventory_transactions_to_item",
        description="Inventory transactions reference a product catalog SKU",
        child_table="sage_inv_transactions_snapshot",
        child_key="item_id",
        parent_view="v_inventory",
        parent_key="sku",
    ),

    SoftRelationship(
        name="gl_journal_to_coa",
        description="GL journal entries reference a chart-of-accounts code",
        child_table="sage_gl_snapshot",
        child_key="account_id",
        parent_view="v_chart_of_accounts",
        parent_key="account_code",
        required=False,
        notes="account_id candidates include free-text account numbers; lower confidence than other edges.",
    ),

    SoftRelationship(
        name="gl_detail_to_coa",
        description="GL detail rows (live CSV import) reference a chart-of-accounts code",
        child_table="sage_gl_detail_snapshot",
        child_key="account_code",
        parent_view="v_chart_of_accounts",
        parent_key="account_code",
    ),

    SoftRelationship(
        name="gl_account_summary_to_coa",
        description="GL account summary rows reference a chart-of-accounts code",
        child_table="sage_gl_account_summary_snapshot",
        child_key="account_code",
        parent_view="v_chart_of_accounts",
        parent_key="account_code",
    ),

    SoftRelationship(
        name="customer_sales_to_customer",
        description="Customer lifetime-sales summary rows reference a customer",
        child_table="sage_customer_sales_snapshot",
        child_key="customer_id",
        parent_view="v_customers",
        parent_key="customer_id",
    ),

    SoftRelationship(
        name="placeware_invoices_to_customer",
        description="ACE's branded invoice table references a customer",
        child_table="placeware_invoices",
        child_key="customer_id",
        parent_view="v_customers",
        parent_key="customer_id",
        child_has_batch_id=False,
        notes="placeware_invoices has no batch_id — it's continuously upserted by key, not append-only.",
    ),
]


def get(name: str) -> Optional[SoftRelationship]:
    return next((r for r in RELATIONSHIPS if r.name == name), None)
