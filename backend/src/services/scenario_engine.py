"""
Scenario Engine

Parameterised revenue scenario modelling.  Accepts a base revenue/cost figure
and a list of business levers, returns ranked weekly-uplift initiatives with
NGN amounts, target account lists, and a confidence rating.

Design principles:
    - Pure Python, no ML dependencies — easy to extend later
    - Works with zero data (returns sensible zeroes) but becomes useful once
      customer master and product revenue data are loaded
    - Levers are typed (price, volume, mix, cost_reduction) and can be filtered
      to specific product or customer subsets

Public API:
    ScenarioEngine.run(base_revenue, base_cost, levers, context) -> ScenarioResult
    quick_scenarios(base_revenue, base_cost, goal_pct, timeframe_months) -> ScenarioResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Lever:
    """A single modelling lever applied to a revenue/cost base.

    Attributes:
        name:            Human-readable lever description
        lever_type:      One of: price | volume | mix | cost_reduction
        magnitude_pct:   Expected % change (e.g. 0.05 = 5 %)
        product_filter:  Optional list of product_ids / SKUs this lever applies to
        target_accounts: Optional list of customer_ids to focus on
        revenue_base:    Revenue subset this lever applies to (overrides total if set)
        confidence:      high | medium | low — caller's confidence in achievability
    """
    name: str
    lever_type: str  # price | volume | mix | cost_reduction
    magnitude_pct: float
    product_filter: List[str] = field(default_factory=list)
    target_accounts: List[str] = field(default_factory=list)
    revenue_base: Optional[float] = None  # narrowed base; falls back to total
    confidence: str = "medium"


@dataclass
class Initiative:
    """A ranked output initiative with NGN weekly uplift estimate."""
    name: str
    lever_type: str
    weekly_uplift_ngn: float
    annual_uplift_ngn: float
    magnitude_pct: float
    target_accounts: List[str]
    product_filter: List[str]
    confidence: str
    rationale: str


@dataclass
class ScenarioResult:
    """Full output of a scenario run."""
    base_revenue: float
    base_cost: float
    base_margin_pct: float
    scenario_base: float          # status-quo annual
    scenario_conservative: float  # 50 % lever effectiveness
    scenario_optimistic: float    # 100 % lever effectiveness
    total_weekly_uplift_ngn: float
    initiatives: List[Initiative]
    summary: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ScenarioEngine:
    """Applies a list of levers to a revenue/cost base and returns a ScenarioResult."""

    WEEKS_PER_YEAR = 52

    def run(
        self,
        base_revenue: float,
        base_cost: float,
        levers: List[Lever],
        context: Optional[Dict[str, Any]] = None,
    ) -> ScenarioResult:
        context = context or {}
        base_margin_pct = (
            round((base_revenue - base_cost) / base_revenue * 100, 2)
            if base_revenue > 0 else 0.0
        )

        initiatives: List[Initiative] = []

        for lever in levers:
            effective_base = lever.revenue_base if lever.revenue_base is not None else base_revenue
            annual_uplift = self._calc_annual_uplift(lever, effective_base, base_cost)
            weekly_uplift = round(annual_uplift / self.WEEKS_PER_YEAR, 2)

            rationale = self._build_rationale(lever, effective_base, annual_uplift, weekly_uplift)

            initiatives.append(Initiative(
                name=lever.name,
                lever_type=lever.lever_type,
                weekly_uplift_ngn=weekly_uplift,
                annual_uplift_ngn=round(annual_uplift, 2),
                magnitude_pct=lever.magnitude_pct,
                target_accounts=lever.target_accounts[:20],
                product_filter=lever.product_filter[:20],
                confidence=lever.confidence,
                rationale=rationale,
            ))

        # Sort: high-confidence largest uplift first
        conf_rank = {"high": 0, "medium": 1, "low": 2}
        initiatives.sort(key=lambda i: (conf_rank.get(i.confidence, 9), -i.weekly_uplift_ngn))

        total_annual = sum(i.annual_uplift_ngn for i in initiatives)
        total_weekly = round(total_annual / self.WEEKS_PER_YEAR, 2)

        scenario_base = base_revenue
        scenario_optimistic = base_revenue + total_annual
        scenario_conservative = base_revenue + total_annual * 0.5

        # Summary sentence
        top = initiatives[0] if initiatives else None
        if top:
            summary = (
                f"Running {len(initiatives)} lever(s) on ₦{base_revenue:,.0f} revenue base. "
                f"Top initiative: '{top.name}' → ₦{top.weekly_uplift_ngn:,.0f}/week uplift. "
                f"Optimistic annual: ₦{scenario_optimistic:,.0f} | "
                f"Conservative annual: ₦{scenario_conservative:,.0f}."
            )
        else:
            summary = "No levers provided — base scenario only."

        return ScenarioResult(
            base_revenue=round(base_revenue, 2),
            base_cost=round(base_cost, 2),
            base_margin_pct=base_margin_pct,
            scenario_base=round(scenario_base, 2),
            scenario_conservative=round(scenario_conservative, 2),
            scenario_optimistic=round(scenario_optimistic, 2),
            total_weekly_uplift_ngn=total_weekly,
            initiatives=initiatives,
            summary=summary,
        )

    # ------------------------------------------------------------------

    def _calc_annual_uplift(self, lever: Lever, effective_base: float, base_cost: float) -> float:
        if lever.lever_type == "price":
            # Price increase on revenue — direct revenue uplift
            return effective_base * lever.magnitude_pct
        elif lever.lever_type == "volume":
            # Volume increase — revenue uplift proportional to magnitude
            return effective_base * lever.magnitude_pct
        elif lever.lever_type == "mix":
            # Product-mix improvement — conservative 60 % of raw uplift (mix shifts are slower)
            return effective_base * lever.magnitude_pct * 0.6
        elif lever.lever_type == "cost_reduction":
            # Cost reduction — uplift = cost saving = base_cost × magnitude
            return base_cost * lever.magnitude_pct
        else:
            logger.warning(f"Unknown lever_type: {lever.lever_type}")
            return 0.0

    def _build_rationale(
        self,
        lever: Lever,
        effective_base: float,
        annual_uplift: float,
        weekly_uplift: float,
    ) -> str:
        accounts_str = (
            f" for {len(lever.target_accounts)} target account(s)"
            if lever.target_accounts else ""
        )
        products_str = (
            f" on SKU(s) {', '.join(lever.product_filter[:3])}"
            if lever.product_filter else ""
        )
        return (
            f"{lever.lever_type.replace('_', ' ').title()} lever of "
            f"{lever.magnitude_pct * 100:.1f}%{products_str}{accounts_str}. "
            f"Applied to ₦{effective_base:,.0f} base → "
            f"₦{weekly_uplift:,.0f}/week | ₦{annual_uplift:,.0f}/year."
        )


# ---------------------------------------------------------------------------
# Convenience factory for standard 3-scenario output
# ---------------------------------------------------------------------------

def quick_scenarios(
    base_revenue: float,
    base_cost: float,
    goal_pct: float = 15.0,
    timeframe_months: int = 6,
    top_products: Optional[List[str]] = None,
    ar_reliable_customers: Optional[List[str]] = None,
) -> ScenarioResult:
    """Build three standard levers (acquisition, price, mix) and run them.

    Replaces the ad-hoc inline math in RevenueStrategyAgent.generate_insights().
    """
    levers = [
        Lever(
            name="Customer Acquisition — reliable-AR accounts",
            lever_type="volume",
            magnitude_pct=goal_pct / 100 * 0.4,  # 40 % of goal from new volume
            target_accounts=ar_reliable_customers or [],
            confidence="medium",
        ),
        Lever(
            name="Price Optimisation — high-margin SKUs",
            lever_type="price",
            magnitude_pct=0.04,  # 4 % price increase on high-margin products
            product_filter=top_products or [],
            confidence="high" if top_products else "low",
        ),
        Lever(
            name="Product Mix Expansion — underperforming SKUs",
            lever_type="mix",
            magnitude_pct=goal_pct / 100 * 0.3,  # 30 % of goal from mix improvement
            product_filter=top_products[-3:] if top_products else [],
            confidence="low",
        ),
    ]
    engine = ScenarioEngine()
    return engine.run(base_revenue, base_cost, levers)
