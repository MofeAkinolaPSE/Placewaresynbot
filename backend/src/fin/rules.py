"""AccountingRuleService: business event -> which accounts.

Modules never hard-code account numbers. They ask for a *role*
(AR_CONTROL, DELIVERY_INCOME, ...) or a product's own accounts, and the
entity's configuration answers. This is how the client's rule "delivery
charges go to other income, discounts to their own head" (meeting 2) is
honoured without code changes when their chart evolves.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.fin.accounts import mapped_account, optional_mapped
from src.fin.db import q1
from src.fin.errors import FinError

# role -> (description, required?)  Used by Setup > Posting rules.
MAPPING_KEYS: Dict[str, str] = {
    "AR_CONTROL": "Accounts Receivable control (customer invoices)",
    "AP_CONTROL": "Accounts Payable control (supplier bills)",
    "SALES_DEFAULT": "Sales revenue when a product has no own revenue account",
    "SERVICE_INCOME": "Revenue for service / non-stock invoice lines",
    "DELIVERY_INCOME": "Delivery charges billed to customers (kept out of product sales)",
    "OTHER_CHARGE_INCOME": "Other charges billed on invoices",
    "SALES_DISCOUNT": "Discounts allowed on invoices",
    "SALES_RETURNS": "Sales returns & allowances (credit notes)",
    "INVENTORY_DEFAULT": "Inventory when a product has no own inventory account",
    "COGS_DEFAULT": "Cost of sales when a product has no own COGS account",
    "INVENTORY_ADJUSTMENT": "Stock write-offs / count differences",
    "STOCK_ON_LOAN": "Stock lent to customers (still ours, not in the warehouse)",
    "PURCHASE_EXPENSE_DEFAULT": "Default expense for non-stock supplier bill lines",
    "WHT_SUFFERED": "Withholding tax deducted by customers from their payments",
    "WHT_PAYABLE": "Withholding tax deducted from supplier payments (owed to FIRS)",
    "BANK_CHARGES": "Bank charges",
    "RETAINED_EARNINGS": "Retained earnings (year-end close target)",
    "OPENING_BALANCE_EQUITY": "Opening balance equity (migration suspense)",
    "ASSET_DISPOSAL": "Gain / loss on disposal of fixed assets",
    "OUTPUT_TAX": "Tax collected on sales (unset until tax rules are confirmed)",
    "INPUT_TAX": "Tax paid on purchases (unset until tax rules are confirmed)",
}


def account(conn, entity_id: str, key: str) -> Dict[str, Any]:
    if key not in MAPPING_KEYS:
        raise FinError("VALIDATION_FAILED", f"Unknown posting rule {key}")
    return mapped_account(conn, entity_id, key)


def optional(conn, entity_id: str, key: str) -> Optional[Dict[str, Any]]:
    return optional_mapped(conn, entity_id, key)


def product(conn, entity_id: str, sku: str) -> Dict[str, Any]:
    p = q1(conn, "SELECT * FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (entity_id, sku))
    if not p:
        raise FinError("RESOURCE_NOT_FOUND", f"Product {sku} is not in the product list",
                       {"sku": sku})
    return p


def product_accounts(conn, entity_id: str, sku: str) -> Dict[str, Any]:
    """Revenue / inventory / COGS accounts for a product, falling back to defaults."""
    p = product(conn, entity_id, sku)
    out = {"product": p}
    for field, key in (("revenue_account_id", "SALES_DEFAULT"), ("inventory_account_id", "INVENTORY_DEFAULT"),
                       ("cogs_account_id", "COGS_DEFAULT")):
        if p.get(field):
            out[field] = str(p[field])
        else:
            out[field] = str(account(conn, entity_id, key)["id"])
    return out
