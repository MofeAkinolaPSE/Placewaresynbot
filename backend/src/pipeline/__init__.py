"""
Enterprise Data Pipeline Module

Implements a 6-layer architecture for enterprise-grade data processing:
- Layer 1: Ingestion (raw persistence)
- Layer 2: Validation (schema checks)
- Layer 3: Normalization (config-driven mapping)
- Layer 4: Feature Computation (KPIs)
- Layer 5: Intelligence (risk scoring, insights)
- Layer 6: API/Consumption (read-only access)

All processing is:
- Deterministic: Same input → same output
- Idempotent: Reprocessing doesn't corrupt data
- Auditable: Full lineage tracking
- Configurable: No hardcoded domain logic
"""

from .base import (
    PipelineContext,
    PipelineLayer,
    PipelineResult,
    LayerError,
)
from .ingestion import IngestionLayer
from .validation import ValidationLayer
from .normalization import NormalizationLayer
from .feature import FeatureLayer
from .intelligence import IntelligenceLayer
from .orchestrator import PipelineOrchestrator

__all__ = [
    # Core abstractions
    "PipelineContext",
    "PipelineLayer",
    "PipelineResult",
    "LayerError",
    # Layers
    "IngestionLayer",
    "ValidationLayer",
    "NormalizationLayer",
    "FeatureLayer",
    "IntelligenceLayer",
    # Orchestration
    "PipelineOrchestrator",
]
