from __future__ import annotations

from fastapi.testclient import TestClient
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from assertions import assert_status  # noqa: E402
from src.services.tool_registry import (  # noqa: E402
    build_default_tool_registry,
    ToolPermissionError,
    ToolRegistry,
    ToolMetadata,
)


client = TestClient(app_module.app)


def test_registry_denies_finance_tool_for_customer_role():
    registry = build_default_tool_registry()
    try:
        registry.execute("getFinancialKpis", {}, roles=set(), mode="customer")
        assert False, "Expected ToolPermissionError"
    except ToolPermissionError:
        assert True


def test_registry_allows_customer_inventory_tool():
    registry = build_default_tool_registry()
    customer_tools = registry.list_tools(roles=set(), mode="customer")
    names = {t["name"] for t in customer_tools}
    assert "getLatestInventorySnapshot" in names
    assert "getInventoryBySkus" in names


def test_registry_execute_enforces_roles_with_local_tool():
    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="secureTool",
            description="secure",
            department="test",
            source="test.secure",
            required_roles={"admin"},
            allowed_modes={"assistant"},
        ),
        lambda: {"ok": True},
    )

    try:
        registry.execute("secureTool", roles={"finance"}, mode="assistant")
        assert False, "Expected ToolPermissionError"
    except ToolPermissionError:
        assert True

    out = registry.execute("secureTool", roles={"admin"}, mode="assistant")
    assert out["tool"] == "secureTool"
    assert out["data"]["schema_version"] == "2026.1"
    assert out["data"]["status"] == "ok"


def test_registry_adapter_returns_deterministic_bounded_payload():
    registry = ToolRegistry()

    def noisy_tool():
        return {
            "zeta": "x" * 1000,
            "alpha": [
                {"k": 2, "j": 1},
                {"k": 4, "j": 3},
            ] + list(range(0, 200)),
        }

    registry.register(
        ToolMetadata(
            name="noisyTool",
            description="noise",
            department="test",
            source="test.noisy",
            required_roles=set(),
            allowed_modes={"assistant"},
        ),
        noisy_tool,
    )

    out = registry.execute("noisyTool", roles=set(), mode="assistant")
    data = out["data"]
    assert data["schema_version"] == "2026.1"
    assert data["payload_type"] == "object"
    payload = data["payload"]
    assert list(payload.keys()) == ["alpha", "zeta"]
    assert isinstance(payload["alpha"], list)
    assert len(payload["alpha"]) <= 50
    assert isinstance(payload["zeta"], str)
    assert len(payload["zeta"]) <= 603  # includes ellipsis when truncated


def test_ai_tools_unauth_forced_to_customer_mode_even_if_requested_executive():
    r = client.get("/ai/tools?mode=executive")
    assert_status(r, 200)
    data = r.json()
    assert data["mode"] == "customer"
    names = {t["name"] for t in data["tools"]}
    assert "getExecutiveSummary" not in names


def test_ai_tools_authenticated_mode_respected(monkeypatch):
    def fake_verify_jwt(request, required_role=None):
        payload = {"sub": "u-1", "roles": ["finance"]}
        request.state.user = payload
        return payload

    monkeypatch.setattr(app_module, "verify_jwt", fake_verify_jwt)
    r = client.get("/ai/tools?mode=assistant", headers={"Authorization": "Bearer test-token"})
    assert_status(r, 200)
    data = r.json()
    assert data["mode"] == "assistant"
    names = {t["name"] for t in data["tools"]}
    assert "getFinancialKpis" in names
    assert "getExecutiveSummary" not in names
