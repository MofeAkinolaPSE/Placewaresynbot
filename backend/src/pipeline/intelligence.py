"""
Layer 5: Intelligence Layer

Responsibilities:
- Risk scoring
- Insight generation
- Trigger evaluation
- Workflow state updates

Rules:
- Risk scoring must use configurable weights
- No hardcoded thresholds
- All rules must defer to config
- All decisions must be logged
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from enum import Enum
import logging

from .base import (
    PipelineContext,
    PipelineLayer,
    PipelineResult,
    LayerStatus,
)
from .feature import FeatureOutput, ComputedFeature


logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level classifications."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InsightType(Enum):
    """Types of insights that can be generated."""
    ANOMALY = "anomaly"
    TREND = "trend"
    THRESHOLD = "threshold"
    CORRELATION = "correlation"
    RECOMMENDATION = "recommendation"


@dataclass
class RiskScore:
    """A risk assessment."""
    category: str
    score: float  # 0.0 to 1.0
    level: RiskLevel
    factors: list[dict[str, Any]]
    recommendations: list[str]


@dataclass
class Insight:
    """A generated insight."""
    insight_type: InsightType
    title: str
    description: str
    severity: str  # "info", "warning", "alert"
    data: dict[str, Any]
    recommendations: list[str]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


@dataclass
class Trigger:
    """A triggered action/notification."""
    trigger_name: str
    condition: str
    matched: bool
    action: str
    priority: int
    metadata: dict[str, Any]


@dataclass
class IntelligenceOutput:
    """Output from the intelligence layer."""
    ingestion_id: str
    batch_id: str
    risk_scores: list[RiskScore]
    insights: list[Insight]
    triggers: list[Trigger]
    overall_risk_level: RiskLevel
    normalized_records: dict[str, list[dict[str, Any]]]  # Pass through


@dataclass
class RiskRule:
    """Rule for computing risk scores."""
    name: str
    category: str
    weight: float
    evaluate: Callable[[list[ComputedFeature], dict[str, Any]], tuple[float, list[dict]]]
    threshold_low: float = 0.3
    threshold_medium: float = 0.6
    threshold_high: float = 0.8


@dataclass
class TriggerRule:
    """Rule for evaluating triggers."""
    name: str
    condition: Callable[[list[ComputedFeature], dict[str, Any]], bool]
    action: str
    priority: int = 0
    description: str = ""


class IntelligenceLayer(PipelineLayer[FeatureOutput, IntelligenceOutput]):
    """Layer 5: Intelligence
    
    Performs risk scoring, insight generation, and trigger evaluation.
    """
    
    def __init__(
        self,
        risk_rules: dict[str, RiskRule] | None = None,
        trigger_rules: dict[str, TriggerRule] | None = None,
        insight_generators: list[Callable] | None = None,
    ):
        """Initialize intelligence layer.
        
        Args:
            risk_rules: Map of rule name -> RiskRule.
            trigger_rules: Map of trigger name -> TriggerRule.
            insight_generators: List of insight generator functions.
        """
        self._risk_rules = risk_rules or {}
        self._trigger_rules = trigger_rules or {}
        self._insight_generators = insight_generators or []
        self._register_defaults()
    
    @property
    def name(self) -> str:
        return "intelligence"
    
    def _register_defaults(self) -> None:
        """Register default rules."""
        # Data quality risk
        self._risk_rules.setdefault("data_quality", RiskRule(
            name="data_quality",
            category="data",
            weight=0.3,
            evaluate=self._evaluate_data_quality_risk,
        ))
        
        # Volume anomaly detection
        self._risk_rules.setdefault("volume_anomaly", RiskRule(
            name="volume_anomaly",
            category="operations",
            weight=0.2,
            evaluate=self._evaluate_volume_anomaly,
        ))
        
        # Low inventory trigger
        self._trigger_rules.setdefault("low_inventory", TriggerRule(
            name="low_inventory",
            condition=lambda features, agg: any(
                f.name == "inventory_value" and f.value < 1000
                for f in features
            ),
            action="notify_procurement",
            priority=2,
            description="Inventory value below threshold",
        ))
    
    def _evaluate_data_quality_risk(
        self,
        features: list[ComputedFeature],
        aggregates: dict[str, Any],
    ) -> tuple[float, list[dict]]:
        """Evaluate data quality risk."""
        factors = []
        score = 0.0
        
        # Check for empty datasets
        for dataset, agg in aggregates.items():
            if agg.get("count", 0) == 0:
                factors.append({
                    "factor": "empty_dataset",
                    "dataset": dataset,
                    "impact": 0.2,
                })
                score += 0.2
        
        # Normalize score to 0-1 range
        score = min(score, 1.0)
        
        return score, factors
    
    def _evaluate_volume_anomaly(
        self,
        features: list[ComputedFeature],
        aggregates: dict[str, Any],
    ) -> tuple[float, list[dict]]:
        """Evaluate volume anomaly risk."""
        factors = []
        score = 0.0
        
        # Check for unusually low record counts
        for feature in features:
            if feature.name == "record_count" and feature.value < 10:
                factors.append({
                    "factor": "low_record_count",
                    "value": feature.value,
                    "impact": 0.3,
                })
                score += 0.3
        
        return min(score, 1.0), factors
    
    def _score_to_level(
        self,
        score: float,
        low: float = 0.3,
        medium: float = 0.6,
        high: float = 0.8,
    ) -> RiskLevel:
        """Convert numeric score to risk level."""
        if score >= high:
            return RiskLevel.CRITICAL
        elif score >= medium:
            return RiskLevel.HIGH
        elif score >= low:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW
    
    def _compute_risk_scores(
        self,
        features: list[ComputedFeature],
        aggregates: dict[str, Any],
    ) -> list[RiskScore]:
        """Compute all risk scores."""
        scores: list[RiskScore] = []
        
        for rule in self._risk_rules.values():
            try:
                score_value, factors = rule.evaluate(features, aggregates)
                level = self._score_to_level(
                    score_value,
                    rule.threshold_low,
                    rule.threshold_medium,
                    rule.threshold_high,
                )
                
                # Generate recommendations based on level
                recommendations = []
                if level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                    recommendations.append(f"Review {rule.category} metrics urgently")
                elif level == RiskLevel.MEDIUM:
                    recommendations.append(f"Monitor {rule.category} trends")
                
                scores.append(RiskScore(
                    category=rule.category,
                    score=score_value,
                    level=level,
                    factors=factors,
                    recommendations=recommendations,
                ))
            except Exception as e:
                logger.warning(f"Failed to compute risk for {rule.name}: {e}")
        
        return scores
    
    def _evaluate_triggers(
        self,
        features: list[ComputedFeature],
        aggregates: dict[str, Any],
    ) -> list[Trigger]:
        """Evaluate all trigger rules."""
        triggers: list[Trigger] = []
        
        for rule in self._trigger_rules.values():
            try:
                matched = rule.condition(features, aggregates)
                triggers.append(Trigger(
                    trigger_name=rule.name,
                    condition=rule.description,
                    matched=matched,
                    action=rule.action if matched else "",
                    priority=rule.priority if matched else 0,
                    metadata={"description": rule.description},
                ))
            except Exception as e:
                logger.warning(f"Failed to evaluate trigger {rule.name}: {e}")
        
        return triggers
    
    def _generate_insights(
        self,
        features: list[ComputedFeature],
        aggregates: dict[str, Any],
        risk_scores: list[RiskScore],
    ) -> list[Insight]:
        """Generate insights from computed data."""
        insights: list[Insight] = []
        
        # Generate threshold insights
        for feature in features:
            if feature.category == "finance" and feature.value > 0:
                insights.append(Insight(
                    insight_type=InsightType.THRESHOLD,
                    title=f"{feature.name.replace('_', ' ').title()} Summary",
                    description=f"Current {feature.name}: {feature.value:,.2f} {feature.unit}",
                    severity="info",
                    data={"feature": feature.name, "value": feature.value},
                    recommendations=[],
                ))
        
        # Generate risk insights
        high_risks = [s for s in risk_scores if s.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
        for risk in high_risks:
            insights.append(Insight(
                insight_type=InsightType.ANOMALY,
                title=f"High Risk: {risk.category.title()}",
                description=f"Risk score {risk.score:.2f} in {risk.category}",
                severity="alert",
                data={"category": risk.category, "score": risk.score, "factors": risk.factors},
                recommendations=risk.recommendations,
            ))
        
        # Run custom insight generators
        for generator in self._insight_generators:
            try:
                custom_insights = generator(features, aggregates, risk_scores)
                insights.extend(custom_insights)
            except Exception as e:
                logger.warning(f"Custom insight generator failed: {e}")
        
        return insights
    
    def _compute_overall_risk(
        self,
        risk_scores: list[RiskScore],
    ) -> RiskLevel:
        """Compute overall risk level."""
        if not risk_scores:
            return RiskLevel.LOW
        
        # Use max risk level
        max_level = max(r.level.value for r in risk_scores)
        return RiskLevel(max_level)
    
    def _process(
        self,
        input_data: FeatureOutput,
        context: PipelineContext,
    ) -> PipelineResult[IntelligenceOutput]:
        """Process intelligence layer."""
        # Compute risk scores
        risk_scores = self._compute_risk_scores(
            input_data.features,
            input_data.aggregates,
        )
        
        # Evaluate triggers
        triggers = self._evaluate_triggers(
            input_data.features,
            input_data.aggregates,
        )
        
        # Generate insights
        insights = self._generate_insights(
            input_data.features,
            input_data.aggregates,
            risk_scores,
        )
        
        # Compute overall risk
        overall_risk = self._compute_overall_risk(risk_scores)
        
        # Log triggered actions
        matched_triggers = [t for t in triggers if t.matched]
        for trigger in matched_triggers:
            context.add_audit_entry(
                layer=self.name,
                action="trigger_fired",
                details={
                    "trigger": trigger.trigger_name,
                    "action": trigger.action,
                    "priority": trigger.priority,
                },
            )
        
        # Build summary
        summary = {
            "risk_scores_computed": len(risk_scores),
            "triggers_matched": len(matched_triggers),
            "insights_generated": len(insights),
            "overall_risk": overall_risk.value,
        }
        
        context.add_lineage(self.name, summary)
        
        output = IntelligenceOutput(
            ingestion_id=input_data.ingestion_id,
            batch_id=input_data.batch_id,
            risk_scores=risk_scores,
            insights=insights,
            triggers=triggers,
            overall_risk_level=overall_risk,
            normalized_records=input_data.normalized_records,
        )
        
        return PipelineResult(
            status=LayerStatus.SUCCEEDED,
            data=output,
            rows_input=len(input_data.features),
            rows_output=len(risk_scores) + len(insights) + len(triggers),
        )
