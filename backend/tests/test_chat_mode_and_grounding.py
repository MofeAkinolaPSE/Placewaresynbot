from __future__ import annotations

from fastapi.testclient import TestClient
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from assertions import assert_status  # noqa: E402


client = TestClient(app_module.app)


def test_chat_anonymous_forced_customer_mode(monkeypatch):
    monkeypatch.setattr(app_module, "get_embedding", lambda question: None)
    monkeypatch.setattr(app_module, "_run_orchestration_plan", lambda **kwargs: ([], []))
    monkeypatch.setattr(app_module.llm_client, "generate_response", lambda **kwargs: "ok")

    r = client.post("/chat", json={"question": "show executive summary", "mode": "executive"})
    assert_status(r, 200)
    body = r.json()
    assert body["orchestration"]["mode"] == "customer"


def test_chat_executive_revenue_grounded_answer(monkeypatch):
    monkeypatch.setattr(app_module, "verify_jwt", lambda request: {"sub": "u1", "roles": ["admin"]})
    monkeypatch.setattr(app_module, "get_embedding", lambda question: None)

    tool_outputs = [
        {
            "tool": "getFinancialKpis",
            "department": "finance",
            "source": "test",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {
                "schema_version": "2026.1",
                "status": "ok",
                "payload_type": "object",
                "record_count": 1,
                "payload": {
                    "ar": {"total_amount": 1200000, "total_balance": 340000, "overdue_count": 4},
                    "ap": {"total_amount": 500000, "total_balance": 200000, "overdue_count": 1},
                },
            },
        }
    ]

    monkeypatch.setattr(
        app_module,
        "_run_orchestration_plan",
        lambda **kwargs: (tool_outputs, []),
    )
    monkeypatch.setattr(
        app_module.llm_client,
        "generate_response",
        lambda **kwargs: "LLM should not be used for this grounded KPI path",
    )

    r = client.post(
        "/chat",
        headers={"Authorization": "Bearer test-token"},
        json={"question": "what is our current revenue", "mode": "executive"},
    )
    assert_status(r, 200)
    body = r.json()
    assert body["orchestration"]["mode"] == "executive"
    assert "AR total is" in body["answer"]
    assert any(s.get("question") == "tool:getFinancialKpis" for s in body.get("sources", []))


def test_chat_executive_analytics_requires_tool_evidence(monkeypatch):
    monkeypatch.setattr(app_module, "verify_jwt", lambda request: {"sub": "u1", "roles": ["admin"]})
    monkeypatch.setattr(app_module, "get_embedding", lambda question: None)
    monkeypatch.setattr(app_module, "_run_orchestration_plan", lambda **kwargs: ([], []))
    monkeypatch.setattr(app_module.llm_client, "generate_response", lambda **kwargs: "generic answer should not be used")

    r = client.post(
        "/chat",
        headers={"Authorization": "Bearer test-token"},
        json={"question": "what is our executive revenue performance this quarter", "mode": "executive"},
    )
    assert_status(r, 200)
    body = r.json()
    assert body["orchestration"]["mode"] == "executive"
    assert "no verified backend evidence" in body["answer"].lower()


def test_chat_customer_lead_intent_returns_confirmation(monkeypatch):
    monkeypatch.setattr(app_module, "store_lead", lambda payload: "lead-123")

    r = client.post(
        "/chat",
        json={
            "question": "Please contact me for pricing. My name is Jane Doe and my email is jane@example.com",
            "mode": "customer",
        },
    )
    assert_status(r, 200)
    body = r.json()
    assert "Lead ID: lead-123" in body["answer"]
    assert "Thank you for your patronage" in body["answer"]


def test_chat_customer_order_intent_links_lead_and_returns_tracking(monkeypatch):
    monkeypatch.setattr(app_module, "store_lead", lambda payload: 101)
    monkeypatch.setattr(
        app_module,
        "store_order",
        lambda payload: {
            "order_id": "ord-789",
            "tracking_id": "trk-789",
            "status": "received",
            "items": payload.get("items") or [],
            "source": payload.get("source") or "synbot",
            "lead_id": payload.get("lead_id"),
            "customer_email": payload.get("customer_email"),
        },
    )

    r = client.post(
        "/chat",
        json={
            "question": "Please place order VAC-100 x 2. My name is John Doe and my email is john@example.com",
            "mode": "customer",
        },
    )
    assert_status(r, 200)
    body = r.json()
    assert "Order ID: ord-789" in body["answer"]
    assert "Tracking ID: trk-789" in body["answer"]


def test_chat_executive_tone_strips_customer_ordering_language(monkeypatch):
    monkeypatch.setattr(app_module, "verify_jwt", lambda request: {"sub": "u1", "roles": ["admin"]})
    monkeypatch.setattr(app_module, "get_embedding", lambda question: None)
    monkeypatch.setattr(app_module, "_run_orchestration_plan", lambda **kwargs: ([], []))
    monkeypatch.setattr(
        app_module.llm_client,
        "generate_response",
        lambda **kwargs: (
            "Current stock is broad and active.\n"
            "Next Steps for Ordering:\n"
            "Please contact our team to place an order.\n"
            "Email: info@placeware.example\n"
            "Phone: +234 000 000 0000\n"
            "Thank you for your patronage."
        ),
    )

    r = client.post(
        "/chat",
        headers={"Authorization": "Bearer test-token"},
        json={"question": "give me an update", "mode": "executive"},
    )
    assert_status(r, 200)
    body = r.json()
    answer = body["answer"].lower()
    assert body["orchestration"]["mode"] == "executive"
    assert "next steps for ordering" not in answer
    assert "place an order" not in answer
    assert "thank you for your patronage" not in answer
    assert "email:" not in answer
    assert "phone:" not in answer
