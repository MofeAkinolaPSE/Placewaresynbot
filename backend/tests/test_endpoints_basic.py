"""Basic endpoint tests (lightweight) using FastAPI TestClient.

These tests mock out network-dependent functionality lightly by relying on
current mock scaffolds (LLM returns empty -> fallback path) and placeholder
stock/order implementations.
"""
from fastapi.testclient import TestClient
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from assertions import assert_status  # noqa: E402

client = TestClient(app_module.app)


def test_root_health():
    r = client.get("/")
    assert_status(r, 200)
    assert "message" in r.json()


def test_chat_fallback_no_embedding(monkeypatch):
    # Force retriever return empty and llm return empty so fallback triggers
    from src import retrieval, llm_client

    def fake_retrieve(self, embedding, k=1):  # noqa: D401
        return []

    def fake_generate_response(self, context, question, instruction=None):
        return ""  # force fallback

    monkeypatch.setattr(retrieval.QnARetriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(llm_client.LLMClient, "generate_response", fake_generate_response)
    r = client.post("/chat", json={"question": "What do you offer?"})
    assert_status(r, 200)
    j = r.json()
    assert "answer" in j
    # Fallback returns a non-empty company profile response
    assert len(j["answer"]) > 20


def test_stock_snapshot_fallback():
    r = client.post("/stock", json={})
    assert_status(r, 200)
    data = r.json()
    assert "stock" in data
    assert isinstance(data["stock"], list)


def test_submit_order_minimal(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "store_order",
        lambda payload: {
            "order_id": "ord-123",
            "tracking_id": "trk-123",
            "status": "received",
            "items": payload.get("items") or [],
            "source": payload.get("source") or "direct",
            "lead_id": payload.get("lead_id"),
            "customer_email": payload.get("customer_email"),
        },
    )
    payload = {
        "customer_name": "Test User",
        "customer_email": "test@example.com",
        "items": [{"sku": "VX-100", "quantity": 2}],
    }
    r = client.post("/submit_order", json=payload)
    assert_status(r, 200)
    j = r.json()
    assert "order_id" in j
    assert "tracking_id" in j
    assert j["status"] == "received"


def test_track_lookup(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_tracking",
        lambda tracking_id: {
            "id": tracking_id,
            "order_id": "ord-123",
            "status": "received",
            "last_update": "2026-01-01T00:00:00Z",
            "eta": "pending",
        },
    )
    r = client.get("/track/ABC123")
    assert_status(r, 200)
    j = r.json()
    assert j["id"] == "ABC123"
    assert j["status"] == "received"
