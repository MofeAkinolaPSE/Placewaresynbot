from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from inspect import signature
from typing import Any, Callable
import logging

from ..db import get_controls_rollup, get_chat_history
from .intelligence import executive_summary, risk_signals, recommendations
from .sage_adapter.service import (
    kpis as finance_kpis,
    ar_trend_summary,
    ar_aging_buckets,
    latest_inventory_snapshot,
    inventory_by_skus,
)
from .ops import kpis as ops_kpis, forecast_stock_turnover
from .inventory import get_expiring_inventory

logger = logging.getLogger("tool_registry")

TOOL_RESPONSE_SCHEMA_VERSION = "2026.1"
MAX_ADAPTER_DEPTH = 4
MAX_ADAPTER_LIST_ITEMS = 50
MAX_ADAPTER_STRING_LEN = 600

ToolAdapter = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    department: str
    source: str
    required_roles: set[str] = field(default_factory=set)
    allowed_modes: set[str] = field(default_factory=lambda: {"assistant", "executive"})


@dataclass
class ToolDefinition:
    metadata: ToolMetadata
    handler: Callable[..., Any]
    adapter: ToolAdapter


class ToolPermissionError(PermissionError):
    """Raised when caller lacks role/mode permissions for a tool."""


class ToolExecutionError(RuntimeError):
    """Raised when a tool execution fails due to runtime/argument issues."""


