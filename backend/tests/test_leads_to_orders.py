import os
from fastapi.testclient import TestClient

# Ensure no auth required in tests by monkeypatching require_role
os.environ["WEBHOOK_SECRET"] = "test-secret"

from app import app
import src.db as db

client = TestClient(app)


def test_leads_to_orders_endpoint(monkeypatch):
    # Monkeypatch require_role to be no-op
    import app as app_module
    monkeypatch.setattr(app_module, "require_role", lambda request, role: True)

    # Monkeypatch db_helpers to return deterministic data
    def fake_conversion(days=30):
        return {"days": days, "leads": 10, "orders": 8, "orders_linked_to_leads": 6, "conversion_rate_percent": 60.0}
    monkeypatch.setattr(db, "supabase", db.supabase)
    monkeypatch.setattr("src.db_helpers.get_lead_order_conversion", lambda days=30: fake_conversion(days))

    r = client.get("/admin/leads-to-orders?days=30")
    assert r.status_code == 200
    data = r.json().get("data")
    assert data["days"] == 30
    assert data["leads"] == 10
*** End Patch