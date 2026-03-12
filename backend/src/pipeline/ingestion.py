"""
Layer 1: Ingestion Layer

Responsibilities:
- Accept external data (APIs, uploads, database pulls)
- Timestamp and tag all records
- Assign ingestion_id
- Persist raw payload unchanged

Rules:
- Raw data must never be mutated
- Store raw records separately
- All ingestion must be idempotent
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
import json
import logging
import uuid

from .base import (
    PipelineContext,
    PipelineLayer,
    PipelineResult,
    LayerStatus,
    LayerError,
)


logger = logging.getLogger(__name__)


@dataclass
class RawPayload:
    """Immutable raw payload from ingestion."""
    ingestion_id: str
    source_system: str
    content_type: str
    raw_data: bytes | dict[str, Any]
    filename: str | None
    received_at: str
    content_hash: str
    metadata: dict[str, Any]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        raw_for_storage = self.raw_data
        if isinstance(raw_for_storage, bytes):
            # Store bytes as base64 or reference
            import base64
            raw_for_storage = {
                "_type": "bytes",
                "_encoding": "base64",
                "_data": base64.b64encode(raw_for_storage).decode("utf-8"),
            }
        return {
            "ingestion_id": self.ingestion_id,
            "source_system": self.source_system,
            "content_type": self.content_type,
            "raw_data": raw_for_storage,
            "filename": self.filename,
            "received_at": self.received_at,
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }


@dataclass
class IngestionInput:
    """Input to the ingestion layer."""
    source_system: str
    datasets: dict[str, dict[str, Any]]  # dataset_name -> {content, filename, content_type}
    metadata: dict[str, Any] | None = None


@dataclass
class IngestionOutput:
    """Output from the ingestion layer."""
    ingestion_id: str
    batch_id: str
    received_at: str
    payloads: list[RawPayload]
    idempotency_key: str | None


class IngestionLayer(PipelineLayer[IngestionInput, IngestionOutput]):
    """Layer 1: Ingestion
    
    Accepts raw data, assigns IDs, persists unchanged, and produces
    immutable RawPayload objects for downstream processing.
    """
    
    def __init__(
        self,
        persist_raw: bool = True,
        db_client: Any = None,
    ):
        """Initialize ingestion layer.
        
        Args:
            persist_raw: Whether to persist raw payloads to database.
            db_client: Database client for raw payload persistence.
        """
        self._persist_raw = persist_raw
        self._db = db_client
    
    @property
    def name(self) -> str:
        return "ingestion"
    
    def _compute_content_hash(self, content: bytes | dict) -> str:
        """Compute deterministic hash of content."""
        if isinstance(content, dict):
            content = json.dumps(content, sort_keys=True).encode("utf-8")
        return sha256(content).hexdigest()
    
    def _compute_idempotency_key(
        self,
        source_system: str,
        datasets: dict[str, dict],
        timestamp: str,
    ) -> str:
        """Compute idempotency key from inputs."""
        # Build deterministic string representation
        parts = [source_system, timestamp]
        for name in sorted(datasets.keys()):
            ds = datasets[name]
            if isinstance(ds.get("content"), bytes):
                parts.append(f"{name}:{sha256(ds['content']).hexdigest()}")
            elif ds.get("content"):
                parts.append(f"{name}:{sha256(str(ds['content']).encode()).hexdigest()}")
        combined = "|".join(parts)
        return sha256(combined.encode()).hexdigest()[:32]
    
    def _persist_payloads(
        self,
        payloads: list[RawPayload],
        context: PipelineContext,
    ) -> None:
        """Persist raw payloads to database."""
        if not self._persist_raw or not self._db:
            logger.debug("Raw payload persistence skipped (disabled or no db client)")
            return
        
        try:
            rows = [p.to_dict() for p in payloads]
            self._db.table("raw_import_payloads").insert(rows).execute()
            logger.info(f"Persisted {len(rows)} raw payloads")
            context.add_lineage(self.name, {"persisted_payloads": len(rows)})
        except Exception as e:
            # Log but don't fail - raw persistence is optional
            logger.warning(f"Failed to persist raw payloads: {e}")
            context.add_warning(
                layer=self.name,
                warning_type="persistence_failed",
                message=str(e),
            )
    
    def _process(
        self,
        input_data: IngestionInput,
        context: PipelineContext,
    ) -> PipelineResult[IngestionOutput]:
        """Process ingestion input."""
        received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ingestion_id = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        
        # Update context with IDs
        context.ingestion_id = ingestion_id
        context.batch_id = batch_id
        context.source_system = input_data.source_system
        
        # Compute idempotency key
        idempotency_key = self._compute_idempotency_key(
            source_system=input_data.source_system,
            datasets=input_data.datasets,
            timestamp=received_at,
        )
        
        # Create raw payloads for each dataset
        payloads: list[RawPayload] = []
        for dataset_name, dataset_info in input_data.datasets.items():
            content = dataset_info.get("content")
            if not content:
                continue
            
            content_hash = self._compute_content_hash(content)
            
            payload = RawPayload(
                ingestion_id=ingestion_id,
                source_system=input_data.source_system,
                content_type=dataset_info.get("content_type", "application/octet-stream"),
                raw_data=content,
                filename=dataset_info.get("filename"),
                received_at=received_at,
                content_hash=content_hash,
                metadata={
                    "dataset_name": dataset_name,
                    "batch_id": batch_id,
                    **(input_data.metadata or {}),
                },
            )
            payloads.append(payload)
        
        # Persist raw payloads
        self._persist_payloads(payloads, context)
        
        # Update lineage
        context.add_lineage(self.name, {
            "ingestion_id": ingestion_id,
            "batch_id": batch_id,
            "source_system": input_data.source_system,
            "datasets_received": list(input_data.datasets.keys()),
            "payloads_created": len(payloads),
            "idempotency_key": idempotency_key,
        })
        
        output = IngestionOutput(
            ingestion_id=ingestion_id,
            batch_id=batch_id,
            received_at=received_at,
            payloads=payloads,
            idempotency_key=idempotency_key,
        )
        
        return PipelineResult(
            status=LayerStatus.SUCCEEDED,
            data=output,
            rows_input=len(input_data.datasets),
            rows_output=len(payloads),
        )
