"""Sage adapter stub.

Provides an abstraction layer for future Sage Accounting / Inventory API
integration. For now, operates in mock mode returning deterministic data so
higher layers can be developed and tested without real credentials.
"""
from __future__ import annotations
import time
import random
from ...constants import SAGE_MOCK


class SageAdapter:
    def __init__(self, mock: bool | None = None):
        self.mock = SAGE_MOCK if mock is None else mock

    # Placeholder: authenticate / refresh token
    def ensure_auth(self):  # pragma: no cover
        if self.mock:
            return True
        # TODO: real token refresh
        return True

    def get_items(self, skus: list[str] | None = None):
        """Return inventory items (mock or live)."""
        self.ensure_auth()
        if self.mock:
            base = [
                {"sku": "VX-100", "name": "Sample Vaccine A", "quantity": 120, "uom": "vials"},
                {"sku": "VX-200", "name": "Sample Vaccine B", "quantity": 45, "uom": "vials"},
                {"sku": "EQ-500", "name": "Cold Chain Box", "quantity": 12, "uom": "units"},
            ]
            if skus:
                return [b for b in base if b["sku"] in skus]
            return base
        # TODO: real HTTP calls to Sage endpoints
        return []

    def get_tracking_status(self, tracking_id: str):
        self.ensure_auth()
        if self.mock:
            statuses = ["processing", "in_transit", "at_hub", "out_for_delivery", "delivered"]
            # deterministic pick
            idx = hash(tracking_id) % len(statuses)
            return {
                "id": tracking_id,
                "status": statuses[idx],
                "last_update": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                "eta": time.strftime('%Y-%m-%d', time.gmtime(time.time() + 3*86400)),
            }
        return {"id": tracking_id, "status": "unknown"}
