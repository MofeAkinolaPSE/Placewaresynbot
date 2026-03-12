"""
Pipeline Orchestrator

Coordinates execution of all pipeline layers with:
- Sequential layer execution
- Full lineage tracking
- Error handling and recovery
- Persistence to database
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import logging
import uuid

from .base import (
    PipelineContext,
    PipelineResult,
    LayerStatus,
    LayerError,
)
from .ingestion import IngestionLayer, IngestionInput, IngestionOutput
from .validation import ValidationLayer, ValidationOutput
from .normalization import NormalizationLayer, NormalizationOutput
from .feature import FeatureLayer, FeatureOutput
from .intelligence import IntelligenceLayer, IntelligenceOutput


logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution."""
    persist_raw: bool = True
    skip_validation: bool = False
    skip_features: bool = False
    skip_intelligence: bool = False
    max_retries: int = 3
    

@dataclass
class PipelineExecutionResult:
    """Result of full pipeline execution."""
    success: bool
    pipeline_id: str
    ingestion_id: str | None
    batch_id: str | None
    status: str
    layers_completed: list[str]
    layers_failed: list[str]
    context: PipelineContext
    final_output: IntelligenceOutput | None
    error: str | None
    execution_time_ms: float
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "pipeline_id": self.pipeline_id,
            "ingestion_id": self.ingestion_id,
            "batch_id": self.batch_id,
            "status": self.status,
            "layers_completed": self.layers_completed,
            "layers_failed": self.layers_failed,
            "lineage": self.context.lineage,
            "audit_trail": self.context.audit_trail,
            "errors": self.context.errors,
            "warnings": self.context.warnings,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }


