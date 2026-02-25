from __future__ import annotations
from typing import Any, Dict, List, Optional
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class RevenueStrategyAgent(BaseAgent):
    name = "revenue_strategy"
    required_role = "finance_manager"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor or not specs:
            # safe fallback: expect context contains `revenue_rows`
            rows = self.context.get("revenue_rows") or []
            return {"results": [({"type": "revenue_rows"}, rows)], "query_count": 1, "total_latency_ms": 0}
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        product_revenue: Dict[str, float] = {}
        customer_revenue: Dict[str, float] = {}
        total = 0.0
        errors: List[str] = []

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(res.get("error"))
                continue
            for row in res or []:
                try:
                    pid = str(row.get("product_id") or row.get("sku") or "unknown")
                    cust = str(row.get("customer_id") or row.get("customer") or "unknown")
                    rev = float(row.get("revenue") or row.get("amount") or 0)
                    product_revenue[pid] = product_revenue.get(pid, 0.0) + rev
                    customer_revenue[cust] = customer_revenue.get(cust, 0.0) + rev
                    total += rev
                except Exception:
                    errors.append("row_parse_error")

        # sort top contributors
        top_products = sorted(product_revenue.items(), key=lambda x: -x[1])[:10]
        top_customers = sorted(customer_revenue.items(), key=lambda x: -x[1])[:10]

        metrics = {"total_revenue": round(total, 2), "top_products_count": len(top_products), "top_customers_count": len(top_customers)}
        return {"metrics": metrics, "top_products": top_products, "top_customers": top_customers, "errors": errors}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        top_products = analysis.get("top_products", [])
        top_customers = analysis.get("top_customers", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(metrics)

        if top_products:
            insight.findings.append(f"Top product drives revenue: {top_products[0][0]} => {top_products[0][1]}")
            insight.recommendations.append("Prioritize inventory and promotion for top-performing products.")
        if top_customers:
            insight.findings.append(f"Top customer contributes: {top_customers[0][0]} => {top_customers[0][1]}")
            insight.recommendations.append("Consider tailored credit + retention programs for top customers.")

        # simple uplift scenario: 10% price increase on top 3 products
        uplift = 0.0
        for pid, rev in top_products[:3]:
            uplift += rev * 0.10
        insight.metrics["projected_uplift_10pct_top3"] = round(uplift, 2)

        if errors:
            insight.risks.append("partial_data: some revenue rows failed to parse")

        insight.confidence_score = 0.8 if not errors else 0.55
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 600)
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"metrics": "dict", "top_products": "list", "top_customers": "list"}
