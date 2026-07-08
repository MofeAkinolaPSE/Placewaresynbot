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
    get_invoices,
)
from .ops import kpis as ops_kpis, forecast_stock_turnover
from .inventory import get_expiring_inventory
from .crm import get_crm_stats

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


_RECON_STALE_DAYS = 30
_RECON_POINT_IN_TIME = {
    "account_reconciliation",
    "deposits_in_transit",
    "other_outstanding_items",
    "outstanding_checks",
}


def get_reconciliation_status() -> dict:
    """Return freshness of all bank reconciliation snapshots for Ace context."""
    from ..db import db as _db
    from datetime import datetime, timezone

    try:
        rows = (
            _db.table("reconciliation_tracking")
            .select(
                "account_code, account_name, snapshot_type, reconciled_period, "
                "gl_balance, bank_balance, difference, last_imported_at, updated_at"
            )
            .order("account_code")
            .execute()
            .data or []
        )
    except Exception:
        return {"error": "reconciliation_tracking table not yet populated", "stale_accounts": []}

    now = datetime.now(timezone.utc)
    stale = []
    summary = []
    for r in rows:
        updated = r.get("updated_at") or r.get("last_imported_at")
        days_since = None
        if updated:
            try:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days_since = (now - ts).days
            except Exception:
                pass

        is_pit = r["snapshot_type"] in _RECON_POINT_IN_TIME
        is_stale = is_pit and (days_since is None or days_since >= _RECON_STALE_DAYS)
        entry = {
            "account": r.get("account_name") or r["account_code"],
            "type": r["snapshot_type"],
            "period": r.get("reconciled_period"),
            "days_since_update": days_since,
            "difference": r.get("difference"),
            "is_stale": is_stale,
        }
        summary.append(entry)
        if is_stale:
            stale.append(entry)

    return {
        "total_tracked": len(summary),
        "stale_count": len(stale),
        "stale_threshold_days": _RECON_STALE_DAYS,
        "stale_accounts": stale,
        "all_accounts": summary,
    }


SCHEMA_ALLOW_LIST = [
    "customers", "suppliers", "crm_prospects", "customer_360",
    "sage_items_snapshot", "sage_purchase_orders_snapshot", "sage_vendors_snapshot",
    "sage_ar_snapshot", "sage_ap_snapshot", "sage_gl_snapshot", "sage_gl_transactions",
    "temperature_logs", "placeware_storage_zones",
    "inventory_items", "stock_levels", "inventory_movements",
    "event_ledger", "opportunities", "supplier_deliveries",
]


def live_schema_summary() -> dict:
    from ..db import db as _db
    results = []
    for table in SCHEMA_ALLOW_LIST:
        try:
            col_resp = _db.table("information_schema.columns").select(
                "column_name, data_type"
            ).eq("table_name", table).execute()
            columns = [f"{r['column_name']} ({r['data_type']})" for r in (col_resp.data or [])]
        except Exception:
            columns = ["(columns unavailable)"]
        try:
            count_resp = _db.table(table).select("id", count="exact").limit(1).execute()
            row_count = count_resp.count if count_resp.count is not None else len(count_resp.data or [])
        except Exception:
            row_count = "unknown"
        results.append({
            "table": table,
            "row_count": row_count,
            "columns": columns,
        })
    return {"tables": results, "total_tables": len(results)}


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

    registry.register(
        ToolMetadata(
            name="getInvoices",
            description=(
                "Retrieve Placeware AR invoices synced from Sage 50. "
                "Returns invoice list with customer name, invoice date, total amount, "
                "outstanding balance, and status. Use for questions about invoices, "
                "billing, accounts receivable, overdue payments, or outstanding balances."
            ),
            department="finance",
            source="services.sage_adapter.service.get_invoices",
            required_roles={"admin", "management", "finance"},
            allowed_modes={"assistant", "executive"},
        ),
        get_invoices,
    )

    registry.register(
        ToolMetadata(
            name="getCrmStats",
            description=(
                "Get live CRM stats: total customer count from the customers table, "
                "pipeline value, win rate, and average risk score. "
                "Use this for any question about how many customers, customer records, or CRM pipeline."
            ),
            department="crm",
            source="services.crm.get_crm_stats",
            required_roles={"admin", "management", "sales", "finance"},
            allowed_modes={"assistant", "executive"},
        ),
        get_crm_stats,
    )

    registry.register(
        ToolMetadata(
            name="getLiveSchemaSummary",
            description=(
                "List real database tables with column names and row counts. "
                "Use for questions about what data exists, what tables are available, "
                "database structure, or what the system tracks."
            ),
            department="management",
            source="services.tool_registry.live_schema_summary",
            required_roles={"admin", "management"},
            allowed_modes={"assistant", "executive"},
        ),
        live_schema_summary,
    )

    registry.register(
        ToolMetadata(
            name="getReconciliationStatus",
            description=(
                "Check the freshness of bank reconciliation snapshots. "
                "Returns which accounts are stale (not updated in 30+ days) and the "
                "difference between GL balance and bank balance for each. "
                "Call this before answering any question about cash position, bank balance, "
                "outstanding checks, or deposits in transit."
            ),
            department="finance",
            source="services.tool_registry.get_reconciliation_status",
            required_roles={"admin", "finance", "management"},
            allowed_modes={"assistant", "executive"},
        ),
        get_reconciliation_status,
    )

    return registry
