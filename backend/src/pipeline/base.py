"""
Base abstractions for the enterprise data pipeline.

Provides interfaces and data structures used across all layers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar
import logging
import time
import uuid


T = TypeVar("T")  # Input type
U = TypeVar("U")  # Output type


class LayerStatus(Enum):
    """Status of a pipeline layer execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class LayerError(Exception):
    """Raised when a pipeline layer fails."""
    
    def __init__(
        self,
        layer: str,
        message: str,
        original_error: Exception | None = None,
        context: dict[str, Any] | None = None,
    ):
        self.layer = layer
        self.message = message
        self.original_error = original_error
        self.context = context or {}
        super().__init__(f"[{layer}] {message}")


@dataclass
class PipelineContext:
    """Context object passed through pipeline layers.
    
    Tracks metadata, lineage, and accumulated state across processing.
    """
    # Identity
    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ingestion_id: str | None = None
    batch_id: str | None = None
    source_system: str | None = None
    
    # Timing
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Lineage tracking
    lineage: dict[str, Any] = field(default_factory=dict)
    audit_trail: list[dict[str, Any]] = field(default_factory=list)
    
    # Accumulated errors/warnings
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    
    # Custom metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def add_audit_entry(
        self,
        layer: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add an entry to the audit trail."""
        self.audit_trail.append({
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "layer": layer,
            "action": action,
            "details": details or {},
        })
    
    def add_lineage(self, layer: str, data: dict[str, Any]) -> None:
        """Add lineage tracking data for a layer."""
        self.lineage[layer] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            **data,
        }
    
    def add_error(
        self,
        layer: str,
        error_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a non-fatal error."""
        self.errors.append({
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "layer": layer,
            "error_type": error_type,
            "message": message,
            "details": details or {},
        })
    
    def add_warning(
        self,
        layer: str,
        warning_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a warning."""
        self.warnings.append({
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "layer": layer,
            "warning_type": warning_type,
            "message": message,
            "details": details or {},
        })


@dataclass
class PipelineResult(Generic[T]):
    """Result of a pipeline layer or full pipeline execution."""
    status: LayerStatus
    data: T | None = None
    context: PipelineContext | None = None
    
    # Metrics
    rows_input: int = 0
    rows_output: int = 0
    rows_rejected: int = 0
    execution_time_ms: float = 0.0
    
    # Error info (if failed)
    error: LayerError | None = None
    
    @property
    def succeeded(self) -> bool:
        return self.status == LayerStatus.SUCCEEDED
    
    @property
    def failed(self) -> bool:
        return self.status == LayerStatus.FAILED


class PipelineLayer(ABC, Generic[T, U]):
    """Abstract base class for pipeline layers.
    
    Each layer must implement the process method and declare its name.
    Provides automatic timing, logging, and error handling.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Layer name for logging and auditing."""
        pass
    
    @abstractmethod
    def _process(
        self,
        input_data: T,
        context: PipelineContext,
    ) -> PipelineResult[U]:
        """Internal processing logic. Implement in subclasses."""
        pass
    
    def process(
        self,
        input_data: T,
        context: PipelineContext,
    ) -> PipelineResult[U]:
        """Execute the layer with timing, logging, and error handling.
        
        This is the main entry point - wraps _process with observability.
        """
        logger = logging.getLogger(f"pipeline.{self.name}")
        
        context.add_audit_entry(
            layer=self.name,
            action="started",
            details={"input_type": type(input_data).__name__},
        )
        
        start_time = time.perf_counter()
        
        try:
            result = self._process(input_data, context)
            result.execution_time_ms = (time.perf_counter() - start_time) * 1000
            result.context = context
            
            context.add_audit_entry(
                layer=self.name,
                action="completed",
                details={
                    "status": result.status.value,
                    "rows_input": result.rows_input,
                    "rows_output": result.rows_output,
                    "rows_rejected": result.rows_rejected,
                    "execution_time_ms": round(result.execution_time_ms, 2),
                },
            )
            
            logger.info(
                f"Layer completed: status={result.status.value}, "
                f"in={result.rows_input}, out={result.rows_output}, "
                f"rejected={result.rows_rejected}, "
                f"time={result.execution_time_ms:.2f}ms"
            )
            
            return result
            
        except LayerError:
            raise
        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            
            error = LayerError(
                layer=self.name,
                message=str(e),
                original_error=e,
            )
            
            context.add_audit_entry(
                layer=self.name,
                action="failed",
                details={
                    "error": str(e),
                    "execution_time_ms": round(execution_time_ms, 2),
                },
            )
            
            logger.error(f"Layer failed: {e}", exc_info=True)
            
            return PipelineResult(
                status=LayerStatus.FAILED,
                data=None,
                context=context,
                execution_time_ms=execution_time_ms,
                error=error,
            )
