from __future__ import annotations
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from datetime import datetime


class InsightModel(BaseModel):
    metrics: Dict[str, Any] = Field(default_factory=dict)
    findings: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    supporting_refs: List[Dict[str, Any]] = Field(default_factory=list)
    execution_metadata: Dict[str, Any] = Field(default_factory=lambda: {
        "query_count": 0,
        "latency_ms": 0,
        "timestamp": datetime.utcnow().isoformat(),
    })

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_dataclass(cls, obj: Any) -> "InsightModel":
        # A simple adapter to convert the dataclass `Insight` to pydantic model
        data = getattr(obj, "__dict__", {})
        # fallback: try .dict()
        if not data and hasattr(obj, "dict"):
            data = obj.dict()
        return cls(**data)


__all__ = ["InsightModel"]
