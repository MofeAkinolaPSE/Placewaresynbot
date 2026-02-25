from __future__ import annotations
from typing import Any, Dict, List
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class ProcessOptimizationAgent(BaseAgent):
    name = "process_optimization"
    required_role = "ops_lead"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor or not specs:
            return {"results": [], "query_count": 0}
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        bottlenecks: List[Dict[str, Any]] = []
        stats: Dict[str, float] = {"avg_throughput": 0.0, "p99_latency": 0.0}
        total = 0

        for spec, res in results:
            for row in res or []:
                try:
                    total += 1
                    throughput = float(row.get("throughput") or 0)
                    latency = float(row.get("latency_ms") or 0)
                    stats["avg_throughput"] += throughput
                    stats["p99_latency"] = max(stats["p99_latency"], latency)
                    if latency > 1000 or throughput < 1:
                        bottlenecks.append({"stage": row.get("stage"), "latency": latency, "throughput": throughput})
                except Exception:
                    continue

        if total:
            stats["avg_throughput"] = stats["avg_throughput"] / total

        return {"stats": stats, "bottlenecks": bottlenecks}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        stats = analysis.get("stats", {})
        bottlenecks = analysis.get("bottlenecks", [])

        insight = Insight()
        insight.metrics.update(stats)

        if bottlenecks:
            insight.findings.append(f"Detected {len(bottlenecks)} bottleneck(s) in the process pipeline.")
            insight.supporting_refs.extend(bottlenecks[:5])
            insight.recommendations.append("Target the highest latency stages for capacity and batching improvements.")
            insight.confidence_score = 0.75
        else:
            insight.findings.append("No significant process bottlenecks detected.")
            insight.confidence_score = 0.6

        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 300)
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"stats": "dict", "bottlenecks": "list"}
