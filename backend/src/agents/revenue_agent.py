from __future__ import annotations
from typing import Any, Dict, List, Optional
import statistics
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query
from src.services.scenario_engine import ScenarioEngine, Lever, quick_scenarios


@register_agent
class RevenueStrategyAgent(BaseAgent):
    """Revenue Strategy Agent — accepts optional growth goal and decomposes
    into actionable strategies: new customer acquisition, price optimisation,
    and product mix expansion.  Produces scenario forecasts (base, optimistic,
    conservative) and weekly uplift targets."""

    name = "revenue_strategy"
    required_role = "finance_manager"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor or not specs:
            rows = self.context.get("revenue_rows") or []
            return {"results": [({"type": "revenue_rows"}, rows)], "query_count": 1, "total_latency_ms": 0}
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        product_revenue: Dict[str, Dict[str, float]] = {}
        customer_revenue: Dict[str, Dict[str, float]] = {}
        total = 0.0
        ar_reliable_customers: List[str] = []
        errors: List[str] = []

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(str(res.get("error")))
                continue
            spec_type = spec.get("type", "") if isinstance(spec, dict) else ""
            for row in res or []:
                try:
                    pid = str(row.get("product_id") or row.get("sku") or "unknown")
                    cust = str(row.get("customer_id") or row.get("customer") or "unknown")
                    rev = float(row.get("revenue") or row.get("amount") or 0)
                    cost = float(row.get("cost") or 0)
                    margin = float(row.get("margin_pct") or 0)
                    units = float(row.get("units") or row.get("quantity") or 0)

                    # Product stats
                    ps = product_revenue.setdefault(pid, {"revenue": 0.0, "cost": 0.0, "units": 0.0, "margin_pct": margin})
                    ps["revenue"] += rev
                    ps["cost"] += cost
                    ps["units"] += units

                    # Customer stats
                    cs = customer_revenue.setdefault(cust, {"revenue": 0.0, "invoice_count": 0})
                    cs["revenue"] += rev
                    cs["invoice_count"] += 1

                    total += rev

                    # AR reliability — customers with low overdue
                    days_overdue = row.get("days_overdue") or row.get("due_days")
                    if days_overdue is not None and int(days_overdue) <= 30 and cust not in ar_reliable_customers:
                        ar_reliable_customers.append(cust)
                except Exception:
                    errors.append("row_parse_error")

        # Sort top contributors
        top_products = sorted(product_revenue.items(), key=lambda x: -x[1]["revenue"])[:10]
        top_customers = sorted(customer_revenue.items(), key=lambda x: -x[1]["revenue"])[:10]

        # Identify margin headroom: products where margin > 25 % (room for price increase)
        margin_headroom = [
            (pid, stats) for pid, stats in product_revenue.items()
            if stats.get("margin_pct", 0) > 25
        ]

        # Identify underperforming SKUs (low revenue but positive units — expansion candidates)
        avg_rev = (total / len(product_revenue)) if product_revenue else 0
        expansion_candidates = [
            (pid, stats) for pid, stats in product_revenue.items()
            if stats["revenue"] < avg_rev * 0.5 and stats["units"] > 0
        ]

        metrics = {
            "total_revenue": round(total, 2),
            "product_count": len(product_revenue),
            "customer_count": len(customer_revenue),
            "ar_reliable_customers": len(ar_reliable_customers),
        }

        return {
            "metrics": metrics,
            "top_products": top_products,
            "top_customers": top_customers,
            "margin_headroom": margin_headroom[:10],
            "expansion_candidates": expansion_candidates[:10],
            "ar_reliable_customers": ar_reliable_customers[:20],
            "errors": errors,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        top_products = analysis.get("top_products", [])
        top_customers = analysis.get("top_customers", [])
        margin_headroom = analysis.get("margin_headroom", [])
        expansion_candidates = analysis.get("expansion_candidates", [])
        ar_reliable = analysis.get("ar_reliable_customers", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(metrics)

        total_revenue = metrics.get("total_revenue", 0)

        # ---------------------------------------------------------------
        # Goal decomposition
        # ---------------------------------------------------------------
        goal = self.context.get("goal_input") or {}
        target_pct = float(goal.get("target_pct", 15))
        timeframe_months = int(goal.get("timeframe_months", 6))
        target_uplift = total_revenue * (target_pct / 100)
        weekly_target = target_uplift / max(1, timeframe_months * 4.33)

        insight.metrics["goal_target_pct"] = target_pct
        insight.metrics["goal_timeframe_months"] = timeframe_months
        insight.metrics["required_total_uplift"] = round(target_uplift, 2)
        insight.metrics["required_weekly_uplift"] = round(weekly_target, 2)

        # ---------------------------------------------------------------
        # Strategy 1: New customer acquisition (target reliable-AR hospitals)
        # ---------------------------------------------------------------
        acq_uplift = target_uplift * 0.4  # 40 % from new customers
        insight.findings.append(
            f"Revenue goal: +{target_pct}% (₦{round(target_uplift, 0):,.0f}) over {timeframe_months} months."
        )
        if ar_reliable:
            insight.recommendations.append(
                f"Strategy 1 — Customer Acquisition: Target {len(ar_reliable)} reliable-AR customers "
                f"for expanded product range. Expected contribution: ₦{round(acq_uplift, 0):,.0f}."
            )
        else:
            insight.recommendations.append(
                "Strategy 1 — Customer Acquisition: Identify and onboard new hospital accounts. "
                f"Target contribution: ₦{round(acq_uplift, 0):,.0f}."
            )

        # ---------------------------------------------------------------
        # Strategy 2: Price optimisation (margin-headroom products)
        # ---------------------------------------------------------------
        price_uplift = target_uplift * 0.3  # 30 % from pricing
        if margin_headroom:
            candidates_str = ", ".join(pid for pid, _ in margin_headroom[:3])
            insight.recommendations.append(
                f"Strategy 2 — Price Optimisation: Increase prices 3-5% on high-margin SKUs "
                f"({candidates_str}). Expected contribution: ₦{round(price_uplift, 0):,.0f}."
            )
        else:
            insight.recommendations.append(
                "Strategy 2 — Price Optimisation: Limited margin headroom; focus on reducing "
                f"cost-of-goods instead. Target contribution: ₦{round(price_uplift, 0):,.0f}."
            )

        # ---------------------------------------------------------------
        # Strategy 3: Product mix expansion (underperforming SKUs)
        # ---------------------------------------------------------------
        mix_uplift = target_uplift * 0.3  # 30 % from product mix
        if expansion_candidates:
            exp_str = ", ".join(pid for pid, _ in expansion_candidates[:3])
            insight.recommendations.append(
                f"Strategy 3 — Product Mix: Push underperforming SKUs ({exp_str}) into "
                f"high-demand regions. Expected contribution: ₦{round(mix_uplift, 0):,.0f}."
            )
        else:
            insight.recommendations.append(
                "Strategy 3 — Product Mix: All SKUs performing above average. Focus on volume "
                f"increases. Target contribution: ₦{round(mix_uplift, 0):,.0f}."
            )

        # ---------------------------------------------------------------
        # Scenario forecasts — powered by ScenarioEngine
        # ---------------------------------------------------------------
        top_product_ids = [p for p, _ in top_products[:5]] if top_products else []
        # ar_reliable is a flat list of customer_id strings (see analyze()),
        # not (id, stats) tuples — unpacking each string as `c, _` blew up
        # with "too many values to unpack" for any id longer than 2 chars.
        ar_customer_ids = ar_reliable[:10] if ar_reliable else []
        total_cost = metrics.get("total_cost", 0.0)

        try:
            scenario_result = quick_scenarios(
                base_revenue=float(total_revenue),
                base_cost=float(total_cost),
                goal_pct=float(target_pct),
                timeframe_months=int(timeframe_months),
                top_products=top_product_ids,
                ar_reliable_customers=ar_customer_ids,
            )
            base_forecast = scenario_result.scenario_base
            optimistic_forecast = scenario_result.scenario_optimistic
            conservative_forecast = scenario_result.scenario_conservative
            insight.metrics["scenario_weekly_uplift_ngn"] = scenario_result.total_weekly_uplift_ngn
            insight.metrics["scenario_summary"] = scenario_result.summary
        except Exception as _sce:
            # Graceful degradation — keep simple inline math
            base_forecast = total_revenue
            optimistic_forecast = total_revenue + target_uplift
            conservative_forecast = total_revenue + target_uplift * 0.5

        insight.metrics["scenario_base"] = round(base_forecast, 2)
        insight.metrics["scenario_optimistic"] = round(optimistic_forecast, 2)
        insight.metrics["scenario_conservative"] = round(conservative_forecast, 2)

        insight.findings.append(
            f"Forecast scenarios: Base ₦{base_forecast:,.0f} | "
            f"Conservative ₦{conservative_forecast:,.0f} | "
            f"Optimistic ₦{optimistic_forecast:,.0f}."
        )

        # Top product/customer summaries
        if top_products:
            insight.findings.append(f"Top product: {top_products[0][0]} => ₦{top_products[0][1]['revenue']:,.0f}")
            insight.supporting_refs.extend([{"product_id": p, **s} for p, s in top_products[:5]])
        if top_customers:
            insight.findings.append(f"Top customer: {top_customers[0][0]} => ₦{top_customers[0][1]['revenue']:,.0f}")
            insight.supporting_refs.extend([{"customer_id": c, **s} for c, s in top_customers[:5]])

        # Weekly experiment suggestion
        insight.recommendations.append(
            f"Weekly experiment: Achieve ₦{round(weekly_target, 0):,.0f}/week uplift. "
            "Test regional promotions and bundle offers; measure conversion rate weekly."
        )

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
        return {
            "metrics": "dict (total_revenue, goal_*, scenario_*, required_weekly_uplift)",
            "top_products": "list[tuple(product_id, stats)]",
            "top_customers": "list[tuple(customer_id, stats)]",
            "scenarios": "base, optimistic, conservative revenue forecasts",
            "strategies": "3 decomposed strategies in recommendations",
        }
