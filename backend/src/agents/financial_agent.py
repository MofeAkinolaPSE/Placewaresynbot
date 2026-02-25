from __future__ import annotations
from typing import Any, Dict, List, Optional
from decimal import Decimal
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class FinancialAnalystAgent(BaseAgent):
    name = "financial_analyst"
    required_role = "finance_analyst"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs")
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor or not specs:
            return {"results": [], "query_count": 0, "total_latency_ms": 0}
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        ar_buckets: Dict[str, float] = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
        product_stats: Dict[str, Dict[str, float]] = {}
        total_revenue = 0.0
        total_cost = 0.0
        errors: List[str] = []

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(f"spec={spec}: {res.get('error')}")
                continue
            try:
                for row in res or []:
                    if not isinstance(row, dict):
                        continue
                    # Accounts receivable rows
                    if row.get("type") == "ar" or "due_days" in row or "days_overdue" in row:
                        due = row.get("due_days") or row.get("days_overdue") or 0
                        try:
                            amt = float(row.get("amount") or row.get("balance") or 0)
                        except Exception:
                            amt = 0.0
                        if due <= 30:
                            ar_buckets["0-30"] += amt
                        elif due <= 60:
                            ar_buckets["31-60"] += amt
                        elif due <= 90:
                            ar_buckets["61-90"] += amt
                        else:
                            ar_buckets["90+"] += amt

                    # Sales / product profitability rows
                    if "product_id" in row and ("revenue" in row or "cost" in row):
                        pid = str(row.get("product_id"))
                        rev = float(row.get("revenue") or 0)
                        cost = float(row.get("cost") or 0)
                        total_revenue += rev
                        total_cost += cost
                        stat = product_stats.setdefault(pid, {"revenue": 0.0, "cost": 0.0, "units": 0})
                        stat["revenue"] += rev
                        stat["cost"] += cost
                        stat["units"] += float(row.get("units") or 0)

            except Exception:
                errors.append(f"failed to parse result for spec={spec}")

        # compute product margins
        for pid, stat in product_stats.items():
            rev = stat.get("revenue", 0.0)
            cost = stat.get("cost", 0.0)
            margin = ((rev - cost) / rev * 100.0) if rev else 0.0
            stat["margin_pct"] = round(margin, 2)

        overall_margin = ((total_revenue - total_cost) / total_revenue * 100.0) if total_revenue else 0.0

        # detect margin compression: simple heuristic comparing top product margins
        compressed_products = [p for p, s in product_stats.items() if s.get("margin_pct", 0) < 10]

        metrics = {
            "ar_buckets": ar_buckets,
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "overall_margin_pct": round(overall_margin, 2),
            "compressed_product_count": len(compressed_products),
        }

        return {
            "metrics": metrics,
            "product_stats": product_stats,
            "compressed_products": compressed_products,
            "errors": errors,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        product_stats = analysis.get("product_stats", {})
        compressed = analysis.get("compressed_products", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(metrics)

        # AR findings
        ar = metrics.get("ar_buckets", {})
        if ar and ar.get("90+", 0) > 0:
            insight.findings.append(f"High overdue AR: {round(ar.get('90+',0),2)} in 90+ days bucket")
            insight.recommendations.append("Review credit terms for customers in 90+ AR bucket and escalate collections.")

        # Margin findings
        overall_margin = metrics.get("overall_margin_pct", 0.0)
        if overall_margin < 15:
            insight.risks.append("overall_margin_compression")
            insight.recommendations.append("Investigate pricing and supplier costs; consider repricing or promotional adjustments.")

        if compressed:
            insight.findings.append(f"{len(compressed)} products with margin < 10%")
            insight.supporting_refs.extend([{"product_id": p, **product_stats.get(p, {})} for p in compressed[:10]])

        if errors:
            insight.risks.append("partial_data: some finance queries failed")
            insight.supporting_refs.append({"errors": errors})

        insight.confidence_score = 0.85 if not errors else 0.6
        insight.execution_metadata["query_count"] = metrics.get("query_count", 0)

        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 300)
        if cache is None:
            return
        cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "metrics": "dict",
            "product_stats": "dict",
            "compressed_products": "list[str]",
        }
