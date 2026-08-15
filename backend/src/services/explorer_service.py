"""explorer_service.py — Commercial Data Explorer.

Part of the ACE Data Intelligence Layer (see
data-assimilation/docs.md/ACE-Data-Intelligence-Layer.md Chapter 4).

Unified search + drill-down across the five Silver-view-backed master
entities (customers, vendors, items, GL accounts, invoices). This is ACE's
generalized answer to the "Context Engine" concept for vendors/items —
`crm_360.py`'s `customer_360` endpoint stays untouched (working, shipped);
this module does not clone its pattern, it generalizes the *concept* for
the entities Customer 360 doesn't cover.

**Deliberately Postgres-only in this phase**: the backend container has no
filesystem access to `data-assimilation/` (confirmed via `backend/Dockerfile`
— it copies only `app.py`/`src/`/`migrations/`/`scripts/`, never
`data-assimilation/`). So `original_source_record` (trace to the literal
Bronze JSON archive entry from the historical DAT migration) and
`exceptions` (cross-reference to `exceptions.jsonl`) are NOT populated here.
Bronze itself is still fully available for the live/ongoing import path —
`sage_*_snapshot` tables are natively append-only in Postgres, so
`bronze_history` below needs no filesystem access at all.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from src.db import get_psycopg_dsn
from src.data_intel import entity_field_maps as efm
from src.data_intel import soft_relationships
from src.services import lineage_service
from src.services.relationship_auditor_service import child_where_clause

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Unsafe identifier rejected: {name!r}")
    return name


def _connect():
    conn = psycopg2.connect(get_psycopg_dsn())
    # Autocommit — see lineage_service.py's _connect() for why: search() and
    # _related_counts() each run several independent read queries in a loop
    # over one shared connection/cursor, and a single failing query must not
    # abort the rest.
    conn.autocommit = True
    return conn


# ---------------------------------------------------------------------------
# Searchable entity registry
# ---------------------------------------------------------------------------

_SEARCHABLE: Dict[str, Dict[str, Any]] = {
    "customers": {
        "view": "v_customers", "key_col": "customer_id",
        "search_cols": ["customer_id", "name", "phone", "email"],
        "label_col": "name",
        "bronze_table": "sage_customers_snapshot", "bronze_key_col": "customer_id",
        "field_map_entity": "customers",
    },
    "vendors": {
        "view": "v_vendors", "key_col": "vendor_id",
        "search_cols": ["vendor_id", "vendor_name", "phone", "email"],
        "label_col": "vendor_name",
        "bronze_table": "sage_vendors_snapshot", "bronze_key_col": "vendor_id",
        "field_map_entity": "vendors",
    },
    "items": {
        "view": "v_inventory", "key_col": "sku",
        "search_cols": ["sku", "name"],
        "label_col": "name",
        "bronze_table": "sage_items_snapshot", "bronze_key_col": "item_id",
        "field_map_entity": "items",
    },
    "gl_accounts": {
        "view": "v_chart_of_accounts", "key_col": "account_code",
        "search_cols": ["account_code", "account_name"],
        "label_col": "account_name",
        "bronze_table": "sage_coa_snapshot", "bronze_key_col": "account_code",
        "field_map_entity": "chart_of_accounts",
    },
    "invoices": {
        "view": "v_ar_invoices", "key_col": "invoice_id",
        "search_cols": ["invoice_id", "customer_name"],
        "label_col": "invoice_id",
        "bronze_table": "sage_ar_snapshot", "bronze_key_col": "invoice_id",
        "field_map_entity": "sales_invoices",
    },
}

# Required fields for the quality badge, keyed by entity_type and expressed
# in terms of each SILVER VIEW's actual output column names — deliberately
# NOT the same as entity_field_maps.REQUIRED_FIELDS (which is correctly
# scoped to the raw snapshot-table column names, e.g. item_id/item_name/
# net_amount, and is used as-is by lineage_service.py's coverage matrix,
# which queries the raw target_table directly). The Silver views rename
# columns for display (item_id -> sku, item_name -> name, net_amount ->
# total_amount, etc. — see migrations 086/087), so re-using the raw-table
# REQUIRED_FIELDS against a canonical (view) row here would check for
# columns the view never returns and flag every record as broken.
_VIEW_REQUIRED_FIELDS: Dict[str, List[str]] = {
    "customers": ["customer_id", "name"],
    "vendors": ["vendor_id", "vendor_name"],
    "items": ["sku", "name"],
    "gl_accounts": ["account_code", "account_name"],
    "invoices": ["invoice_id", "customer_id", "total_amount"],
}

_ENTITY_RELATED_EDGES: Dict[str, List[str]] = {
    "customers": ["ar_invoice_to_customer", "sold_items_to_customer",
                  "customer_sales_to_customer", "placeware_invoices_to_customer"],
    "vendors": ["purchase_orders_to_vendor"],
    "items": ["invoice_lines_to_item", "inventory_to_item_catalog",
              "inventory_transactions_to_item"],
    "gl_accounts": ["gl_journal_to_coa", "gl_detail_to_coa", "gl_account_summary_to_coa"],
    "invoices": ["ar_invoice_lines_to_invoice"],
}


def known_entity_types() -> List[str]:
    return list(_SEARCHABLE.keys())


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _subtitle_for(entity_type: str, row: Dict[str, Any]) -> str:
    if entity_type in ("customers", "vendors"):
        return row.get("phone") or row.get("email") or ""
    if entity_type == "items":
        return row.get("category") or ""
    if entity_type == "gl_accounts":
        return row.get("account_type") or ""
    if entity_type == "invoices":
        parts = [row.get("customer_name") or "", str(row.get("total_amount") or "")]
        return " — ".join(p for p in parts if p)
    return ""


def search(query: str, limit_per_entity: int = 8) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    like_pattern = f"%{query}%"

    conn = _connect()
    results: List[Dict[str, Any]] = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        for entity_type, cfg in _SEARCHABLE.items():
            view = _safe_ident(cfg["view"])
            cols = [_safe_ident(c) for c in cfg["search_cols"]]
            where_sql = " OR ".join(f"{c}::text ILIKE %s" for c in cols)
            params = [like_pattern] * len(cols)
            try:
                cur.execute(
                    f"SELECT * FROM {view} WHERE {where_sql} LIMIT %s",
                    params + [limit_per_entity],
                )
                rows = cur.fetchall()
            except Exception:
                continue
            for row in rows:
                row = dict(row)
                results.append({
                    "entity_type": entity_type,
                    "key": row.get(cfg["key_col"]),
                    "label": row.get(cfg["label_col"]) or row.get(cfg["key_col"]),
                    "subtitle": _subtitle_for(entity_type, row),
                })
    finally:
        conn.close()
    return results


# ---------------------------------------------------------------------------
# Record drill-down
# ---------------------------------------------------------------------------

def _related_counts(cur, entity_type: str, key: str) -> List[Dict[str, Any]]:
    edge_names = _ENTITY_RELATED_EDGES.get(entity_type, [])
    out: List[Dict[str, Any]] = []
    for name in edge_names:
        rel = soft_relationships.get(name)
        if rel is None:
            continue
        child_table = _safe_ident(rel.child_table)
        ckey_expr = rel.child_key_expr or _safe_ident(rel.child_key)
        where_sql, params = child_where_clause(cur, rel)
        extra = f"({ckey_expr})::text = %s"
        where_sql = f"{where_sql} AND {extra}" if where_sql else f"WHERE {extra}"
        try:
            cur.execute(f"SELECT count(*) FROM {child_table} {where_sql}", params + [key])
            count = cur.fetchone()[0]
        except Exception:
            count = None
        out.append({
            "relationship": name,
            "description": rel.description,
            "required": rel.required,
            "count": count,
        })
    return out


def _quality_badge(
    entity_type: str,
    canonical: Optional[Dict[str, Any]],
    related: List[Dict[str, Any]],
) -> tuple[str, List[str]]:
    reasons: List[str] = []
    if canonical is None:
        return "red", ["Record not found in the Silver view."]

    required = _VIEW_REQUIRED_FIELDS.get(entity_type, [])
    for col in required:
        val = canonical.get(col)
        if val is None or (isinstance(val, str) and not val.strip()):
            reasons.append(f"Required field '{col}' is missing.")

    for edge in related:
        if edge["count"] == 0 and edge["required"]:
            # Zero related rows on a required edge is informational, not
            # necessarily bad (e.g. a brand-new customer has no invoices yet)
            # — only flag it if the edge count couldn't even be computed.
            continue
        if edge["count"] is None and edge["required"]:
            reasons.append(f"Could not verify relationship '{edge['relationship']}'.")

    if reasons:
        return ("red" if any("missing" in r for r in reasons) else "amber"), reasons
    return "green", reasons


def _developer_trace(field_map_entity: Optional[str], bronze_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not field_map_entity:
        return []
    all_entities = efm.all_entities()
    cfg = all_entities.get(field_map_entity)
    if not cfg:
        return []

    coverage = lineage_service.field_coverage_report()
    coverage_by_col: Dict[str, Optional[float]] = {}
    for section in ("dat_translated_entities", "csv_native_entities"):
        for entity_report in coverage[section]:
            if entity_report["entity"] == field_map_entity:
                for col in entity_report["columns"]:
                    coverage_by_col[col["ace_column"]] = col.get("coverage_pct")

    trace: List[Dict[str, Any]] = []
    for ace_col, candidates in cfg["fields"].items():
        value_history = [row.get(ace_col) for row in bronze_history if ace_col in row]
        trace.append({
            "ace_column": ace_col,
            "sage_column_candidates": candidates,
            "live_coverage_pct": coverage_by_col.get(ace_col),
            "value_history": value_history,
        })
    return trace


def get_record(entity_type: str, key: str) -> Dict[str, Any]:
    cfg = _SEARCHABLE.get(entity_type)
    if cfg is None:
        raise ValueError(f"Unknown entity_type: {entity_type!r}. Known: {known_entity_types()}")

    view = _safe_ident(cfg["view"])
    key_col = _safe_ident(cfg["key_col"])
    bronze_table = _safe_ident(cfg["bronze_table"])
    bronze_key_col = _safe_ident(cfg["bronze_key_col"])

    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(f"SELECT * FROM {view} WHERE {key_col}::text = %s LIMIT 1", [key])
        canonical_row = cur.fetchone()
        canonical = dict(canonical_row) if canonical_row else None

        cur.execute(
            f"SELECT * FROM {bronze_table} WHERE {bronze_key_col}::text = %s "
            f"ORDER BY imported_at DESC LIMIT 20",
            [key],
        )
        bronze_history = [dict(r) for r in cur.fetchall()]

        related = _related_counts(cur, entity_type, key)
    finally:
        conn.close()

    quality_badge, quality_reasons = _quality_badge(entity_type, canonical, related)
    developer_trace = _developer_trace(cfg["field_map_entity"], bronze_history)

    return {
        "entity_type": entity_type,
        "key": key,
        "found": canonical is not None,
        "canonical": canonical,
        "bronze_history": bronze_history,
        "related": related,
        "quality_badge": quality_badge,
        "quality_reasons": quality_reasons,
        "developer_trace": developer_trace,
        # Deliberately omitted this phase — no filesystem bridge to
        # data-assimilation/ from the backend container (see module docstring).
        "original_source_record": None,
        "exceptions": None,
    }
