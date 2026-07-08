"""exception_manager.py — Exception Queue for the ACE pipeline.

Part of the ACE Data Engineering Pipeline (see docs.md/ACE-Data-Blueprint.md).

Every quality failure produces a managed exception rather than a silent drop.
Exceptions are persisted to exceptions.jsonl (append-only) for steward review.

Severity levels (from ACE blueprint §5.4):
  RECOVERABLE   — minor format issue, missing optional field.  Pipeline continues.
  DATA_QUALITY  — invalid format, duplicate key, missing required field.
                  Record quarantined; notify data steward.
  CRITICAL      — broken parent reference, corrupted source data.
                  Halt entity batch; require engineering review.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import quality_engine  # for QualityResult type

_HERE       = os.path.dirname(os.path.abspath(__file__))
_LOG_FILE   = os.path.join(_HERE, "exceptions.jsonl")


def log(
    batch_id: str,
    company:  str,
    entity:   str,
    result:   "quality_engine.QualityResult",
) -> None:
    """Append one exception to the log file."""
    entry = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "batch_id":   batch_id,
        "company":    company,
        "entity":     entity,
        **result.as_dict(),
    }
    with open(_LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def log_many(
    batch_id:  str,
    company:   str,
    entity:    str,
    results:   List["quality_engine.QualityResult"],
) -> None:
    """Append multiple exceptions in one call."""
    if not results:
        return
    with open(_LOG_FILE, "a", encoding="utf-8") as fh:
        for result in results:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "batch_id":  batch_id,
                "company":   company,
                "entity":    entity,
                **result.as_dict(),
            }
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def has_critical(results: List["quality_engine.QualityResult"]) -> bool:
    """Return True if any exception in *results* is CRITICAL severity."""
    return any(r.severity == "CRITICAL" for r in results)


def count_by_severity(results: List["quality_engine.QualityResult"]) -> Dict[str, int]:
    """Return {severity: count} for a list of QualityResult objects."""
    counts: Dict[str, int] = {}
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1
    return counts


def read_exceptions(batch_id: str | None = None) -> List[Dict[str, Any]]:
    """Read all exceptions from the log, optionally filtered by batch_id."""
    if not os.path.exists(_LOG_FILE):
        return []
    entries: List[Dict[str, Any]] = []
    with open(_LOG_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if batch_id is None or entry.get("batch_id") == batch_id:
                entries.append(entry)
    return entries
