"""inventory_workspace.py — grouped-card inventory workspace queries.

Backs the new Inventory Workspace (Phase 2/3 of the inventory upgrade):
grouped stock cards, per-family detail, all-time top sellers, and
per-SKU top-customer lookups. Follows this codebase's established
convention for aggregations sage_invoice_lines_snapshot's small (~22k row)
table size doesn't need SQL GROUP BY for — fetch matching rows via
TableQuery, aggregate in Python — the exact pattern crm_360.py's
`top_items` already uses for the same table.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from typing import Any as DBClient

from ..db import db
from .inventory import classify_stock_status

logger = logging.getLogger("inventory_workspace")

# sage_invoice_lines_snapshot rows for crm_360.py's synthetic "top purchased
# items" aggregation carry invoice_id = "SOLD_<customer_code>" -- no date,
# lifetime totals only. See data_intel/soft_relationships.py's
# sold_items_to_customer edge for the canonical convention this mirrors.
_SOLD_PREFIX = "SOLD_"


def _family_key(name: str) -> str:
    """Strip a trailing '(variant)' qualifier so batch/variant-suffixed SKUs
    of the same vaccine group under one card, e.g. 'VERORAB (A)' and
    'VERORAB (H)' both become 'VERORAB'. A name with no parenthetical is
    unchanged (groups with itself only)."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip() or (name or "")


def compute_suggested_reorder_qty(current_stock: float, reorder_level: float | None) -> float:
    """One canonical reorder-quantity formula: bring stock up to 2x the
    effective reorder threshold. Supersedes the two previously-existing,
    inconsistent, currently-dormant heuristics in workflow/automation.py and
    inventory_agent.py."""
    threshold = reorder_level if reorder_level and reorder_level > 0 else 10
    suggested = threshold * 2 - current_stock
    if suggested <= 0:
        return 0.0
    return max(suggested, 1.0)


def get_workspace_cards(
    company_id: Optional[str] = None, search: Optional[str] = None, client: DBClient = db
) -> List[Dict[str, Any]]:
    """Grouped, live-stock-only cards for the workspace's main grid.

    current_stock > 0 filtering happens BEFORE grouping, so a family whose
    every member is at zero simply produces no card at all -- not a card
    showing zero.
    """
    q = client.table("v_inventory").select(
        "sku,name,category,current_stock,reorder_level,cost_price,expiry_date,company_id"
    ).gt("current_stock", 0)
    if company_id:
        q = q.eq("company_id", company_id)
    rows = q.limit(5000).execute().data or []

    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.get("name") or "").lower() or s in (r.get("sku") or "").lower()]

    groups: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        family = _family_key(r.get("name") or r.get("sku") or "")
        key = (r.get("company_id"), family)
        g = groups.setdefault(key, {
            "family": family,
            "company_id": r.get("company_id"),
            "category": r.get("category"),
            "sku_count": 0,
            "total_stock": 0.0,
            "valuation": 0.0,
            "nearest_expiry_date": None,
            "worst_status": "adequate",
            "members": [],
        })
        qty = float(r.get("current_stock") or 0)
        cost = float(r.get("cost_price") or 0)
        status = classify_stock_status(qty, r.get("reorder_level"))
        g["sku_count"] += 1
        g["total_stock"] += qty
        g["valuation"] += qty * cost
        g["members"].append(r.get("sku"))
        exp = r.get("expiry_date")
        if exp and (g["nearest_expiry_date"] is None or str(exp) < str(g["nearest_expiry_date"])):
            g["nearest_expiry_date"] = exp
        # worst-case status across members: out_of_stock can't occur here
        # (current_stock>0 filter already applied), so severity order is
        # critical > warning > adequate.
        severity = {"critical": 2, "warning": 1, "adequate": 0}
        if severity.get(status, 0) > severity.get(g["worst_status"], 0):
            g["worst_status"] = status

    cards = []
    for g in groups.values():
        g["valuation"] = round(g["valuation"], 2)
        g["status"] = g.pop("worst_status")
        g["suggested_reorder_qty"] = (
            compute_suggested_reorder_qty(g["total_stock"], None) if g["status"] in ("critical", "warning") else 0.0
        )
        cards.append(g)

    cards.sort(key=lambda c: ({"critical": 0, "warning": 1, "adequate": 2}.get(c["status"], 3), c["family"]))
    return cards


