"""relationship_auditor_service.py — Relationship / Orphan Auditor + Table Classification.

Part of the ACE Data Intelligence Layer (see
data-assimilation/docs.md/ACE-Data-Intelligence-Layer.md Chapter 3).

Two responsibilities:

1. **Relationship auditing** — real FK enumeration (`scan_information_schema`,
   expected to return few rows: most linkage in this schema is untyped text
   columns, not DB-enforced FKs) plus the actual soft-FK graph
   (`scan_soft_relationships`, driven by `data_intel.soft_relationships`),
   rolled up into a single `integrity_score()`.

2. **Table classification** — extends migration `086_silver_layer_views.sql`'s
   dead-table-detection method (grep `backend/src/routers/*.py` for zero
   references) into a live, scriptable report over the FULL public schema,
   sourced from `information_schema.tables` (not a static migrations-file
   grep, which over/undercounts due to `IF NOT EXISTS` redeclarations).
   **Report-only — this module never writes SQL or moves anything.** Any new
   `_archive` candidate must be reviewed by a human before a migration is
   written, exactly like the 11 tables migration 086 already archived.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from src.cache import ttl_cache
from src.db import get_psycopg_dsn
from src.data_intel import soft_relationships
from src.data_intel.soft_relationships import SoftRelationship

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_HERE = os.path.dirname(os.path.abspath(__file__))        # backend/src/services
_SRC_ROOT = os.path.dirname(_HERE)                          # backend/src
_BACKEND_ROOT = os.path.dirname(_SRC_ROOT)                  # backend
_ROUTERS_DIR = os.path.join(_SRC_ROOT, "routers")
_SERVICES_DIR = _HERE
_MIGRATIONS_DIR = os.path.join(_BACKEND_ROOT, "migrations")

_SELF_FILENAME = os.path.basename(__file__)

_HEALTHY_THRESHOLD = 95.0
_FAILED_THRESHOLD = 50.0


def _safe_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Unsafe identifier rejected: {name!r}")
    return name


def _connect():
    conn = psycopg2.connect(get_psycopg_dsn())
    # Autocommit — see lineage_service.py's _connect() for why: several
    # functions here (scan_soft_relationships, classify_tables's per-table
    # checks) run many independent read queries in a loop over one shared
    # connection/cursor, and a single failing query must not abort the rest.
    conn.autocommit = True
    return conn


def _latest_batch(cur, table: str) -> Optional[str]:
    try:
        cur.execute(
            f"SELECT batch_id FROM {_safe_ident(table)} "
            f"WHERE batch_id IS NOT NULL ORDER BY imported_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _status_for(coverage_pct: Optional[float]) -> str:
    if coverage_pct is None:
        return "NO_DATA"
    if coverage_pct >= _HEALTHY_THRESHOLD:
        return "HEALTHY"
    if coverage_pct >= _FAILED_THRESHOLD:
        return "REVIEW_REQUIRED"
    return "FAILED"


# ---------------------------------------------------------------------------
# 1. Real FK enumeration
# ---------------------------------------------------------------------------

def scan_information_schema() -> List[Dict[str, str]]:
    """Enumerate real, DB-enforced foreign keys in the public schema.

    Expected to return few rows — that's the schema's actual state, not a
    scan failure. Report it as-is."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                tc.table_name, kcu.column_name,
                ccu.table_name  AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            ORDER BY tc.table_name, kcu.column_name
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "table": r[0],
            "column": r[1],
            "references_table": r[2],
            "references_column": r[3],
            "constraint_name": r[4],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 2. Soft-relationship auditing
# ---------------------------------------------------------------------------

def child_where_clause(cur, rel: SoftRelationship, alias: Optional[str] = None) -> tuple[str, list]:
    """Public (no leading underscore deliberately — reused by explorer_service.py's
    per-record related-edge counts, so the batch/filter SQL assembly logic
    lives in exactly one place)."""
    prefix = f"{alias}." if alias else ""
    clauses: List[str] = []
    params: List[Any] = []
    if rel.child_has_batch_id:
        latest = _latest_batch(cur, rel.child_table)
        if latest is not None:
            clauses.append(f"{prefix}batch_id = %s")
            params.append(latest)
    if rel.child_filter_sql:
        clauses.append(rel.child_filter_sql)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


