"""lineage_service.py — Data Lineage Engine / Field Coverage Matrix.

Part of the ACE Data Intelligence Layer (see
data-assimilation/docs.md/ACE-Data-Intelligence-Layer.md Chapter 2).

Reports, per entity, how well each ACE canonical column is actually
populated in the live database — a direct translation of the RoyanHealth
"Data Lineage Engine" / "Coverage Calculator" concept
(backend/docs/Latestmods-TB/Nl-Data-mod/Data Engine/data-engine2.md) onto
ACE's commercial schema.

Important scoping note: the "Sage Column" shown per field is the *candidate
list* from entity_field_maps.py, not a confirmed single winner — which
literal DAT/CSV column fed a given live value isn't persisted anywhere
today (not in Bronze, not in exceptions.jsonl). True column-level
provenance per row is a future-phase item (would need
`canonical_mapper.transform()` to write a `resolved_columns` sidecar).
What IS computed here, live, is whether the ACE column itself is populated.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2

from src.cache import ttl_cache
from src.db import get_psycopg_dsn
from src.data_intel import entity_field_maps as efm

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    """Defensive check — every identifier here comes from our own static
    config, never user input, but we validate anyway before f-string SQL."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"Unsafe identifier rejected: {name!r}")
    return name


def _connect():
    conn = psycopg2.connect(get_psycopg_dsn())
    # Autocommit — every function here runs many independent read queries in
    # a loop over one shared connection/cursor (one per entity/column). Without
    # autocommit, a single query failing (e.g. a column-name mismatch between
    # field_maps.py's ACE-column names and the live table — a real one exists:
    # sage_ar_snapshot has `date`/`amount`, not field_maps.py's `invoice_date`/
    # `net_amount`) leaves the connection in an aborted-transaction state,
    # silently failing every SUBSEQUENT query too, not just the bad one.
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


def _column_coverage(cur, table: str, column: str, batch_id: Optional[str]) -> Dict[str, Any]:
    table = _safe_ident(table)
    column = _safe_ident(column)
    where = ""
    params: tuple = ()
    if batch_id is not None:
        where = "WHERE batch_id = %s"
        params = (batch_id,)
    try:
        cur.execute(
            f"SELECT count(*) AS total, "
            f"count(*) FILTER (WHERE {column} IS NOT NULL AND {column}::text <> '') AS populated "
            f"FROM {table} {where}",
            params,
        )
        total, populated = cur.fetchone()
    except Exception as exc:
        return {"total": 0, "populated": 0, "coverage_pct": None, "error": str(exc)}
    if not total:
        return {"total": 0, "populated": 0, "coverage_pct": None}
    return {
        "total": total,
        "populated": populated,
        "coverage_pct": round(100.0 * populated / total, 1),
    }


def _entity_report(cur, entity: str, cfg: Dict) -> Dict[str, Any]:
    table = cfg["target_table"]
    batch_id = _latest_batch(cur, table)
    columns_report: List[Dict[str, Any]] = []
    for ace_col, candidates in cfg["fields"].items():
        try:
            cov = _column_coverage(cur, table, ace_col, batch_id)
        except ValueError as exc:
            cov = {"total": 0, "populated": 0, "coverage_pct": None, "error": str(exc)}
        columns_report.append({
            "ace_column": ace_col,
            "sage_column_candidates": candidates,
            **cov,
        })
    return {
        "entity": entity,
        "target_table": table,
        "silver_view": cfg.get("silver_view"),
        "batch_id": batch_id,
        "source_note": cfg.get("source_note"),
        "columns": columns_report,
    }