def get_family_detail(
    company_id: Optional[str], family: str, client: DBClient = db
) -> Dict[str, Any]:
    """Full member/batch breakdown for one family, including zero-stock
    members (the card hides an all-zero family entirely, but the detail
    view is honest about mixed in-stock/out-of-stock state)."""
    q = client.table("v_inventory").select(
        "sku,name,category,unit,current_stock,reorder_level,cost_price,selling_price,expiry_date,batch_number,company_id"
    )
    if company_id:
        q = q.eq("company_id", company_id)
    rows = q.limit(5000).execute().data or []
    members = [r for r in rows if _family_key(r.get("name") or r.get("sku") or "") == family]
    for r in members:
        qty = float(r.get("current_stock") or 0)
        r["stock_status"] = classify_stock_status(qty, r.get("reorder_level"))
        r["suggested_reorder_qty"] = compute_suggested_reorder_qty(qty, r.get("reorder_level"))

    member_skus = [m["sku"] for m in members if m.get("sku")]

    open_requests: List[Dict[str, Any]] = []
    if member_skus:
        try:
            open_requests = (
                client.table("replenishment_requests")
                .select("id,sku,requested_qty,status,created_at,po_id")
                .in_("sku", member_skus)
                .neq("status", "received")
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning(f"open_replenishment_requests lookup failed (non-fatal): {e}")

    top_customers = get_top_customers_for_sku(member_skus, limit=8, client=client) if member_skus else []

    recent_movements: List[Dict[str, Any]] = []
    if member_skus:
        try:
            from .inventory import get_recent_inventory_movements
            all_recent = get_recent_inventory_movements(limit=100, client=client)
            recent_movements = [m for m in all_recent if m.get("sku") in member_skus][:20]
        except Exception as e:
            logger.warning(f"recent_movements lookup failed (non-fatal): {e}")

    return {
        "family": family,
        "company_id": company_id,
        "members": members,
        "open_replenishment_requests": open_requests,
        "top_customers": top_customers,
        "recent_movements": recent_movements,
    }


def get_top_selling_items(limit: int = 10, company_id: Optional[str] = None, client: DBClient = db) -> List[Dict[str, Any]]:
    """All-time top movers from the lifetime SOLD_<customer> aggregate rows.

    Labeled "Top Sellers -- All-Time" in the UI deliberately, not "recently
    popular" -- sage_invoice_lines_snapshot carries no date column at all,
    so there is no real recency signal to build on.
    """
    try:
        rows = (
            client.table("sage_invoice_lines_snapshot")
            .select("item_id,quantity,line_total,gross_profit")
            .like("invoice_id", f"{_SOLD_PREFIX}%")
            .limit(30000)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"get_top_selling_items query failed: {e}")
        return []

    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        item_id = str(r.get("item_id") or "").strip()
        if not item_id:
            continue
        a = agg.setdefault(item_id, {"sku": item_id, "total_qty": 0.0, "total_revenue": 0.0, "total_gross_profit": 0.0})
        a["total_qty"] += float(r.get("quantity") or 0)
        a["total_revenue"] += float(r.get("line_total") or 0)
        a["total_gross_profit"] += float(r.get("gross_profit") or 0)

    top = sorted(agg.values(), key=lambda x: x["total_qty"], reverse=True)[:limit]

    # Enrich with name/current_stock/company_id from v_inventory.
    if top:
        skus = [t["sku"] for t in top]
        try:
            inv_q = client.table("v_inventory").select("sku,name,current_stock,company_id")
            if company_id:
                inv_q = inv_q.eq("company_id", company_id)
            inv_rows = inv_q.in_("sku", skus).execute().data or []
            inv_by_sku = {r["sku"]: r for r in inv_rows}
            if company_id:
                top = [t for t in top if t["sku"] in inv_by_sku]
            for t in top:
                meta = inv_by_sku.get(t["sku"], {})
                t["name"] = meta.get("name") or t["sku"]
                t["current_stock"] = meta.get("current_stock")
                t["company_id"] = meta.get("company_id")
                t["total_qty"] = round(t["total_qty"], 2)
                t["total_revenue"] = round(t["total_revenue"], 2)
                t["total_gross_profit"] = round(t["total_gross_profit"], 2)
        except Exception as e:
            logger.warning(f"top-sellers v_inventory enrichment failed (non-fatal): {e}")

    return top


def get_top_customers_for_sku(member_skus: List[str], limit: int = 8, client: DBClient = db) -> List[Dict[str, Any]]:
    """Reverse direction of crm_360.py's top_items: for a given set of SKUs,
    who are the top customers by lifetime purchase amount. Reuses the exact
    REPLACE(invoice_id,'SOLD_','') convention codified in
    data_intel/soft_relationships.py's sold_items_to_customer edge."""
    if not member_skus:
        return []
    try:
        rows = (
            client.table("sage_invoice_lines_snapshot")
            .select("invoice_id,quantity,line_total")
            .in_("item_id", member_skus)
            .like("invoice_id", f"{_SOLD_PREFIX}%")
            .limit(10000)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"get_top_customers_for_sku query failed: {e}")
        return []

    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        invoice_id = r.get("invoice_id") or ""
        if not invoice_id.startswith(_SOLD_PREFIX):
            continue
        customer_code = invoice_id[len(_SOLD_PREFIX):]
        if not customer_code:
            continue
        a = agg.setdefault(customer_code, {"customer_code": customer_code, "quantity": 0.0, "amount": 0.0})
        a["quantity"] += float(r.get("quantity") or 0)
        a["amount"] += float(r.get("line_total") or 0)

    top = sorted(agg.values(), key=lambda x: x["amount"], reverse=True)[:limit]

    if top:
        codes = [t["customer_code"] for t in top]
        try:
            cust_rows = (
                client.table("customers")
                .select("customer_code,name")
                .in_("customer_code", codes)
                .execute()
                .data
                or []
            )
            name_by_code = {c["customer_code"]: c.get("name") for c in cust_rows}
            for t in top:
                t["customer_name"] = name_by_code.get(t["customer_code"], t["customer_code"])
                t["quantity"] = round(t["quantity"], 2)
                t["amount"] = round(t["amount"], 2)
        except Exception as e:
            logger.warning(f"top-customers-for-sku customer name enrichment failed (non-fatal): {e}")
            for t in top:
                t["customer_name"] = t["customer_code"]

    return top
