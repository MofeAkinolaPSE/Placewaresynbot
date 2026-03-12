"""
Layer 3: Normalization Layer

Responsibilities:
- Map raw data → internal domain models
- Standardize field names
- Normalize timestamps
- Resolve enumerations via config

Rules:
- All mappings must be config-driven
- No industry hardcoding
- Output must conform to typed domain entities
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar
import logging
import re

from .base import (
    PipelineContext,
    PipelineLayer,
    PipelineResult,
    LayerStatus,
)
from .validation import ValidationOutput


logger = logging.getLogger(__name__)


T = TypeVar("T")


@dataclass
class FieldMapping:
    """Defines how to map a source field to a target field."""
    source: str | list[str]  # Source field name(s) to try
    target: str  # Target field name
    transform: Callable[[Any], Any] | None = None  # Optional transform function
    default: Any = None  # Default value if source is missing
    required: bool = False


@dataclass
class NormalizationConfig:
    """Configuration for normalizing a dataset."""
    dataset_name: str
    field_mappings: list[FieldMapping]
    enum_mappings: dict[str, dict[str, str]] = field(default_factory=dict)  # field -> {source_val: target_val}
    timestamp_fields: list[str] = field(default_factory=list)
    timestamp_formats: list[str] = field(default_factory=lambda: [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y%m%d",
    ])


@dataclass
class NormalizedRecord:
    """A normalized domain entity."""
    dataset: str
    entity: dict[str, Any]
    source_hash: str | None = None


@dataclass
class NormalizationOutput:
    """Output from the normalization layer."""
    ingestion_id: str
    batch_id: str
    normalized_records: dict[str, list[dict[str, Any]]]  # dataset -> records
    normalization_summary: dict[str, Any]


class NormalizationLayer(PipelineLayer[ValidationOutput, NormalizationOutput]):
    """Layer 3: Normalization
    
    Maps validated records to internal domain models using config-driven mappings.
    """
    
    def __init__(
        self,
        configs: dict[str, NormalizationConfig] | None = None,
    ):
        """Initialize normalization layer.
        
        Args:
            configs: Map of dataset_name -> NormalizationConfig.
        """
        self._configs = configs or {}
    
    @property
    def name(self) -> str:
        return "normalization"
    
    def _normalize_timestamp(
        self,
        value: Any,
        formats: list[str],
    ) -> str | None:
        """Normalize timestamp to ISO 8601 format."""
        if value is None:
            return None
        
        if isinstance(value, datetime):
            return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        
        value_str = str(value).strip()
        if not value_str:
            return None
        
        # Try each format
        for fmt in formats:
            try:
                dt = datetime.strptime(value_str, fmt)
                return dt.replace(microsecond=0).isoformat() + "Z"
            except ValueError:
                continue
        
        # If all formats fail, return original (may need manual review)
        logger.warning(f"Could not parse timestamp: {value_str}")
        return value_str
    
    def _apply_enum_mapping(
        self,
        value: Any,
        mapping: dict[str, str],
    ) -> Any:
        """Apply enum mapping to a value."""
        if value is None:
            return None
        
        str_value = str(value).strip().lower()
        
        # Try exact match first
        if str_value in mapping:
            return mapping[str_value]
        
        # Try case-insensitive match
        for source, target in mapping.items():
            if source.lower() == str_value:
                return target
        
        # Return original if no mapping found
        return value
    
    def _get_source_value(
        self,
        record: dict[str, Any],
        source: str | list[str],
    ) -> Any:
        """Get value from record trying multiple source fields."""
        sources = [source] if isinstance(source, str) else source
        
        for src in sources:
            # Handle nested fields (e.g., "address.city")
            parts = src.split(".")
            value = record
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    value = None
                    break
            
            if value is not None:
                return value
        
        return None
    
    def _normalize_record(
        self,
        record: dict[str, Any],
        config: NormalizationConfig,
    ) -> dict[str, Any]:
        """Normalize a single record using config."""
        normalized: dict[str, Any] = {}
        
        for mapping in config.field_mappings:
            # Get source value
            value = self._get_source_value(record, mapping.source)
            
            # Use default if no value
            if value is None:
                value = mapping.default
            
            # Apply transform if provided
            if mapping.transform and value is not None:
                try:
                    value = mapping.transform(value)
                except Exception as e:
                    logger.warning(f"Transform failed for {mapping.target}: {e}")
            
            # Apply enum mapping if configured
            if mapping.target in config.enum_mappings and value is not None:
                value = self._apply_enum_mapping(
                    value,
                    config.enum_mappings[mapping.target],
                )
            
            # Normalize timestamp if configured
            if mapping.target in config.timestamp_fields and value is not None:
                value = self._normalize_timestamp(value, config.timestamp_formats)
            
            normalized[mapping.target] = value
        
        return normalized
    
    def _infer_dataset_from_record(
        self,
        record: dict[str, Any],
    ) -> str:
        """Infer dataset name from record metadata."""
        validation_meta = record.get("_validation", {})
        return validation_meta.get("dataset", "unknown")
    
    def _process(
        self,
        input_data: ValidationOutput,
        context: PipelineContext,
    ) -> PipelineResult[NormalizationOutput]:
        """Process normalization."""
        normalized_by_dataset: dict[str, list[dict[str, Any]]] = {}
        stats: dict[str, dict[str, int]] = {}
        
        for record in input_data.valid_records:
            dataset = self._infer_dataset_from_record(record)
            
            if dataset not in normalized_by_dataset:
                normalized_by_dataset[dataset] = []
                stats[dataset] = {"input": 0, "normalized": 0}
            
            stats[dataset]["input"] += 1
            
            config = self._configs.get(dataset)
            if config:
                # Use config-driven normalization
                normalized = self._normalize_record(record, config)
            else:
                # Pass through without transformation (identity mapping)
                # Remove internal metadata fields
                normalized = {
                    k: v for k, v in record.items()
                    if not k.startswith("_")
                }
            
            normalized_by_dataset[dataset].append(normalized)
            stats[dataset]["normalized"] += 1
        
        # Build summary
        total_input = sum(s["input"] for s in stats.values())
        total_normalized = sum(s["normalized"] for s in stats.values())
        
        summary = {
            "total_input": total_input,
            "total_normalized": total_normalized,
            "datasets": stats,
            "configs_applied": list(self._configs.keys()),
        }
        
        context.add_lineage(self.name, summary)
        
        output = NormalizationOutput(
            ingestion_id=input_data.ingestion_id,
            batch_id=input_data.batch_id,
            normalized_records=normalized_by_dataset,
            normalization_summary=summary,
        )
        
        return PipelineResult(
            status=LayerStatus.SUCCEEDED,
            data=output,
            rows_input=total_input,
            rows_output=total_normalized,
        )


# ============================================================================
# Default normalization configs (can be overridden via config file)
# ============================================================================

def _to_lowercase(val: Any) -> str | None:
    return str(val).lower() if val else None


def _to_decimal(val: Any) -> float | None:
    if val is None:
        return None
    try:
        # Handle currency strings like "$1,234.56"
        cleaned = re.sub(r"[,$]", "", str(val))
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# Pre-built config for Sage customers
SAGE_CUSTOMERS_CONFIG = NormalizationConfig(
    dataset_name="customers",
    field_mappings=[
        FieldMapping(source=["customer_id", "CustomerID", "ID"], target="customer_id"),
        FieldMapping(source=["name", "Name", "CustomerName", "customer_name"], target="name"),
        FieldMapping(source=["email", "Email", "EmailAddress"], target="email", transform=_to_lowercase),
        FieldMapping(source=["phone", "Phone", "PhoneNumber", "phone_number"], target="phone"),
        FieldMapping(source=["status", "Status", "CustomerStatus"], target="status", default="active"),
    ],
    enum_mappings={
        "status": {
            "active": "active",
            "inactive": "inactive",
            "pending": "pending",
            "suspended": "suspended",
            "1": "active",
            "0": "inactive",
            "true": "active",
            "false": "inactive",
        },
    },
)


# Pre-built config for Sage AR
SAGE_AR_CONFIG = NormalizationConfig(
    dataset_name="ar",
    field_mappings=[
        FieldMapping(source=["customer_id", "CustomerID"], target="customer_id"),
        FieldMapping(source=["amount", "Amount", "Total"], target="amount", transform=_to_decimal),
        FieldMapping(source=["due_date", "DueDate", "due"], target="due_date"),
        FieldMapping(source=["status", "Status"], target="status", default="open"),
    ],
    timestamp_fields=["due_date"],
    enum_mappings={
        "status": {
            "open": "open",
            "paid": "paid",
            "overdue": "overdue",
            "partial": "partial",
        },
    },
)


# Pre-built config for Sage inventory
SAGE_INVENTORY_CONFIG = NormalizationConfig(
    dataset_name="inventory",
    field_mappings=[
        FieldMapping(source=["sku", "SKU", "ProductCode", "ItemCode"], target="sku"),
        FieldMapping(source=["name", "Name", "Description", "ProductName"], target="name"),
        FieldMapping(source=["quantity", "Quantity", "qty", "Qty", "on_hand"], target="quantity", transform=_to_int),
        FieldMapping(source=["price", "Price", "UnitPrice", "unit_price"], target="price", transform=_to_decimal),
        FieldMapping(source=["cost", "Cost", "UnitCost", "unit_cost"], target="cost", transform=_to_decimal),
    ],
)


DEFAULT_CONFIGS = {
    "customers": SAGE_CUSTOMERS_CONFIG,
    "ar": SAGE_AR_CONFIG,
    "inventory": SAGE_INVENTORY_CONFIG,
}
