"""
events.py — Event identity and envelope construction.

Deterministic event IDs are what turn at-least-once delivery into exactly-once
effect. The bridge may send the same event twice (retry after a timeout where
SynBot actually succeeded, replay after a crash, an operator-triggered
rescan). SynBot deduplicates on ``event_id``, so a repeat is a no-op.

The ID must therefore be:

  * **Deterministic** — regenerating it from the same Sage row yields the same
    ID, so a rescan after a crash produces the ID already delivered rather than
    a new one. A random UUID would defeat the entire mechanism.
  * **Content-sensitive** — editing an invoice must produce a NEW ID so the
    edit propagates. Keying on the invoice ID alone would make edits invisible.

We hash (entity_type, sage_id, content-fingerprint). The fingerprint is a
canonical JSON rendering of the business fields, so any change to a value the
downstream cares about yields a new ID, while re-reading an unchanged row does
not.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

#: Bumped when the envelope shape changes in a way SynBot must notice.
SCHEMA_VERSION = 2


def content_fingerprint(payload: Dict[str, Any]) -> str:
    """
    Stable hash of the business content of a payload.

    Volatile fields are excluded — they change on every read and would make
    every scan look like an edit, producing infinite spurious events.
    """
    volatile = {"extracted_at", "event_id", "bridge_version", "_meta"}
    filtered = {k: v for k, v in payload.items() if k not in volatile}
    canonical = json.dumps(filtered, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def make_event_id(entity_type: str, sage_id: str, payload: Dict[str, Any]) -> str:
    """
    Build the deterministic event ID for a Sage record.

    Same row, unchanged  → same ID → SynBot dedupes, no duplicate work.
    Same row, edited     → different ID → the edit propagates.
    """
    fp = content_fingerprint(payload)
    raw = "{}:{}:{}".format(entity_type, sage_id, fp)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return "{}-{}".format(entity_type, digest)


def build_envelope(
    entity_type: str,
    sage_id: str,
    payload: Dict[str, Any],
    event: str = "record_upserted",
) -> Dict[str, Any]:
    """
    Wrap a payload in the webhook envelope the bridge sends to SynBot.

    Envelope shape::

        {
          "source": "sage_bridge",
          "schema_version": 2,
          "event": "record_upserted",
          "event_id": "invoice-a1b2c3...",     <- dedupe key
          "entity_type": "invoice",
          "sage_id": "1234",
          "data": { ...full record... }
        }

    Backward compatibility: SynBot's existing handler switches on
    ``event == "data_changed"`` and ``entity_type``. Those keys are still
    present on the change-ping envelope built by build_change_ping(), so the
    old code path keeps working while the new data-carrying path is adopted.
    """
    return {
        "source": "sage_bridge",
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "event_id": make_event_id(entity_type, sage_id, payload),
        "entity_type": entity_type,
        "sage_id": sage_id,
        "data": payload,
    }


def build_change_ping(entity_type: str, token: str) -> Dict[str, Any]:
    """
    Build a legacy-compatible "something changed" ping.

    Used for entity types the bridge does not yet extract in full (vendors,
    payroll, ...). Matches the original payload so SynBot's existing
    schedule_entity_sync path is untouched, but adds an event_id so it is
    deduplicated like everything else.

    ``token`` distinguishes one ping from the next — pass the watermark or
    change token, never a timestamp, or every ping looks unique and the
    dedupe is defeated.
    """
    payload = {"entity_type": entity_type, "token": token}
    return {
        "source": "sage_bridge",
        "schema_version": SCHEMA_VERSION,
        "event": "data_changed",          # legacy key SynBot already handles
        "event_id": make_event_id("ping-" + entity_type, token, payload),
        "entity_type": entity_type,
    }
