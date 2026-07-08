"""master_resolver.py — Master Data Resolution Layer for the ACE pipeline.

Stage 4 of the ACE Data Engineering Pipeline (see docs.md/ACE-Implementation-Guide.md).

Resolves text references in canonical records to governed Master Data identifiers
and validates cross-entity references within a batch.

At current scale, "master data" is the canonical batch context already processed
in Stages 1-3 (customers, items, vendors, COA). This provides:
  - Company ID validation against the Company Master
  - Account type vocabulary validation
  - Cross-entity consistency checks within the batch
  - A framework for future text-name → governed-ID resolution when transactional
    entities (invoices, purchase orders) arrive in Phase 2.

Resolution failures are classified as RECOVERABLE — records pass through but are
flagged for data steward review via the exception manager.

Returns (resolved_rows, unresolved_results) for every entity.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Company Master — authoritative list of ACE operating entities
# ---------------------------------------------------------------------------

_COMPANY_MASTER = {"planigli", "plaphaen"}


# ---------------------------------------------------------------------------
# Account type vocabulary — governed canonical values for COA
# ---------------------------------------------------------------------------

_VALID_ACCOUNT_TYPES = {
    "asset", "liability", "equity", "revenue", "expense",
    "cost_of_goods", "income", "other", "",
}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

class ResolutionResult:
    """Represents a single unresolved Master Data reference."""

    def __init__(
        self,
        row: Dict[str, Any],
        ref_field: str,
        ref_value: str,
        severity: str = "RECOVERABLE",
    ):
        self.row       = row
        self.ref_field = ref_field
        self.ref_value = ref_value
        self.severity  = severity  # RECOVERABLE | DATA_QUALITY | CRITICAL

    def as_quality_result_kwargs(self) -> Dict[str, Any]:
        """Return kwargs suitable for constructing a quality_engine.QualityResult."""
        return {
            "row":        self.row,
            "error_type": "UNRESOLVED_REFERENCE",
            "field":      self.ref_field,
            "severity":   self.severity,
        }


# ---------------------------------------------------------------------------
# Per-entity resolution rules
# ---------------------------------------------------------------------------

def _resolve_customers(
    rows: List[Dict],
    batch_context: Dict[str, List[Dict]],
) -> Tuple[List[Dict], List[ResolutionResult]]:
    unresolved: List[ResolutionResult] = []
    resolved: List[Dict] = []

    for row in rows:
        company_id = str(row.get("company_id") or "").strip().lower()
        if company_id and company_id not in _COMPANY_MASTER:
            unresolved.append(ResolutionResult(
                row, "company_id", company_id, "RECOVERABLE",
            ))
        resolved.append(row)  # always include (RECOVERABLE = pass through + flag)

    return resolved, unresolved


def _resolve_vendors(
    rows: List[Dict],
    batch_context: Dict[str, List[Dict]],
) -> Tuple[List[Dict], List[ResolutionResult]]:
    unresolved: List[ResolutionResult] = []
    resolved: List[Dict] = []

    for row in rows:
        company_id = str(row.get("company_id") or "").strip().lower()
        if company_id and company_id not in _COMPANY_MASTER:
            unresolved.append(ResolutionResult(
                row, "company_id", company_id, "RECOVERABLE",
            ))
        resolved.append(row)

    return resolved, unresolved


def _resolve_chart_of_accounts(
    rows: List[Dict],
    batch_context: Dict[str, List[Dict]],
) -> Tuple[List[Dict], List[ResolutionResult]]:
    unresolved: List[ResolutionResult] = []
    resolved: List[Dict] = []

    for row in rows:
        account_type = str(row.get("account_type") or "").strip().lower()
        company_id   = str(row.get("company_id")   or "").strip().lower()

        if account_type and account_type not in _VALID_ACCOUNT_TYPES:
            unresolved.append(ResolutionResult(
                row, "account_type", account_type, "RECOVERABLE",
            ))

        if company_id and company_id not in _COMPANY_MASTER:
            unresolved.append(ResolutionResult(
                row, "company_id", company_id, "RECOVERABLE",
            ))

        resolved.append(row)

    return resolved, unresolved


def _resolve_items(
    rows: List[Dict],
    batch_context: Dict[str, List[Dict]],
) -> Tuple[List[Dict], List[ResolutionResult]]:
    unresolved: List[ResolutionResult] = []
    resolved: List[Dict] = []

    for row in rows:
        company_id = str(row.get("company_id") or "").strip().lower()
        if company_id and company_id not in _COMPANY_MASTER:
            unresolved.append(ResolutionResult(
                row, "company_id", company_id, "RECOVERABLE",
            ))
        resolved.append(row)

    return resolved, unresolved


def _resolve_stock_on_hand(
    rows: List[Dict],
    batch_context: Dict[str, List[Dict]],
) -> Tuple[List[Dict], List[ResolutionResult]]:
    """Validate stock_on_hand item_id references against the items in this batch."""
    unresolved: List[ResolutionResult] = []
    resolved: List[Dict] = []

    # Build item_id lookup from batch context
    item_ids: set = set()
    for item_row in batch_context.get("items", []):
        iid = str(item_row.get("item_id") or "").strip()
        if iid:
            item_ids.add(iid)

    for row in rows:
        item_id    = str(row.get("item_id")    or "").strip()
        company_id = str(row.get("company_id") or "").strip().lower()

        if item_ids and item_id and item_id not in item_ids:
            # Item referenced in stock_on_hand not found in items batch
            unresolved.append(ResolutionResult(
                row, "item_id", item_id, "RECOVERABLE",
            ))

        if company_id and company_id not in _COMPANY_MASTER:
            unresolved.append(ResolutionResult(
                row, "company_id", company_id, "RECOVERABLE",
            ))

        resolved.append(row)

    return resolved, unresolved


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_RESOLVERS = {
    "customers":         _resolve_customers,
    "vendors":           _resolve_vendors,
    "chart_of_accounts": _resolve_chart_of_accounts,
    "items":             _resolve_items,
    "stock_on_hand":     _resolve_stock_on_hand,
}


def resolve(
    entity: str,
    canonical_rows: List[Dict[str, Any]],
    batch_context: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[ResolutionResult]]:
    """Perform Master Data Resolution on *canonical_rows* for *entity*.

    Args:
        entity:         Entity name (customers, vendors, items, etc.)
        canonical_rows: Output of canonical_mapper.transform() for this entity.
        batch_context:  Dict of entity → canonical rows processed so far in this
                        batch.  Used for cross-entity reference validation.

    Returns:
        (resolved_rows, unresolved_results)

        resolved_rows     — all rows (RECOVERABLE failures pass through)
        unresolved_results — ResolutionResult list for logging to exception_manager
    """
    if not canonical_rows:
        return [], []

    resolver = _RESOLVERS.get(entity)
    if resolver is None:
        # Unknown entity — pass through without resolution
        return canonical_rows, []

    return resolver(canonical_rows, batch_context)


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def resolution_summary(
    resolved: List,
    unresolved: List[ResolutionResult],
) -> str:
    """Return a one-line human-readable resolution summary."""
    total = len(resolved)
    if not unresolved:
        return f"{total} canonical → {total} resolved → 0 flagged"
    by_severity: Dict[str, int] = {}
    for r in unresolved:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
    sev_str = ", ".join(f"{k}:{v}" for k, v in by_severity.items())
    return (
        f"{total} canonical → {total} resolved → "
        f"{len(unresolved)} flagged ({sev_str})"
    )
