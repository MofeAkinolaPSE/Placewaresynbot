"""canonical_mapper.py — Canonical Transformation Layer for the ACE pipeline.

Stage 3 of the ACE Data Engineering Pipeline (see docs.md/ACE-Data-Blueprint.md).

Wraps field_maps.map_row() and adds:
  1. Semantic normalisation (status flags, boolean coercion, string cleanup)
  2. Source metadata injection (source_system, source_batch, source_key, company_id)

The result is a canonical ACE business object ready for the Silver layer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Semantic normalisers
# ---------------------------------------------------------------------------

def _normalise_status(val: Any) -> str:
    """Map any truthy/falsy Sage status value to 'active' or 'inactive'."""
    if val is None:
        return "active"
    s = str(val).strip().upper()
    if s in ("Y", "YES", "1", "TRUE", "T", "ACTIVE", "A", ""):
        return "active"
    return "inactive"


def _normalise_str(val: Any) -> str:
    if val is None:
        return ""
    return " ".join(str(val).strip().split())  # collapse internal whitespace


_STATUS_FIELDS = {"status", "is_active", "active"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transform(
    entity: str,
    valid_rows: List[Dict[str, Any]],
    company: str,
    batch_id: str,
) -> List[Dict[str, Any]]:
    """Transform *valid_rows* into canonical ACE business objects.

    Calls field_maps.map_row() for structural mapping, then:
    - normalises status fields semantically,
    - injects canonical source metadata onto every row.

    Returns list of canonical dicts ready to POST to the Silver layer.
    """
    import field_maps
    from sage50.hard_reader import field_names

    avail = field_names(entity)
    results: List[Dict[str, Any]] = []

    for raw in valid_rows:
        # Structural + type mapping (existing logic)
        mapped: Optional[Dict[str, Any]] = field_maps.map_row(raw, entity, avail)
        if not mapped:
            continue

        # Semantic normalisation
        for key in list(mapped.keys()):
            if key in _STATUS_FIELDS:
                mapped[key] = _normalise_status(mapped[key])
            elif isinstance(mapped[key], str):
                mapped[key] = _normalise_str(mapped[key])

        # Source lineage metadata (canonical standard from ACE blueprint §3.6)
        source_key = _extract_source_key(entity, raw, mapped)
        mapped["source_system"] = "sage50"
        mapped["source_batch"]  = batch_id
        mapped["source_key"]    = source_key
        mapped["company_id"]    = company

        results.append(mapped)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_source_key(
    entity: str,
    raw: Dict[str, Any],
    mapped: Dict[str, Any],
) -> str:
    """Return the best available source primary key for lineage tracking."""
    candidates = {
        "customers":         ["customer_id", "CustId", "CustomerID", "AcctNo"],
        "vendors":           ["vendor_id", "VendorId", "ID", "AcctNo"],
        "chart_of_accounts": ["account_id", "AcctId", "GLCode"],
        "items":             ["item_id", "ItemId", "SKU"],
        "stock_on_hand":     ["item_id", "ItemId", "SKU"],
    }
    for candidate in candidates.get(entity, []):
        val = mapped.get(candidate) or raw.get(candidate)
        if val:
            return str(val).strip()
    return ""
