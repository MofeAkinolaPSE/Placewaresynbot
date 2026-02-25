from __future__ import annotations

import datetime as dt
from statistics import mean
from typing import Any

from src.constants import PROCUREMENT_CLEARANCE_DELAY_DAYS, PROCUREMENT_DAILY_DELAY_COST

SHIPMENT_STATES = [
    "in_transit",
    "at_port",
    "under_clearance",
    "released",
    "delivered_to_warehouse",
]

SHIPMENT_TRANSITIONS: dict[str, set[str]] = {
    "in_transit": {"at_port"},
    "at_port": {"under_clearance", "released"},
    "under_clearance": {"released"},
    "released": {"delivered_to_warehouse"},
    "delivered_to_warehouse": set(),
}


def utc_now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def validate_state(state: str) -> str:
    normalized = (state or "").strip().lower()
    if normalized not in SHIPMENT_STATES:
        allowed = ", ".join(SHIPMENT_STATES)
        raise ValueError(f"status must be one of: {allowed}")
    return normalized


def validate_transition(current_state: str, next_state: str) -> None:
    src = validate_state(current_state)
    dst = validate_state(next_state)
    if dst not in SHIPMENT_TRANSITIONS[src]:
        raise ValueError(f"invalid transition {src} -> {dst}")


def transition_timestamp_patch(current: str, nxt: str) -> dict[str, Any]:
    now_iso = utc_now_iso()
    patch: dict[str, Any] = {"status": nxt, "updated_at": now_iso}

    if nxt == "at_port" and current == "in_transit":
        patch["arrived_port_at"] = now_iso
    elif nxt == "under_clearance":
        patch["clearance_started_at"] = now_iso
    elif nxt == "released":
        patch["released_at"] = now_iso
    elif nxt == "delivered_to_warehouse":
        patch["delivered_at"] = now_iso

    return patch


def compute_clearance_delay_days(
    clearance_started_at: str | None,
    released_at: str | None,
) -> float:
    started = parse_iso_datetime(clearance_started_at)
    if not started:
        return 0.0
    ended = parse_iso_datetime(released_at) or dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    delta = ended - started
    return max(round(delta.total_seconds() / 86400.0, 2), 0.0)


def estimate_delay_impact(delay_days: float, daily_cost: float | None = None) -> float:
    unit_cost = daily_cost if daily_cost is not None else PROCUREMENT_DAILY_DELAY_COST
    return round(max(delay_days, 0.0) * max(unit_cost, 0.0), 2)


def supplier_scorecard(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for shipment in shipments:
        supplier = str(shipment.get("supplier_name") or "unknown").strip().lower()
        grouped.setdefault(supplier, []).append(shipment)

    scorecards: list[dict[str, Any]] = []
    for supplier_key, rows in grouped.items():
        delays: list[float] = []
        rejected = 0
        compliance_breaches = 0

        for row in rows:
            delay_days = compute_clearance_delay_days(
                row.get("clearance_started_at"),
                row.get("released_at"),
            )
            if delay_days > 0:
                delays.append(delay_days)
            metadata = row.get("metadata") or {}
            if isinstance(metadata, dict):
                if bool(metadata.get("rejected") or False):
                    rejected += 1
                if bool(metadata.get("compliance_breach") or False):
                    compliance_breaches += 1

        total = len(rows)
        scorecards.append(
            {
                "supplier": supplier_key,
                "shipments": total,
                "avg_delay_days": round(mean(delays), 2) if delays else 0.0,
                "rejection_rate": round(rejected / total, 4) if total else 0.0,
                "compliance_breach_count": compliance_breaches,
                "reliability_score": round(
                    max(
                        0.0,
                        100.0
                        - (round(mean(delays), 2) if delays else 0.0) * 4.0
                        - (rejected / total if total else 0.0) * 40.0
                        - compliance_breaches * 3.0,
                    ),
                    2,
                ),
            }
        )

    scorecards.sort(key=lambda item: item["reliability_score"], reverse=True)
    return scorecards


def run_clearance_analysis(
    shipments: list[dict[str, Any]],
    threshold_days: int | None = None,
    daily_cost: float | None = None,
) -> dict[str, Any]:
    threshold = int(threshold_days or PROCUREMENT_CLEARANCE_DELAY_DAYS)
    delayed: list[dict[str, Any]] = []

    for shipment in shipments:
        if shipment.get("status") not in {"under_clearance", "released", "delivered_to_warehouse"}:
            continue
        delay_days = compute_clearance_delay_days(
            shipment.get("clearance_started_at"),
            shipment.get("released_at"),
        )
        if delay_days > threshold:
            delayed.append(
                {
                    "shipment_id": shipment.get("id"),
                    "shipment_ref": shipment.get("shipment_ref"),
                    "supplier_name": shipment.get("supplier_name"),
                    "delay_days": delay_days,
                    "threshold_days": threshold,
                    "estimated_impact": estimate_delay_impact(delay_days, daily_cost),
                    "currency": shipment.get("currency") or "NGN",
                    "status": shipment.get("status"),
                }
            )

    delayed.sort(key=lambda item: item["delay_days"], reverse=True)
    total_impact = round(sum(item["estimated_impact"] for item in delayed), 2)

    return {
        "threshold_days": threshold,
        "delayed_count": len(delayed),
        "estimated_total_impact": total_impact,
        "delayed_shipments": delayed,
        "supplier_scorecard": supplier_scorecard(shipments),
    }