@ttl_cache(ttl_seconds=300, tags=("data_intel", "coverage"))
def field_coverage_report() -> Dict[str, Any]:
    """Full coverage matrix: DAT-translated entities and CSV-native entities
    reported in SEPARATE sections (blending them would misleadingly pad the
    coverage numbers — CSV-native columns are ~1:1 passthrough, not real
    translation). Cached 5 min — a diagnostic report, staleness is fine;
    the Explorer's live per-record lookups are NOT cached (see
    explorer_service.py)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        dat_entities = [
            _entity_report(cur, name, cfg)
            for name, cfg in efm.DAT_ENTITY_MAPS.items()
        ]
        csv_native_entities = [
            _entity_report(cur, name, cfg)
            for name, cfg in efm.CSV_NATIVE_ENTITY_MAPS.items()
        ]
    finally:
        conn.close()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dat_translated_entities": dat_entities,
        "csv_native_entities": csv_native_entities,
        "non_extractable_fields": NON_EXTRACTABLE_FIELDS,
    }


def missing_columns_report() -> List[Dict[str, Any]]:
    """Columns at 0% (or unmeasurable) coverage, priority-sorted — the
    RoyanHealth 'Missing Data Report' equivalent."""
    report = field_coverage_report()
    missing: List[Dict[str, Any]] = []
    for section, entities in (
        ("dat_translated", report["dat_translated_entities"]),
        ("csv_native", report["csv_native_entities"]),
    ):
        for entity_report in entities:
            for col in entity_report["columns"]:
                pct = col.get("coverage_pct")
                if pct is None or pct == 0.0:
                    missing.append({
                        "section": section,
                        "entity": entity_report["entity"],
                        "target_table": entity_report["target_table"],
                        "ace_column": col["ace_column"],
                        "sage_column_candidates": col["sage_column_candidates"],
                        "coverage_pct": pct,
                        "error": col.get("error"),
                    })
    # Priority: required fields first (matches REQUIRED_FIELDS), then alphabetical
    def _priority(item: Dict[str, Any]) -> tuple:
        required = efm.REQUIRED_FIELDS.get(item["entity"], [])
        is_required = item["ace_column"] in required
        return (0 if is_required else 1, item["entity"], item["ace_column"])

    missing.sort(key=_priority)
    return missing


# ---------------------------------------------------------------------------
# Non-extractable fields — tribal knowledge, turned into written record.
# Source: project history of the historical Sage 50 .DAT extraction effort.
# Not computable from live data — declared once here, rendered as-is.
# ---------------------------------------------------------------------------

NON_EXTRACTABLE_FIELDS: List[Dict[str, str]] = [
    {
        "source": "STXHDR.DAT / STXROW.DAT",
        "field_group": "Sales transactions",
        "status": "NOT_EXTRACTABLE",
        "reason": "Never entered in this Sage 50 dataset (no transaction history recorded at the POS/invoice level in these files).",
    },
    {
        "source": "JRNLHDR.DAT / INVCOST.DAT",
        "field_group": "GL / inventory cost detail (358 MB+)",
        "status": "NOT_EXTRACTABLE",
        "reason": "Non-LSTRING binary format — different record layout than the LSTRING-offset tables the current extractor understands.",
    },
    {
        "source": "UNITMEAS.DAT, TAXCODE.DAT, COST.DAT, BUDGET.DAT, BANKREC.DAT",
        "field_group": "Reference/config tables",
        "status": "NOT_EXTRACTABLE",
        "reason": "Small files but all non-LSTRING format.",
    },
    {
        "source": "EMPLOYEE.DAT, PROJECT.DAT",
        "field_group": "Staff / project reference data",
        "status": "EMPTY",
        "reason": "File structure exists but contains zero records in this company's Sage dataset.",
    },
    {
        "source": "CONTACTS.DAT, ADDRESS.DAT",
        "field_group": "Contact names, billing addresses",
        "status": "HAS_DATA_NOT_EXTRACTED",
        "reason": "Uses a non-standard UUID-prefixed record format (not the standard LSTRING-at-offset-22 layout other tables use) — extractor not yet written.",
    },
    {
        "source": "LINEITEM.DAT",
        "field_group": "expiry_date, batch_number",
        "status": "EXTRACTED",
        "reason": "Successfully extracted via scan_date/scan_lot_code read modes; populated into sage_items_snapshot.expiry_date / batch_number.",
    },
    {
        "source": "JRNLROW.DAT",
        "field_group": "GL journal entries (postings, descriptions)",
        "status": "PARTIALLY_EXTRACTED",
        "reason": "Extracted via Btrieve LVAR streaming into sage_gl_transactions (71,744 rows, 2014-2025). Debit/credit amounts and GL account codes are NOT extractable — fixed-length record pages not decoded.",
    },
]
