from __future__ import annotations
from typing import Any, Dict, List
import statistics
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class LogisticsOptimizationAgent(BaseAgent):
    name = "logistics_optimization"
    required_role = "logistics"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor:
            return {"results": [], "query_count": 0}
        if not specs:
            specs = [{"type": "deliveries_recent"}, {"type": "routes_performance"}]
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        delays: List[float] = []
        sla_breaches: List[Dict[str, Any]] = []
        route_stats: Dict[str, List[float]] = {}

        for spec, res in results:
            for row in res or []:
                try:
                    delay = row.get("delay_minutes")
                    route = row.get("route") or row.get("origin_to_dest")
                    fuel_cost = row.get("fuel_cost")
                    sla = row.get("sla_minutes")
                    if delay is not None:
                        d = float(delay)
                        delays.append(d)
                        if route:
                            route_stats.setdefault(route, []).append(d)
                        if sla is not None and d > float(sla):
                            sla_breaches.append({"delivery_id": row.get("delivery_id") or row.get("id"), "route": route, "delay": d, "sla": sla})
                except Exception:
                    continue

        avg_delay = statistics.mean(delays) if delays else 0.0
        route_summary = []
        for r, vals in route_stats.items():
            route_summary.append({"route": r, "avg_delay": round(statistics.mean(vals), 2), "p95": round(max(vals), 2)})

        metrics = {"avg_delay_minutes": round(avg_delay, 2), "sla_breach_count": len(sla_breaches)}
        return {"metrics": metrics, "sla_breaches": sla_breaches, "route_summary": route_summary}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        metrics = analysis.get("metrics") or {}
        sla_breaches = analysis.get("sla_breaches") or []
        route_summary = analysis.get("route_summary") or []

        insight.metrics.update(metrics)

        if sla_breaches:
            insight.findings.append(f"{len(sla_breaches)} delivery SLA breach(es) detected.")
            insight.supporting_refs.extend(sla_breaches[:10])
            insight.recommendations.append("Investigate recurring routes with the highest delays and optimize schedules.")

        if route_summary:
            top = sorted(route_summary, key=lambda x: -x.get("avg_delay", 0))[:5]
            insight.findings.append(f"Top slow routes: {', '.join(r['route'] for r in top)}")
            insight.supporting_refs.extend(top)
            insight.recommendations.append("Consider route consolidation and dynamic routing for high-delay legs.")

        insight.confidence_score = 0.75
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 300))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"metrics": "dict", "sla_breaches": "list", "route_summary": "list"}