class PipelineOrchestrator:
    """Orchestrates execution of the full data pipeline.
    
    Manages layer instantiation, execution sequence, and error handling.
    """
    
    def __init__(
        self,
        db_client: Any = None,
        config: PipelineConfig | None = None,
        ingestion_layer: IngestionLayer | None = None,
        validation_layer: ValidationLayer | None = None,
        normalization_layer: NormalizationLayer | None = None,
        feature_layer: FeatureLayer | None = None,
        intelligence_layer: IntelligenceLayer | None = None,
    ):
        """Initialize orchestrator.
        
        Args:
            db_client: Database client for persistence.
            config: Pipeline configuration.
            *_layer: Optional pre-configured layer instances.
        """
        self._db = db_client
        self._config = config or PipelineConfig()
        
        # Initialize layers
        self._ingestion = ingestion_layer or IngestionLayer(
            persist_raw=self._config.persist_raw,
            db_client=db_client,
        )
        self._validation = validation_layer or ValidationLayer()
        self._normalization = normalization_layer or NormalizationLayer()
        self._feature = feature_layer or FeatureLayer()
        self._intelligence = intelligence_layer or IntelligenceLayer()
    
    def _persist_results(
        self,
        output: IntelligenceOutput,
        context: PipelineContext,
    ) -> None:
        """Persist normalized records to snapshot tables."""
        if not self._db:
            logger.debug("Persistence skipped (no db client)")
            return
        
        batch_id = output.batch_id
        imported_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Map datasets to tables
        table_mapping = {
            "customers": "sage_customers_snapshot",
            "ar": "sage_ar_snapshot",
            "ap": "sage_ap_snapshot",
            "gl": "sage_gl_snapshot",
            "inventory": "sage_inventory_snapshot",
            "staff": "sage_staff_snapshot",
        }
        
        for dataset, records in output.normalized_records.items():
            if not records:
                continue
            
            table = table_mapping.get(dataset)
            if not table:
                logger.warning(f"No table mapping for dataset: {dataset}")
                continue
            
            # Enrich records with batch metadata
            enriched = []
            for r in records:
                x = dict(r)
                x["batch_id"] = batch_id
                x["imported_at"] = imported_at
                enriched.append(x)
            
            try:
                self._db.table(table).insert(enriched).execute()
                logger.info(f"Persisted {len(enriched)} records to {table}")
                context.add_lineage("persistence", {
                    f"{dataset}_persisted": len(enriched),
                    f"{dataset}_table": table,
                })
            except Exception as e:
                logger.error(f"Failed to persist {dataset} to {table}: {e}")
                context.add_error(
                    layer="persistence",
                    error_type="insert_failed",
                    message=str(e),
                    details={"table": table, "count": len(enriched)},
                )
                raise
    
    def execute(
        self,
        input_data: IngestionInput,
    ) -> PipelineExecutionResult:
        """Execute the full pipeline.
        
        Args:
            input_data: Input to the ingestion layer.
            
        Returns:
            PipelineExecutionResult with full lineage and outputs.
        """
        import time
        start_time = time.perf_counter()
        
        context = PipelineContext()
        layers_completed: list[str] = []
        layers_failed: list[str] = []
        final_output: IntelligenceOutput | None = None
        error_message: str | None = None
        
        try:
            # Layer 1: Ingestion
            logger.info("Starting Layer 1: Ingestion")
            ingestion_result = self._ingestion.process(input_data, context)
            
            if ingestion_result.failed:
                layers_failed.append("ingestion")
                raise LayerError("ingestion", "Ingestion failed", ingestion_result.error)
            
            layers_completed.append("ingestion")
            ingestion_output = ingestion_result.data
            
            # Layer 2: Validation
            logger.info("Starting Layer 2: Validation")
            if self._config.skip_validation:
                # Create pass-through validation output
                validation_output = ValidationOutput(
                    ingestion_id=ingestion_output.ingestion_id,
                    batch_id=ingestion_output.batch_id,
                    valid_records=[],  # Will populate from payloads
                    invalid_records=[],
                    validation_summary={"skipped": True},
                )
                context.add_lineage("validation", {"skipped": True})
            else:
                validation_result = self._validation.process(ingestion_output, context)
                
                if validation_result.failed:
                    layers_failed.append("validation")
                    raise LayerError("validation", "Validation failed", validation_result.error)
                
                validation_output = validation_result.data
            
            layers_completed.append("validation")
            
            # Layer 3: Normalization
            logger.info("Starting Layer 3: Normalization")
            normalization_result = self._normalization.process(validation_output, context)
            
            if normalization_result.failed:
                layers_failed.append("normalization")
                raise LayerError("normalization", "Normalization failed", normalization_result.error)
            
            layers_completed.append("normalization")
            normalization_output = normalization_result.data
            
            # Layer 4: Feature Computation
            logger.info("Starting Layer 4: Feature Computation")
            if self._config.skip_features:
                feature_output = FeatureOutput(
                    ingestion_id=normalization_output.ingestion_id,
                    batch_id=normalization_output.batch_id,
                    features=[],
                    aggregates={},
                    normalized_records=normalization_output.normalized_records,
                )
                context.add_lineage("feature_computation", {"skipped": True})
            else:
                feature_result = self._feature.process(normalization_output, context)
                
                if feature_result.failed:
                    layers_failed.append("feature_computation")
                    raise LayerError("feature_computation", "Feature computation failed", feature_result.error)
                
                feature_output = feature_result.data
            
            layers_completed.append("feature_computation")
            
            # Layer 5: Intelligence
            logger.info("Starting Layer 5: Intelligence")
            if self._config.skip_intelligence:
                from .intelligence import RiskLevel
                intelligence_output = IntelligenceOutput(
                    ingestion_id=feature_output.ingestion_id,
                    batch_id=feature_output.batch_id,
                    risk_scores=[],
                    insights=[],
                    triggers=[],
                    overall_risk_level=RiskLevel.LOW,
                    normalized_records=feature_output.normalized_records,
                )
                context.add_lineage("intelligence", {"skipped": True})
            else:
                intelligence_result = self._intelligence.process(feature_output, context)
                
                if intelligence_result.failed:
                    layers_failed.append("intelligence")
                    raise LayerError("intelligence", "Intelligence layer failed", intelligence_result.error)
                
                intelligence_output = intelligence_result.data
            
            layers_completed.append("intelligence")
            final_output = intelligence_output
            
            # Persist results
            logger.info("Persisting results")
            self._persist_results(intelligence_output, context)
            layers_completed.append("persistence")
            
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            
            return PipelineExecutionResult(
                success=True,
                pipeline_id=context.pipeline_id,
                ingestion_id=context.ingestion_id,
                batch_id=context.batch_id,
                status="completed",
                layers_completed=layers_completed,
                layers_failed=layers_failed,
                context=context,
                final_output=final_output,
                error=None,
                execution_time_ms=execution_time_ms,
            )
            
        except LayerError as e:
            error_message = str(e)
            logger.error(f"Pipeline failed at {e.layer}: {e.message}")
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Pipeline failed with unexpected error: {e}", exc_info=True)
        
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        
        return PipelineExecutionResult(
            success=False,
            pipeline_id=context.pipeline_id,
            ingestion_id=context.ingestion_id,
            batch_id=context.batch_id,
            status="failed",
            layers_completed=layers_completed,
            layers_failed=layers_failed,
            context=context,
            final_output=final_output,
            error=error_message,
            execution_time_ms=execution_time_ms,
        )
    
    async def execute_async(
        self,
        input_data: IngestionInput,
    ) -> PipelineExecutionResult:
        """Async wrapper for pipeline execution.
        
        Useful for API endpoints that need async support.
        """
        import asyncio
        return await asyncio.to_thread(self.execute, input_data)
