from __future__ import annotations
from typing import Any, Dict, List
import datetime as dt
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class ExpiryMonitoringAgent(BaseAgent):
    name = "expiry_monitoring"
    required_role = "qc"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor:
            return {"results": [], "query_count": 0}
        if not specs:
            specs = [{"type": "inventory_expiring"}]
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        warning_window = int(self.context.get("expiry_warning_days", 60))
        promotion_recs: List[Dict[str, Any]] = []
        reallocation_recs: List[Dict[str, Any]] = []
        slow_moving: List[Dict[str, Any]] = []
        metrics = {"near_expiry_count": 0, "slow_moving_count": 0}

        now = dt.datetime.utcnow()
        for spec, res in results:
            for row in res or []:
                try:
                    batch_id = row.get("batch_id") or row.get("id")
                    sku = row.get("sku") or row.get("product_id")
                    expiry_raw = row.get("expiry_date") or row.get("best_before")
                    if not expiry_raw:
                        continue
                    try:
                        expiry = dt.datetime.fromisoformat(str(expiry_raw))
                    except Exception:
                        # try date-only
                        try:
                            expiry = dt.datetime.strptime(str(expiry_raw), "%Y-%m-%d")
                        except Exception:
                            continue

                    days_to_expiry = max(0, (expiry - now).days)
                    if days_to_expiry <= warning_window:
                        metrics["near_expiry_count"] += 1
                        avg_monthly_sales = float(row.get("avg_monthly_sales") or 0)
                        qty_on_hand = float(row.get("qty_on_hand") or row.get("stock") or 0)
                        # recommend promotion when little time and large stock
                        if days_to_expiry <= 30 or qty_on_hand > (avg_monthly_sales * 2):
                            promotion_recs.append({"batch_id": batch_id, "sku": sku, "days_to_expiry": days_to_expiry, "qty": qty_on_hand})
                        else:
                            reallocation_recs.append({"batch_id": batch_id, "sku": sku, "days_to_expiry": days_to_expiry, "qty": qty_on_hand})

                    # slow-moving detection: use turnover_days or avg_monthly_sales
                    turnover_days = row.get("turnover_days")
                    if turnover_days is not None:
                        try:
                            if float(turnover_days) > 90:
                                slow_moving.append({"batch_id": batch_id, "sku": sku, "turnover_days": turnover_days, "qty": row.get("qty_on_hand")})
                                metrics["slow_moving_count"] += 1
                        except Exception:
                            pass
                except Exception:
                    continue

        return {"metrics": metrics, "promotion_recs": promotion_recs, "reallocation_recs": reallocation_recs, "slow_moving": slow_moving}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        metrics = analysis.get("metrics") or {}
        promotion_recs = analysis.get("promotion_recs") or []
        reallocation_recs = analysis.get("reallocation_recs") or []
        slow_moving = analysis.get("slow_moving") or []

        insight.metrics.update(metrics)

        if promotion_recs:
            insight.findings.append(f"{len(promotion_recs)} batch(es) require promotion to avoid expiry.")
            insight.supporting_refs.extend(promotion_recs[:10])
            insight.recommendations.append("Create targeted promotions or discounts for near-expiry stock.")
            # enqueue promotion workflow if available
            if self.context.get("auto_trigger_workflow") and self.context.get("workflow_engine"):
                engine = self.context.get("workflow_engine")
                for p in promotion_recs[:20]:
                    try:
                        engine.enqueue("inventory.expiry_promotion", {
                            "sku": p.get("sku"),
                            "batch_id": p.get("batch_id"),
                            "qty": p.get("qty"),
                            "days_to_expiry": p.get("days_to_expiry", 60),
                            "discount_pct": 15.0,
                        })
                    except Exception:
                        continue

        if reallocation_recs:
            insight.findings.append(f"{len(reallocation_recs)} batch(es) recommended for reallocation.")
            insight.recommendations.append("Consider internal transfers to nearby warehouses with higher velocity.")
            insight.supporting_refs.extend(reallocation_recs[:10])

        if slow_moving:
            insight.findings.append(f"{len(slow_moving)} slow-moving batch(es) detected.")
            insight.recommendations.append("Investigate product lifecycle and consider delist or targeted campaigns.")
            insight.supporting_refs.extend(slow_moving[:10])

        # confidence heuristics
        insight.confidence_score = 0.85 if metrics.get("near_expiry_count", 0) > 0 else 0.6
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 300))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"metrics": "dict", "promotion_recs": "list", "reallocation_recs": "list", "slow_moving": "list"}