def _edge_stats(cur, rel: SoftRelationship) -> Dict[str, Any]:
    child_table = _safe_ident(rel.child_table)
    child_key = _safe_ident(rel.child_key)
    parent_view = _safe_ident(rel.parent_view)
    parent_key = _safe_ident(rel.parent_key)
    ckey_expr = rel.child_key_expr or child_key

    where_sql, params = child_where_clause(cur, rel)
    sql = f"""
        WITH child AS (
            SELECT ({ckey_expr}) AS ckey
            FROM {child_table}
            {where_sql}
        )
        SELECT
            count(*) AS total_rows,
            count(*) FILTER (WHERE ckey IS NULL OR ckey::text = '') AS null_or_blank,
            count(*) FILTER (
                WHERE ckey IS NOT NULL AND ckey::text <> '' AND p.{parent_key} IS NOT NULL
            ) AS matched,
            count(*) FILTER (
                WHERE ckey IS NOT NULL AND ckey::text <> '' AND p.{parent_key} IS NULL
            ) AS orphan
        FROM child c
        LEFT JOIN {parent_view} p ON p.{parent_key}::text = c.ckey::text
    """
    try:
        cur.execute(sql, params)
        total, null_blank, matched, orphan = cur.fetchone()
    except Exception as exc:
        return {
            "name": rel.name, "description": rel.description,
            "child_table": rel.child_table, "child_key": rel.child_key,
            "parent_view": rel.parent_view, "parent_key": rel.parent_key,
            "required": rel.required, "notes": rel.notes,
            "total_rows": 0, "null_or_blank": 0, "matched": 0, "orphan": 0,
            "coverage_pct": None, "status": "ERROR", "error": str(exc),
        }

    non_null = matched + orphan
    coverage_pct = round(100.0 * matched / non_null, 1) if non_null else None
    return {
        "name": rel.name,
        "description": rel.description,
        "child_table": rel.child_table,
        "child_key": rel.child_key,
        "parent_view": rel.parent_view,
        "parent_key": rel.parent_key,
        "required": rel.required,
        "notes": rel.notes,
        "total_rows": total,
        "null_or_blank": null_blank,
        "matched": matched,
        "orphan": orphan,
        "coverage_pct": coverage_pct,
        "status": _status_for(coverage_pct),
    }


@ttl_cache(ttl_seconds=300, tags=("data_intel", "relationships"))
def scan_soft_relationships() -> Dict[str, Any]:
    conn = _connect()
    try:
        cur = conn.cursor()
        edges = [_edge_stats(cur, rel) for rel in soft_relationships.RELATIONSHIPS]
    finally:
        conn.close()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "relationships": edges,
    }


def sample_orphans(name: str, limit: int = 50) -> Dict[str, Any]:
    rel = soft_relationships.get(name)
    if rel is None:
        raise ValueError(f"Unknown relationship: {name!r}")

    child_table = _safe_ident(rel.child_table)
    parent_view = _safe_ident(rel.parent_view)
    parent_key = _safe_ident(rel.parent_key)
    ckey_expr = rel.child_key_expr or _safe_ident(rel.child_key)

    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where_sql, params = child_where_clause(cur, rel, alias="c")
        sql = f"""
            WITH child AS (
                SELECT c.*, ({ckey_expr}) AS _ckey
                FROM {child_table} c
                {where_sql}
            )
            SELECT child.*
            FROM child
            LEFT JOIN {parent_view} p ON p.{parent_key}::text = child._ckey::text
            WHERE child._ckey IS NOT NULL AND child._ckey::text <> '' AND p.{parent_key} IS NULL
            LIMIT %s
        """
        cur.execute(sql, params + [limit])
        rows = cur.fetchall()
    finally:
        conn.close()

    return {
        "relationship": name,
        "limit": limit,
        "count": len(rows),
        "orphans": [dict(r) for r in rows],
    }


