from __future__ import annotations

from fastapi.testclient import TestClient
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from assertions import assert_status  # noqa: E402


client = TestClient(app_module.app)


def test_chat_orchestration_emits_audit_events(monkeypatch):
    events: list[dict] = []

    def fake_audit_event(event_type, details=None, **kwargs):
        events.append({"event_type": event_type, "details": details or {}, **kwargs})

    def fake_get_embedding(question: str):
        return [0.0] * 384

    def fake_retrieve(embedding, k=3):
        return []

    def fake_tool_execute(name, args=None, **kwargs):
        return {
            "tool": name,
            "department": "inventory",
            "source": "test.fake",
            "timestamp": "2026-02-19T00:00:00Z",
            "data": {"ok": True},
        }

    def fake_generate_response(context: str, question: str, instruction=None):
        return "ok"

    monkeypatch.setattr(app_module, "audit_event", fake_audit_event)
    monkeypatch.setattr(app_module, "get_embedding", fake_get_embedding)
    monkeypatch.setattr(app_module.retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(app_module.tool_registry, "execute", fake_tool_execute)
    monkeypatch.setattr(app_module.llm_client, "generate_response", fake_generate_response)

    r = client.post("/chat", json={"question": "show me stock availability"})
    assert_status(r, 200)

    event_types = [e["event_type"] for e in events]
    assert "ai_orchestration_plan" in event_types
    assert "ai_tool_call" in event_types
    assert "ai_orchestration_summary" in event_types

    summary = [e for e in events if e["event_type"] == "ai_orchestration_summary"][-1]
    assert summary.get("subject_type") == "chat_orchestration"
    assert summary.get("details", {}).get("tool_count", 0) >= 1


def test_chat_response_contract_shape(monkeypatch):
    def fake_get_embedding(question: str):
        return [0.0] * 384

    def fake_retrieve(embedding, k=3):
        return [("Q1", "A1")]

    def fake_tool_execute(name, args=None, **kwargs):
        return {
            "tool": "getLatestInventorySnapshot",
            "department": "inventory",
            "source": "test.fake",
            "timestamp": "2026-02-19T00:00:00Z",
            "data": {"status": "ok"},
        }

    def fake_generate_response(context: str, question: str, instruction=None):
        return "contract-ok"

    monkeypatch.setattr(app_module, "get_embedding", fake_get_embedding)
    monkeypatch.setattr(app_module.retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(app_module.tool_registry, "execute", fake_tool_execute)
    monkeypatch.setattr(app_module.llm_client, "generate_response", fake_generate_response)

    r = client.post("/chat", json={"question": "check stock"})
    assert_status(r, 200)
    body = r.json()

    assert set(body.keys()) == {"answer", "bot", "sources", "orchestration"}
    assert isinstance(body["answer"], str)
    assert isinstance(body["bot"], str)
    assert isinstance(body["sources"], list)
    assert isinstance(body["orchestration"], dict)
    assert set(body["orchestration"].keys()) == {"mode", "trace_id", "tool_count", "tools", "errors"}
    assert isinstance(body["orchestration"]["trace_id"], str)
    assert isinstance(body["orchestration"]["tool_count"], int)
    assert isinstance(body["orchestration"]["tools"], list)
    assert isinstance(body["orchestration"]["errors"], list)


def test_chat_orchestration_denied_tool_path(monkeypatch):
    events: list[dict] = []

    def fake_audit_event(event_type, details=None, **kwargs):
        events.append({"event_type": event_type, "details": details or {}, **kwargs})

    def fake_get_embedding(question: str):
        return [0.0] * 384

    def fake_retrieve(embedding, k=3):
        return []

    def fake_plan_tools(question: str, mode: str):
        return [("getExecutiveSummary", {})]

    def fake_tool_execute(name, args=None, **kwargs):
        raise app_module.ToolPermissionError("Insufficient role for tool 'getExecutiveSummary'")

    def fake_generate_response(context: str, question: str, instruction=None):
        return "denied-path-ok"

    monkeypatch.setattr(app_module, "audit_event", fake_audit_event)
    monkeypatch.setattr(app_module, "get_embedding", fake_get_embedding)
    monkeypatch.setattr(app_module.retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(app_module, "_plan_tools", fake_plan_tools)
    monkeypatch.setattr(app_module.tool_registry, "execute", fake_tool_execute)
    monkeypatch.setattr(app_module.llm_client, "generate_response", fake_generate_response)

    r = client.post("/chat", json={"question": "executive summary"})
    assert_status(r, 200)
    body = r.json()
    # The denied tool must not appear in the success list (agent routing may add its own entries)
    assert "getExecutiveSummary" not in body["orchestration"]["tools"]
    assert len(body["orchestration"]["errors"]) >= 1

    event_types = [e["event_type"] for e in events]
    assert "ai_tool_denied" in event_types
    summary = [e for e in events if e["event_type"] == "ai_orchestration_summary"][-1]
    assert summary.get("outcome") == "failed"


def test_chat_orchestration_tool_error_path(monkeypatch):
    events: list[dict] = []

    def fake_audit_event(event_type, details=None, **kwargs):
        events.append({"event_type": event_type, "details": details or {}, **kwargs})

    def fake_get_embedding(question: str):
        return [0.0] * 384

    def fake_retrieve(embedding, k=3):
        return []

    def fake_plan_tools(question: str, mode: str):
        return [("getLatestInventorySnapshot", {"limit": 5})]

    def fake_tool_execute(name, args=None, **kwargs):
        raise app_module.ToolExecutionError("Tool 'getLatestInventorySnapshot' execution failed")

    def fake_generate_response(context: str, question: str, instruction=None):
        return "error-path-ok"

    monkeypatch.setattr(app_module, "audit_event", fake_audit_event)
    monkeypatch.setattr(app_module, "get_embedding", fake_get_embedding)
    monkeypatch.setattr(app_module.retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(app_module, "_plan_tools", fake_plan_tools)
    monkeypatch.setattr(app_module.tool_registry, "execute", fake_tool_execute)
    monkeypatch.setattr(app_module.llm_client, "generate_response", fake_generate_response)

    r = client.post("/chat", json={"question": "stock availability"})
    assert_status(r, 200)
    body = r.json()
    # The errored tool must not appear in the success list (agent routing may add its own entries)
    assert "getLatestInventorySnapshot" not in body["orchestration"]["tools"]
    assert len(body["orchestration"]["errors"]) >= 1

    event_types = [e["event_type"] for e in events]
    assert "ai_tool_error" in event_types
    summary = [e for e in events if e["event_type"] == "ai_orchestration_summary"][-1]
    assert summary.get("outcome") == "failed"
