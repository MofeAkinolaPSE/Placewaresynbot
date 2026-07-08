"""batch_reporter.py — Batch Health Reporting for the ACE pipeline.

Part of the ACE Data Engineering Pipeline (see docs.md/ACE-Implementation-Guide.md).

Reads bronze archives and exceptions.jsonl to produce operational batch health
reports, including a Data Confidence Score per batch.

Data Confidence Score (DCS):
    DCS = Completeness × Validation Pass Rate × Master Resolution Rate

    where:
      Completeness         = (total_bronze_rows - total_exceptions) / total_bronze_rows
      Validation Pass Rate = valid_rows / bronze_rows  (per entity, averaged)
      Resolution Rate      = resolved_rows / canonical_rows (RECOVERABLE doesn't
                             reduce count; only DATA_QUALITY/CRITICAL exceptions do)

    Score range: 0.0 → 1.0  (displayed as 0% → 100%)
    Threshold: DCS < 0.95 triggers a steward review recommendation.

Usage:
    python batch_reporter.py                 # report last batch
    python batch_reporter.py --batch ID      # report specific batch
    python batch_reporter.py --all           # summary table of all batches
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bronze_layer
import exception_manager

_HERE = os.path.dirname(os.path.abspath(__file__))

_DCS_WARN_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Data Confidence Score
# ---------------------------------------------------------------------------

def confidence_score(batch_id: str) -> Dict[str, Any]:
    """Compute Data Confidence Score components for *batch_id*.

    Returns a dict with keys:
        completeness, validation_rate, resolution_rate, dcs, status
    """
    batches = bronze_layer.list_batches()
    batch_info = next(
        (b for b in batches if b["batch_id"] == batch_id), None
    )

    total_bronze = 0
    if batch_info:
        total_bronze = sum(e.get("row_count", 0) for e in batch_info.get("entities", []))

    exceptions = exception_manager.read_exceptions(batch_id=batch_id)

    # Count by severity
    critical_count   = sum(1 for e in exceptions if e.get("severity") == "CRITICAL")
    dq_count         = sum(1 for e in exceptions if e.get("severity") == "DATA_QUALITY")
    recoverable_count= sum(1 for e in exceptions if e.get("severity") == "RECOVERABLE")

    hard_failures = critical_count + dq_count  # rows that were quarantined or halted

    if total_bronze == 0:
        return {
            "completeness":      1.0,
            "validation_rate":   1.0,
            "resolution_rate":   1.0,
            "dcs":               1.0,
            "status":            "NO_DATA",
            "total_bronze":      0,
            "total_exceptions":  len(exceptions),
            "critical":          critical_count,
            "data_quality":      dq_count,
            "recoverable":       recoverable_count,
        }

    # Completeness: how many rows made it through without hard failure
    completeness = max(0.0, (total_bronze - hard_failures) / total_bronze)

    # Validation rate: approximate from exception counts
    validation_rate = max(0.0, (total_bronze - dq_count) / total_bronze)

    # Resolution rate: recoverable flags don't quarantine, so rate stays high
    # RECOVERABLE means row passed through but was flagged
    resolution_rate = max(0.0, (total_bronze - critical_count) / total_bronze)

    dcs = completeness * validation_rate * resolution_rate

    status = "HEALTHY" if dcs >= _DCS_WARN_THRESHOLD else "REVIEW_REQUIRED"
    if critical_count > 0:
        status = "FAILED"

    return {
        "completeness":      round(completeness, 4),
        "validation_rate":   round(validation_rate, 4),
        "resolution_rate":   round(resolution_rate, 4),
        "dcs":               round(dcs, 4),
        "status":            status,
        "total_bronze":      total_bronze,
        "total_exceptions":  len(exceptions),
        "critical":          critical_count,
        "data_quality":      dq_count,
        "recoverable":       recoverable_count,
    }


# ---------------------------------------------------------------------------
# Per-batch report
# ---------------------------------------------------------------------------

def report_batch(batch_id: str) -> str:
    """Return a human-readable health report for *batch_id*."""
    batches = bronze_layer.list_batches()
    batch_info = next(
        (b for b in batches if b["batch_id"] == batch_id), None
    )

    if batch_info is None:
        return f"[batch_reporter] Batch '{batch_id}' not found in bronze archive.\n"

    lines: List[str] = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("  ACE Pipeline — Batch Health Report")
    lines.append("=" * 60)
    lines.append(f"  Batch ID   : {batch_id}")
    ts = batch_info.get("extraction_timestamp", "unknown")
    lines.append(f"  Timestamp  : {ts}")
    lines.append("")

    # Entity breakdown
    entities = batch_info.get("entities", [])
    exceptions = exception_manager.read_exceptions(batch_id=batch_id)

    exc_by_entity: Dict[str, List[Dict]] = {}
    for exc in exceptions:
        ent = exc.get("entity", "unknown")
        exc_by_entity.setdefault(ent, []).append(exc)

    col_w = 20
    lines.append(
        f"  {'Entity':<{col_w}} {'Bronze':>7} {'Exceptions':>11}  Severities"
    )
    lines.append("  " + "-" * 56)

    total_bronze = 0
    total_exc    = 0

    for ent_info in sorted(entities, key=lambda x: x.get("entity", "")):
        ent_name   = ent_info.get("entity", "?")
        row_count  = ent_info.get("row_count", 0)
        ent_excs   = exc_by_entity.get(ent_name, [])
        ent_exc_ct = len(ent_excs)

        sev_counts: Dict[str, int] = {}
        for e in ent_excs:
            sev = e.get("severity", "?")
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
        sev_str = ", ".join(f"{s}:{c}" for s, c in sev_counts.items()) if sev_counts else "—"

        lines.append(
            f"  {ent_name:<{col_w}} {row_count:>7} {ent_exc_ct:>11}  {sev_str}"
        )
        total_bronze += row_count
        total_exc    += ent_exc_ct

    lines.append("  " + "-" * 56)
    lines.append(
        f"  {'TOTAL':<{col_w}} {total_bronze:>7} {total_exc:>11}"
    )
    lines.append("")

    # DCS
    dcs_info = confidence_score(batch_id)
    dcs_pct  = dcs_info["dcs"] * 100
    status   = dcs_info["status"]

    lines.append(f"  Data Confidence Score : {dcs_pct:.1f}%")
    lines.append(f"    Completeness        : {dcs_info['completeness'] * 100:.1f}%")
    lines.append(f"    Validation rate     : {dcs_info['validation_rate'] * 100:.1f}%")
    lines.append(f"    Resolution rate     : {dcs_info['resolution_rate'] * 100:.1f}%")
    lines.append("")

    if status == "HEALTHY":
        lines.append("  Status: HEALTHY — pipeline completed with no critical issues")
    elif status == "REVIEW_REQUIRED":
        lines.append(
            f"  Status: REVIEW_REQUIRED — DCS {dcs_pct:.1f}% below 95% threshold"
        )
        lines.append("           Review exceptions.jsonl and re-run after correction")
    else:
        lines.append(
            f"  Status: FAILED — {dcs_info['critical']} CRITICAL exception(s) detected"
        )
        lines.append("           Engineering review required before production use")

    lines.append("=" * 60)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# All-batches summary
# ---------------------------------------------------------------------------

def report_all_batches() -> str:
    """Return a summary table of all archived batches."""
    batches = bronze_layer.list_batches()

    if not batches:
        return "\n[batch_reporter] No batches found in bronze archive.\n"

    lines: List[str] = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("  ACE Pipeline — All Batches Summary")
    lines.append("=" * 72)
    lines.append(
        f"  {'Batch ID':<36} {'Rows':>6} {'Exc':>5} {'DCS':>7}  Status"
    )
    lines.append("  " + "-" * 66)

    for b in batches:
        bid    = b.get("batch_id", "?")
        total  = sum(e.get("row_count", 0) for e in b.get("entities", []))
        dcs_i  = confidence_score(bid)
        dcs_pct= dcs_i["dcs"] * 100
        exc_ct = dcs_i["total_exceptions"]
        status = dcs_i["status"]

        status_label = {
            "HEALTHY":         "✓ HEALTHY",
            "REVIEW_REQUIRED": "! REVIEW",
            "FAILED":          "✗ FAILED",
            "NO_DATA":         "— NO DATA",
        }.get(status, status)

        lines.append(
            f"  {bid:<36} {total:>6} {exc_ct:>5} {dcs_pct:>6.1f}%  {status_label}"
        )

    lines.append("=" * 72)
    lines.append(f"  Total batches: {len(batches)}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ACE Pipeline — Batch Health Reporter"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--batch", metavar="BATCH_ID",
        help="Report a specific batch by ID",
    )
    group.add_argument(
        "--all", action="store_true",
        help="Show summary table of all batches",
    )
    args = parser.parse_args()

    if args.all:
        print(report_all_batches())
    elif args.batch:
        print(report_batch(args.batch))
    else:
        # Default: last batch
        batches = bronze_layer.list_batches()
        if not batches:
            print("\n[batch_reporter] No batches found in bronze archive.\n")
            return
        last_batch_id = batches[0]["batch_id"]  # list_batches returns newest first
        print(report_batch(last_batch_id))


if __name__ == "__main__":
    main()
