from __future__ import annotations
from typing import Any, Dict, List
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class EnterpriseRiskAgent(BaseAgent):
    name = "enterprise_risk"
    required_role = "risk_officer"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor or not specs:
            return {"results": [], "query_count": 0, "total_latency_ms": 0}
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        risk_items: List[Dict[str, Any]] = []
        agg_score = 0.0
        count = 0
        errors: List[str] = []

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(res.get("error"))
                continue
            for row in res or []:
                try:
                    score = float(row.get("risk_score") or row.get("score") or 0)
                    category = row.get("category") or spec.get("type") or "unknown"
                    risk_items.append({"category": category, "score": score, "details": row})
                    agg_score += score
                    count += 1
                except Exception:
                    errors.append("row_parse_error")

        avg_score = (agg_score / count) if count else 0.0
        metrics = {"avg_risk_score": round(avg_score, 2), "risk_item_count": len(risk_items)}
        return {"metrics": metrics, "risk_items": risk_items, "errors": errors}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        risk_items = analysis.get("risk_items", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(metrics)

        if risk_items:
            # top risks by score
            top = sorted(risk_items, key=lambda r: -float(r.get("score", 0)))[:10]
            insight.findings.append(f"Top risk: {top[0]['category']} score={top[0]['score']}")
            insight.supporting_refs.extend(top)
            insight.recommendations.append("Prioritize mitigation for top risks and assign owners.")

        if metrics.get("avg_risk_score", 0) > 10:
            insight.risks.append("enterprise_risk_elevated")
            insight.recommendations.append("Initiate cross-functional risk review and escalate to execs.")

        if errors:
            insight.risks.append("partial_data: some risk queries failed")

        insight.confidence_score = 0.8 if not errors else 0.55
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 300)
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"metrics": "dict", "risk_items": "list"}
