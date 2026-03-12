"""
Layer 4: Feature Computation Layer

Responsibilities:
- Compute KPIs
- Aggregate metrics
- Derive calculated fields

Rules:
- KPI formulas must not live inside agents
- KPI definitions must be registered modules
- Feature computation must be deterministic
- No side effects
"""

from dataclasses import dataclass, field
from typing import Any, Callable
import logging

from .base import (
    PipelineContext,
    PipelineLayer,
    PipelineResult,
    LayerStatus,
)
from .normalization import NormalizationOutput


logger = logging.getLogger(__name__)


@dataclass
class KPIDefinition:
    """Definition of a KPI to compute."""
    name: str
    description: str
    dataset: str | None  # None for cross-dataset KPIs
    compute: Callable[[list[dict]], Any]
    unit: str = ""
    category: str = "default"


@dataclass
class ComputedFeature:
    """A single computed feature/KPI."""
    name: str
    value: Any
    unit: str
    category: str
    dataset: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureOutput:
    """Output from the feature layer."""
    ingestion_id: str
    batch_id: str
    features: list[ComputedFeature]
    aggregates: dict[str, Any]
    normalized_records: dict[str, list[dict[str, Any]]]  # Pass through for next layer


class FeatureLayer(PipelineLayer[NormalizationOutput, FeatureOutput]):
    """Layer 4: Feature Computation
    
    Computes KPIs and derived metrics from normalized records.
    """
    
    def __init__(
        self,
        kpi_registry: dict[str, KPIDefinition] | None = None,
    ):
        """Initialize feature layer.
        
        Args:
            kpi_registry: Map of KPI name -> KPIDefinition.
        """
        self._kpi_registry = kpi_registry or {}
        # Register default KPIs
        self._register_defaults()
    
    @property
    def name(self) -> str:
        return "feature_computation"
    
    def _register_defaults(self) -> None:
        """Register default KPI definitions."""
        # Record count per dataset
        self._kpi_registry.setdefault("record_count", KPIDefinition(
            name="record_count",
            description="Total record count",
            dataset=None,
            compute=lambda records: len(records),
            unit="records",
            category="volume",
        ))
        
        # AR totals
        self._kpi_registry.setdefault("ar_total", KPIDefinition(
            name="ar_total",
            description="Total accounts receivable",
            dataset="ar",
            compute=lambda records: sum(
                float(r.get("amount") or 0) for r in records
            ),
            unit="currency",
            category="finance",
        ))
        
        # Inventory value
        self._kpi_registry.setdefault("inventory_value", KPIDefinition(
            name="inventory_value",
            description="Total inventory value",
            dataset="inventory",
            compute=lambda records: sum(
                (float(r.get("quantity") or 0) * float(r.get("price") or 0))
                for r in records
            ),
            unit="currency",
            category="inventory",
        ))
        
        # Customer count
        self._kpi_registry.setdefault("customer_count", KPIDefinition(
            name="customer_count",
            description="Total customer count",
            dataset="customers",
            compute=lambda records: len(records),
            unit="customers",
            category="crm",
        ))
        
        # Active customer ratio
        self._kpi_registry.setdefault("active_customer_ratio", KPIDefinition(
            name="active_customer_ratio",
            description="Percentage of active customers",
            dataset="customers",
            compute=lambda records: (
                sum(1 for r in records if r.get("status") == "active") / len(records) * 100
                if records else 0
            ),
            unit="%",
            category="crm",
        ))
    
    def register_kpi(self, kpi: KPIDefinition) -> None:
        """Register a custom KPI definition."""
        self._kpi_registry[kpi.name] = kpi
    
    def _compute_kpi(
        self,
        kpi: KPIDefinition,
        records_by_dataset: dict[str, list[dict]],
    ) -> ComputedFeature | None:
        """Compute a single KPI."""
        try:
            if kpi.dataset:
                records = records_by_dataset.get(kpi.dataset, [])
            else:
                # Combine all records for cross-dataset KPIs
                records = []
                for ds_records in records_by_dataset.values():
                    records.extend(ds_records)
            
            value = kpi.compute(records)
            
            return ComputedFeature(
                name=kpi.name,
                value=value,
                unit=kpi.unit,
                category=kpi.category,
                dataset=kpi.dataset,
                metadata={"description": kpi.description},
            )
        except Exception as e:
            logger.warning(f"Failed to compute KPI {kpi.name}: {e}")
            return None
    
    def _compute_aggregates(
        self,
        records_by_dataset: dict[str, list[dict]],
    ) -> dict[str, Any]:
        """Compute aggregate statistics."""
        aggregates: dict[str, Any] = {}
        
        for dataset, records in records_by_dataset.items():
            if not records:
                continue
            
            ds_agg = {
                "count": len(records),
                "fields": list(records[0].keys()) if records else [],
            }
            
            # Numeric field aggregates
            for key in records[0].keys():
                values = [r.get(key) for r in records if r.get(key) is not None]
                numeric_values = []
                for v in values:
                    try:
                        numeric_values.append(float(v))
                    except (ValueError, TypeError):
                        continue
                
                if numeric_values:
                    ds_agg[f"{key}_sum"] = sum(numeric_values)
                    ds_agg[f"{key}_avg"] = sum(numeric_values) / len(numeric_values)
                    ds_agg[f"{key}_min"] = min(numeric_values)
                    ds_agg[f"{key}_max"] = max(numeric_values)
            
            aggregates[dataset] = ds_agg
        
        return aggregates
    
    def _process(
        self,
        input_data: NormalizationOutput,
        context: PipelineContext,
    ) -> PipelineResult[FeatureOutput]:
        """Process feature computation."""
        features: list[ComputedFeature] = []
        
        # Compute each registered KPI
        for kpi in self._kpi_registry.values():
            feature = self._compute_kpi(kpi, input_data.normalized_records)
            if feature is not None:
                features.append(feature)
        
        # Compute aggregates
        aggregates = self._compute_aggregates(input_data.normalized_records)
        
        # Build summary
        summary = {
            "kpis_computed": len(features),
            "kpi_names": [f.name for f in features],
            "aggregates_by_dataset": list(aggregates.keys()),
        }
        
        context.add_lineage(self.name, summary)
        
        total_records = sum(len(r) for r in input_data.normalized_records.values())
        
        output = FeatureOutput(
            ingestion_id=input_data.ingestion_id,
            batch_id=input_data.batch_id,
            features=features,
            aggregates=aggregates,
            normalized_records=input_data.normalized_records,
        )
        
        return PipelineResult(
            status=LayerStatus.SUCCEEDED,
            data=output,
            rows_input=total_records,
            rows_output=len(features),
        )