@ttl_cache(ttl_seconds=300, tags=("data_intel", "relationships"))
def integrity_score() -> Dict[str, Any]:
    """Overall Integrity Score — row-count-weighted average across edges.

    Deliberately NOT batch_reporter.py's multiplicative Data Confidence
    Score. DCS multiplies sequential pipeline-stage pass rates over the
    SAME base (correct — each stage filters the prior stage's output).
    Relationship edges are PARALLEL/independent measurements over
    different bases; multiplying N of them would unfairly crush the score
    toward zero purely because more edges were added (10 edges at 95% each
    would multiply to ~60%, misrepresenting a genuinely healthy schema).
    """
    scan = scan_soft_relationships()
    weighted_sum = 0.0
    weight_total = 0
    per_edge: List[Dict[str, Any]] = []
    for e in scan["relationships"]:
        weight = (e.get("matched") or 0) + (e.get("orphan") or 0)
        if weight > 0 and e.get("coverage_pct") is not None:
            weighted_sum += e["coverage_pct"] * weight
            weight_total += weight
        per_edge.append({
            "name": e["name"],
            "coverage_pct": e.get("coverage_pct"),
            "weight": weight,
            "required": e["required"],
            "status": e.get("status"),
        })

    overall = round(weighted_sum / weight_total, 1) if weight_total else None
    status = _status_for(overall) if overall is not None else "NO_DATA"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": overall,
        "status": status,
        "formula": (
            "row-count-weighted average across independent/parallel relationship "
            "edges — NOT batch_reporter.py's multiplicative Data Confidence Score, "
            "which is correct only for sequential pipeline stages over the same base"
        ),
        "edges": per_edge,
    }


# ---------------------------------------------------------------------------
# 3. Table classification
# ---------------------------------------------------------------------------

def _grep_references(table: str) -> Dict[str, List[str]]:
    pattern = re.compile(r"\b" + re.escape(table) + r"\b")
    hits: Dict[str, List[str]] = {"routers": [], "services": [], "migrations": []}

    for label, dir_path in (("routers", _ROUTERS_DIR), ("services", _SERVICES_DIR)):
        if not os.path.isdir(dir_path):
            continue
        for root, _dirs, files in os.walk(dir_path):
            for fn in files:
                if not fn.endswith(".py") or fn == _SELF_FILENAME:
                    continue
                path = os.path.join(root, fn)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except OSError:
                    continue
                if pattern.search(text):
                    hits[label].append(os.path.relpath(path, _BACKEND_ROOT).replace("\\", "/"))

    if os.path.isdir(_MIGRATIONS_DIR):
        for fn in sorted(os.listdir(_MIGRATIONS_DIR)):
            if not fn.endswith(".sql"):
                continue
            path = os.path.join(_MIGRATIONS_DIR, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            if pattern.search(text):
                hits["migrations"].append(os.path.relpath(path, _BACKEND_ROOT).replace("\\", "/"))

    return hits


@ttl_cache(ttl_seconds=600, tags=("data_intel", "tables"))
def classify_tables() -> Dict[str, Any]:
    """Report-only classification: Core (referenced from Python) / Referenced
    (SQL-only, e.g. behind a Silver view) / Unused (zero references found
    anywhere). NEVER writes SQL or moves tables — a human reviews any new
    Unused candidate before a migration archives it, exactly like migration
    086's 11 already-archived tables."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        public_tables = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = '_archive' ORDER BY table_name"
        )
        archived_tables = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    results: List[Dict[str, Any]] = []
    for table in public_tables:
        refs = _grep_references(table)
        python_refs = refs["routers"] + refs["services"]
        if python_refs:
            classification = "Core"
        elif refs["migrations"]:
            classification = "Referenced"
        else:
            classification = "Unused"
        results.append({
            "table": table,
            "classification": classification,
            "router_refs": refs["routers"],
            "service_refs": refs["services"],
            "migration_only_refs": refs["migrations"] if not python_refs else [],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_public_tables": len(public_tables),
        "already_archived": archived_tables,
        "already_archived_count": len(archived_tables),
        "classification_counts": {
            "Core": sum(1 for r in results if r["classification"] == "Core"),
            "Referenced": sum(1 for r in results if r["classification"] == "Referenced"),
            "Unused": sum(1 for r in results if r["classification"] == "Unused"),
        },
        "unused_candidates": [r["table"] for r in results if r["classification"] == "Unused"],
        "tables": results,
        "method": (
            "Live information_schema.tables scan (not a static migrations-file grep, "
            "which over/undercounts due to IF NOT EXISTS redeclarations), cross-referenced "
            "against text search of backend/src/routers, backend/src/services, and "
            "backend/migrations. Classification is mechanically derived (Core = referenced "
            "from Python, Referenced = SQL-only e.g. behind a Silver view, Unused = zero "
            "references found) — a coarser 3-way split than a human curator would make, "
            "by design: this tool surfaces candidates, it does not decide for you."
        ),
    }