def _sanitize_tool_data(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_ADAPTER_DEPTH:
        return "<max-depth-reached>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if len(value) <= MAX_ADAPTER_STRING_LEN:
            return value
        return value[:MAX_ADAPTER_STRING_LEN] + "..."

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k in sorted(value.keys(), key=lambda x: str(x)):
            out[str(k)] = _sanitize_tool_data(value[k], depth=depth + 1)
        return out

    if isinstance(value, (list, tuple, set)):
        out_list = list(value)[:MAX_ADAPTER_LIST_ITEMS]
        return [_sanitize_tool_data(v, depth=depth + 1) for v in out_list]

    return str(value)


def default_tool_adapter(raw: Any) -> dict[str, Any]:
    payload = _sanitize_tool_data(raw)
    if isinstance(payload, list):
        record_count = len(payload)
        payload_type = "list"
    elif isinstance(payload, dict):
        record_count = len(payload)
        payload_type = "object"
    else:
        record_count = 1
        payload_type = "scalar"

    return {
        "schema_version": TOOL_RESPONSE_SCHEMA_VERSION,
        "status": "ok",
        "payload_type": payload_type,
        "record_count": record_count,
        "payload": payload,
    }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        metadata: ToolMetadata,
        handler: Callable[..., Any],
        adapter: ToolAdapter | None = None,
    ) -> None:
        if metadata.name in self._tools:
            raise ValueError(f"Tool already registered: {metadata.name}")
        self._tools[metadata.name] = ToolDefinition(
            metadata=metadata,
            handler=handler,
            adapter=adapter or default_tool_adapter,
        )

    def list_tools(self, roles: set[str] | None = None, mode: str = "assistant") -> list[dict[str, Any]]:
        current_roles = roles or set()
        out: list[dict[str, Any]] = []
        for tool_name in sorted(self._tools.keys()):
            td = self._tools[tool_name]
            if mode not in td.metadata.allowed_modes:
                continue
            if td.metadata.required_roles and not (td.metadata.required_roles & current_roles):
                continue
            out.append(
                {
                    "name": td.metadata.name,
                    "description": td.metadata.description,
                    "department": td.metadata.department,
                    "source": td.metadata.source,
                    "required_roles": sorted(td.metadata.required_roles),
                    "allowed_modes": sorted(td.metadata.allowed_modes),
                    "parameters": list(signature(td.handler).parameters.keys()),
                }
            )
        return out

    def execute(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        roles: set[str] | None = None,
        mode: str = "assistant",
    ) -> dict[str, Any]:
        if name not in self._tools:
            raise ToolExecutionError(f"Unknown tool: {name}")

        td = self._tools[name]
        current_roles = roles or set()
        if mode not in td.metadata.allowed_modes:
            raise ToolPermissionError(f"Tool '{name}' is not available in mode '{mode}'")
        if td.metadata.required_roles and not (td.metadata.required_roles & current_roles):
            raise ToolPermissionError(f"Insufficient role for tool '{name}'")

        payload = args or {}
        try:
            raw_data = td.handler(**payload)
            data = td.adapter(raw_data)
        except TypeError as e:
            raise ToolExecutionError(f"Invalid arguments for tool '{name}': {e}") from e
        except Exception as e:
            logger.error(f"Tool '{name}' failed: {e}")
            raise ToolExecutionError(f"Tool '{name}' execution failed") from e

        return {
            "tool": td.metadata.name,
            "department": td.metadata.department,
            "source": td.metadata.source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolMetadata(
            name="getExecutiveSummary",
            description="Get executive business health summary across finance, ops, inventory, and workforce.",
            department="management",
            source="services.intelligence.executive_summary",
            required_roles={"admin", "management"},
            allowed_modes={"assistant", "executive"},
        ),
        executive_summary,
    )

    registry.register(
        ToolMetadata(
            name="getRiskSignals",
            description="Get active cross-functional risk signals from current operational datasets.",
            department="management",
            source="services.intelligence.risk_signals",
            required_roles={"admin", "management", "ops", "finance"},
            allowed_modes={"assistant", "executive"},
        ),
        risk_signals,
    )

    registry.register(
        ToolMetadata(
            name="getRecommendations",
            description="Get deterministic system recommendations generated from current data state.",
            department="management",
            source="services.intelligence.recommendations",
            required_roles={"admin", "management", "ops", "finance", "sales"},
            allowed_modes={"assistant", "executive"},
        ),
        recommendations,
    )

    registry.register(
        ToolMetadata(
            name="getFinancialKpis",
            description="Get AR/AP KPI summary from imported Sage snapshots.",
            department="finance",
            source="services.sage_adapter.service.kpis",
            required_roles={"admin", "management", "finance"},
            allowed_modes={"assistant", "executive"},
        ),
        finance_kpis,
    )

    registry.register(
        ToolMetadata(
            name="getArTrendSummary",
            description="Get AR trend periods used for finance and liquidity monitoring.",
            department="finance",
            source="services.sage_adapter.service.ar_trend_summary",
            required_roles={"admin", "management", "finance"},
            allowed_modes={"assistant", "executive"},
        ),
        ar_trend_summary,
    )

    registry.register(
        ToolMetadata(
            name="getArAgingBuckets",
            description="Get AR aging buckets for receivables risk monitoring.",
            department="finance",
            source="services.sage_adapter.service.ar_aging_buckets",
            required_roles={"admin", "management", "finance"},
            allowed_modes={"assistant", "executive"},
        ),
        ar_aging_buckets,
    )

    registry.register(
        ToolMetadata(
            name="getOpsKpis",
            description="Get operations KPIs (fulfillment, downtime, stock turnover).",
            department="ops",
            source="services.ops.kpis",
            required_roles={"admin", "management", "ops"},
            allowed_modes={"assistant", "executive"},
        ),
        ops_kpis,
    )

    registry.register(
        ToolMetadata(
            name="runStockTurnoverForecast",
            description="Run stock turnover forecast over configured horizon/window.",
            department="ops",
            source="services.ops.forecast_stock_turnover",
            required_roles={"admin", "management", "ops"},
            allowed_modes={"assistant", "executive"},
        ),
        forecast_stock_turnover,
    )

    registry.register(
        ToolMetadata(
            name="getLatestInventorySnapshot",
            description="Get latest inventory snapshot rows from imported Sage data.",
            department="inventory",
            source="services.sage_adapter.service.latest_inventory_snapshot",
            required_roles=set(),
            allowed_modes={"assistant", "executive", "customer"},
        ),
        latest_inventory_snapshot,
    )

    registry.register(
        ToolMetadata(
            name="getInventoryBySkus",
            description="Get current inventory snapshot rows for selected SKUs.",
            department="inventory",
            source="services.sage_adapter.service.inventory_by_skus",
            required_roles=set(),
            allowed_modes={"assistant", "executive", "customer"},
        ),
        inventory_by_skus,
    )

    registry.register(
        ToolMetadata(
            name="getExpiringInventory",
            description="Get inventory expiry risk tiers from latest batch snapshot.",
            department="inventory",
            source="services.inventory.get_expiring_inventory",
            required_roles={"admin", "management", "ops", "sales"},
            allowed_modes={"assistant", "executive"},
        ),
        get_expiring_inventory,
    )

    registry.register(
        ToolMetadata(
            name="getProjectControlsRollup",
            description="Get project controls rollup with scope/cost/risk/change status totals.",
            department="project_controls",
            source="db.get_controls_rollup",
            required_roles={"admin", "management"},
            allowed_modes={"assistant", "executive"},
        ),
        get_controls_rollup,
    )

    registry.register(
        ToolMetadata(
            name="fetchConversationAudit",
            description="Fetch stored conversation history rows for a specific user id.",
            department="chat",
            source="db.get_chat_history",
            required_roles={"admin", "management"},
            allowed_modes={"assistant", "audit"},
        ),
        get_chat_history,
    )

    return registry
