"""bronze_layer.py — Immutable raw-extract archive for the ACE pipeline.

Stage 1 of the ACE Data Engineering Pipeline (see docs.md/ACE-Data-Blueprint.md).

Preserves every Sage 50 extraction exactly as read — no transformations,
no cleansing — so any batch can be replayed or audited in the future.

Archive path structure:
    sage50/extracted/bronze/<company>/<batch_id>/<entity>.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_BRONZE_ROOT = os.path.join(_HERE, "sage50", "extracted", "bronze")


def save(
    batch_id: str,
    company: str,
    entity: str,
    raw_rows: List[Dict[str, Any]],
) -> str:
    """Persist *raw_rows* immutably to the Bronze archive.

    Returns the path of the written file.
    The file is written once; calling save() again with the same arguments
    overwrites only if the file doesn't already exist (idempotent replay).
    """
    dest_dir = os.path.join(_BRONZE_ROOT, company, batch_id)
    os.makedirs(dest_dir, exist_ok=True)

    dest_file = os.path.join(dest_dir, f"{entity}.json")

    if os.path.exists(dest_file):
        # Already archived in this batch — skip (idempotency)
        return dest_file

    payload = {
        "batch_id":           batch_id,
        "company":            company,
        "entity":             entity,
        "source_system":      "sage50",
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "row_count":          len(raw_rows),
        "rows":               raw_rows,
    }

    with open(dest_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str, indent=2)

    return dest_file


def list_batches(company: str | None = None) -> List[Dict[str, Any]]:
    """Return a summary of all archived batches, newest first."""
    results: List[Dict[str, Any]] = []

    companies = (
        [company]
        if company
        else (
            sorted(os.listdir(_BRONZE_ROOT))
            if os.path.isdir(_BRONZE_ROOT)
            else []
        )
    )

    for co in companies:
        co_dir = os.path.join(_BRONZE_ROOT, co)
        if not os.path.isdir(co_dir):
            continue
        for batch in sorted(os.listdir(co_dir), reverse=True):
            batch_dir = os.path.join(co_dir, batch)
            if not os.path.isdir(batch_dir):
                continue
            entities = []
            extraction_timestamp = None
            for f in sorted(os.listdir(batch_dir)):
                if not f.endswith(".json"):
                    continue
                fpath = os.path.join(batch_dir, f)
                try:
                    with open(fpath, encoding="utf-8") as fh:
                        data = json.load(fh)
                    entities.append({
                        "entity":    data.get("entity", f.replace(".json", "")),
                        "row_count": data.get("row_count", 0),
                    })
                    if extraction_timestamp is None:
                        extraction_timestamp = data.get("extraction_timestamp")
                except Exception:
                    entities.append({"entity": f.replace(".json", ""), "row_count": 0})
            results.append({
                "company":               co,
                "batch_id":              batch,
                "extraction_timestamp":  extraction_timestamp,
                "entities":              entities,
                "path":                  batch_dir,
            })

    return results
