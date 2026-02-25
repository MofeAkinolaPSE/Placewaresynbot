from __future__ import annotations
import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Insight:
    metrics: Dict[str, Any] = field(default_factory=dict)
    findings: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    supporting_refs: List[Dict[str, Any]] = field(default_factory=list)
    execution_metadata: Dict[str, Any] = field(default_factory=lambda: {
        "query_count": 0,
        "latency_ms": 0,
        "timestamp": datetime.utcnow().isoformat(),
    })


class BaseAgent(abc.ABC):
    """Abstract base class for domain agents.

    Concrete agents should implement the minimal lifecycle:
      - collect_data()
      - analyze()
      - generate_insights()
      - write_cache()
      - get_output_schema()

    The `run()` helper orchestrates the lifecycle and populates
    execution metadata (latency_ms).
    """

    name: str = "base_agent"
    required_role: Optional[str] = None

    def __init__(self, context: Optional[Dict[str, Any]] = None) -> None:
        self.context = context or {}

    @abc.abstractmethod
    def collect_data(self) -> Any:
        raise NotImplementedError()

    @abc.abstractmethod
    def analyze(self, data: Any) -> Any:
        raise NotImplementedError()

    @abc.abstractmethod
    def generate_insights(self, analysis: Any) -> Insight:
        raise NotImplementedError()

    @abc.abstractmethod
    def write_cache(self, insight: Insight) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_output_schema(self) -> Dict[str, Any]:
        raise NotImplementedError()

    def run(self) -> Insight:
        start = datetime.utcnow()
        data = self.collect_data()
        analysis = self.analyze(data)
        insight = self.generate_insights(analysis)
        try:
            self.write_cache(insight)
        except Exception:
            # Cache write should not stop agent execution; surface in metadata
            insight.execution_metadata.setdefault("cache_write_error", True)
        latency = int((datetime.utcnow() - start).total_seconds() * 1000)
        insight.execution_metadata.setdefault("latency_ms", latency)
        return insight
