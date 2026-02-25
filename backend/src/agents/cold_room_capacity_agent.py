from __future__ import annotations
from typing import Any, Dict, List
import datetime as dt
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class ColdRoomCapacityAgent(BaseAgent):
    name = "cold_room_capacity"
    required_role = "ops"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor:
            return {"results": [], "query_count": 0}
        if not specs:
            specs = [{"type": "cold_room_status_all"}]
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        threshold = float(self.context.get("cold_room_threshold", 0.85))
        warnings: List[Dict[str, Any]] = []
        forecasts: List[Dict[str, Any]] = []
        stats = {"rooms_monitored": 0, "rooms_over_threshold": 0}

        now = dt.datetime.utcnow()
        for spec, res in results:
            for row in res or []:
                try:
                    room_id = row.get("room_id") or row.get("id")
                    capacity = float(row.get("capacity") or row.get("max_capacity") or 0)
                    used = float(row.get("used_capacity") or row.get("current_load") or 0)
                    temp_c = row.get("temperature_c")
                    avg_daily_inflow = float(row.get("avg_daily_inflow") or 0)

                    if capacity <= 0:
                        continue

                    usage = used / capacity if capacity else 0.0
                    stats["rooms_monitored"] += 1
                    if usage >= threshold:
                        stats["rooms_over_threshold"] += 1
                        warnings.append({
                            "room_id": room_id,
                            "usage": round(usage, 3),
                            "used": used,
                            "capacity": capacity,
                            "temperature_c": temp_c,
                        })

                    # simple overflow forecasting: days until full at current avg inflow
                    days_to_full = None
                    if avg_daily_inflow > 0:
                        remaining = max(0.0, capacity - used)
                        days = remaining / avg_daily_inflow
                        days_to_full = int(days)
                        if days_to_full <= 14:
                            forecasts.append({"room_id": room_id, "days_to_full": days_to_full, "remaining": remaining})
                except Exception:
                    continue

        return {"stats": stats, "warnings": warnings, "forecasts": forecasts}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        stats = analysis.get("stats") or {}
        warnings = analysis.get("warnings") or []
        forecasts = analysis.get("forecasts") or []

        insight.metrics.update(stats)

        if warnings:
            insight.findings.append(f"{len(warnings)} cold-room(s) over capacity threshold.")
            insight.supporting_refs.extend(warnings[:10])
            insight.recommendations.append("Redistribute stock or accelerate dispatch from affected rooms.")
            insight.recommendations.append("Increase monitoring cadence and validate temperature logs.")

        if forecasts:
            insight.findings.append(f"{len(forecasts)} cold-room(s) forecasted to reach capacity within 14 days.")
            insight.supporting_refs.extend(forecasts[:10])
            insight.recommendations.append("Plan inter-warehouse transfers or temporary storage expansions.")

        insight.confidence_score = 0.8 if stats.get("rooms_monitored", 0) > 0 else 0.5
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 300))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"stats": "dict", "warnings": "list", "forecasts": "list"}
