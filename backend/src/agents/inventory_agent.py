"""Inventory Agent skeleton.

Listens to `event_bus` and updates simple inventory KPIs such as
`stock_events` and a naive `stock_projection` metric stored in `placeware_kpis`.
"""
from __future__ import annotations

from typing import Any, Dict, List
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class InventoryIntelligenceAgent(BaseAgent):
    name = "inventory_intelligence"
    required_role = "inventory_analyst"

    def collect_data(self) -> Dict[str, Any]:
        """Collects data by delegating to a provided `db_executor` and `query_specs`.

        Expected context keys (recommended):
          - `db_executor`: callable(spec) -> result
          - `query_specs`: iterable of specs (SQL or dict)
          - `parallel_queries`: bool
        If none provided, returns an empty placeholder result so the agent
        remains safe for demo workflows.
        """
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs")
        parallel = bool(self.context.get("parallel_queries", False))

        if not executor or not specs:
            # No DB attached — return empty structure (safe fallback)
            return {"results": [], "query_count": 0, "total_latency_ms": 0}

        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Simple analysis: look for low-stock rows and aggregate counts.

        The `data['results']` is expected to be a list of (spec, result) tuples.
        Each `result` may be a list of rows or an error dict. This method
        normalizes and produces quick metrics.
        """
        results = data.get("results", [])
        low_stock_items: List[Dict[str, Any]] = []
        errors: List[str] = []

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(f"spec={spec}: {res.get('error')}")
                continue
            # Expect res to be iterable rows
            try:
                for row in res or []:
                    # row is expected to contain `product_id`, `stock`, `threshold`
                    if not isinstance(row, dict):
                        continue
                    stock = row.get("stock")
                    thresh = row.get("threshold") or row.get("reorder_threshold")
                    if stock is None or thresh is None:
                        continue
                    if stock <= thresh:
                        low_stock_items.append(row)
            except Exception:
                errors.append(f"failed to parse result for spec={spec}")

        metrics = {
            "low_stock_count": len(low_stock_items),
            "query_count": data.get("query_count", 0),
            "total_latency_ms": data.get("total_latency_ms", 0),
        }

        return {"metrics": metrics, "low_stock_items": low_stock_items, "errors": errors}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        low_items = analysis.get("low_stock_items", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(metrics)

        if low_items:
            insight.findings.append(f"{len(low_items)} items at or below reorder threshold")
            # create simple recommendations
            rec = "Create replenishment requests for low-stock items."
            insight.recommendations.append(rec)
            # include first few items as supporting refs
            insight.supporting_refs.extend(low_items[:10])

            # Optional: trigger replenishment workflow if engine provided in context
            engine = self.context.get("workflow_engine")
            auto_trigger = bool(self.context.get("auto_trigger_workflow", True))
            if engine and auto_trigger:
                # build items payload: determine qty using reorder_qty or threshold heuristic
                items = []
                for row in low_items:
                    try:
                        product_id = row.get("product_id") or row.get("product") or row.get("id")
                        stock = int(row.get("stock") or 0)
                        reorder_qty = row.get("reorder_qty")
                        threshold = int(row.get("threshold") or row.get("reorder_threshold") or 0)
                        if reorder_qty is None:
                            # default heuristic: bring stock up to 2x threshold
                            desired = max(threshold * 2, threshold + 10)
                            qty = max(desired - stock, 1)
                        else:
                            qty = int(reorder_qty)
                    except Exception:
                        qty = 10
                        product_id = row.get("product_id") or row.get("product") or "unknown"
                    items.append({"product_id": product_id, "qty": qty})

                try:
                    result = engine.run("replenishment.create", {"items": items})
                    insight.execution_metadata["workflow_triggered"] = True
                    insight.execution_metadata["workflow_result"] = {"created": result.get("steps", [])}
                except Exception as e:
                    insight.execution_metadata["workflow_triggered"] = False
                    insight.execution_metadata.setdefault("workflow_errors", []).append(str(e))

        if errors:
            insight.risks.append("partial_data: some queries failed")
            insight.supporting_refs.append({"errors": errors})

        # confidence: heuristic based on absence of errors
        insight.confidence_score = 0.9 if not errors else 0.6
        insight.execution_metadata["query_count"] = metrics.get("query_count", 0)
        insight.execution_metadata["timestamp"] = insight.execution_metadata.get("timestamp")

        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 300)
        if cache is None:
            return
        # store pydict to keep cache simple
        cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "metrics": "dict",
            "findings": "list[str]",
            "risks": "list[str]",
            "recommendations": "list[str]",
            "confidence_score": "float",
        }
