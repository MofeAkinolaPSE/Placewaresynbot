"""
Layer 2: Validation Layer

Responsibilities:
- Schema validation
- Required field checks
- Type validation
- Reject malformed records
- Log validation errors

Rules:
- Use strict schema contracts
- No business logic here
- Validation must not transform data
"""

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar
import logging

from .base import (
    PipelineContext,
    PipelineLayer,
    PipelineResult,
    LayerStatus,
)
from .ingestion import IngestionOutput, RawPayload


logger = logging.getLogger(__name__)


T = TypeVar("T")


@dataclass
class ValidationRule:
    """A single validation rule."""
    name: str
    field: str | None  # None for record-level validation
    validator: Callable[[Any], bool]
    error_message: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class ValidationResult:
    """Result of validating a single record."""
    valid: bool
    record: dict[str, Any]
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ValidationOutput:
    """Output from the validation layer."""
    ingestion_id: str
    batch_id: str
    valid_records: list[dict[str, Any]]
    invalid_records: list[dict[str, Any]]
    validation_summary: dict[str, Any]


class ValidationLayer(PipelineLayer[IngestionOutput, ValidationOutput]):
    """Layer 2: Validation
    
    Validates records against schema contracts without transforming data.
    """
    
    def __init__(
        self,
        schema_registry: dict[str, dict[str, Any]] | None = None,
        required_fields_by_dataset: dict[str, list[str]] | None = None,
        custom_rules: dict[str, list[ValidationRule]] | None = None,
    ):
        """Initialize validation layer.
        
        Args:
            schema_registry: Map of dataset_name -> schema definition.
            required_fields_by_dataset: Map of dataset_name -> required field names.
            custom_rules: Map of dataset_name -> list of custom validation rules.
        """
        self._schema_registry = schema_registry or {}
        self._required_fields = required_fields_by_dataset or {}
        self._custom_rules = custom_rules or {}
    
    @property
    def name(self) -> str:
        return "validation"
    
    def _validate_required_fields(
        self,
        record: dict[str, Any],
        required_fields: list[str],
    ) -> list[dict[str, Any]]:
        """Check for required fields."""
        errors = []
        for field_name in required_fields:
            if field_name not in record or record[field_name] is None:
                errors.append({
                    "rule": "required_field",
                    "field": field_name,
                    "message": f"Required field '{field_name}' is missing or null",
                })
        return errors
    
    def _validate_types(
        self,
        record: dict[str, Any],
        schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Validate field types against schema."""
        errors = []
        type_map = schema.get("types", {})
        
        for field_name, expected_type in type_map.items():
            if field_name not in record:
                continue
            
            value = record[field_name]
            if value is None:
                continue  # Null handling is done by required field check
            
            # Basic type validation
            type_valid = True
            if expected_type == "string" and not isinstance(value, str):
                type_valid = False
            elif expected_type == "number" and not isinstance(value, (int, float)):
                type_valid = False
            elif expected_type == "integer" and not isinstance(value, int):
                type_valid = False
            elif expected_type == "boolean" and not isinstance(value, bool):
                type_valid = False
            elif expected_type == "array" and not isinstance(value, list):
                type_valid = False
            elif expected_type == "object" and not isinstance(value, dict):
                type_valid = False
            
            if not type_valid:
                errors.append({
                    "rule": "type_mismatch",
                    "field": field_name,
                    "expected": expected_type,
                    "actual": type(value).__name__,
                    "message": f"Field '{field_name}' expected {expected_type}, got {type(value).__name__}",
                })
        
        return errors
    
    def _apply_custom_rules(
        self,
        record: dict[str, Any],
        rules: list[ValidationRule],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Apply custom validation rules."""
        errors = []
        warnings = []
        
        for rule in rules:
            try:
                value = record.get(rule.field) if rule.field else record
                if not rule.validator(value):
                    entry = {
                        "rule": rule.name,
                        "field": rule.field,
                        "message": rule.error_message,
                    }
                    if rule.severity == "error":
                        errors.append(entry)
                    else:
                        warnings.append(entry)
            except Exception as e:
                errors.append({
                    "rule": rule.name,
                    "field": rule.field,
                    "message": f"Rule execution failed: {e}",
                })
        
        return errors, warnings
    
    def _validate_record(
        self,
        record: dict[str, Any],
        dataset_name: str,
    ) -> ValidationResult:
        """Validate a single record."""
        all_errors: list[dict[str, Any]] = []
        all_warnings: list[dict[str, Any]] = []
        
        # Check required fields
        required = self._required_fields.get(dataset_name, [])
        all_errors.extend(self._validate_required_fields(record, required))
        
        # Check types
        schema = self._schema_registry.get(dataset_name, {})
        all_errors.extend(self._validate_types(record, schema))
        
        # Apply custom rules
        custom = self._custom_rules.get(dataset_name, [])
        custom_errors, custom_warnings = self._apply_custom_rules(record, custom)
        all_errors.extend(custom_errors)
        all_warnings.extend(custom_warnings)
        
        return ValidationResult(
            valid=len(all_errors) == 0,
            record=record,
            errors=all_errors,
            warnings=all_warnings,
        )
    
    def _parse_payload_content(
        self,
        payload: RawPayload,
    ) -> list[dict[str, Any]]:
        """Parse raw payload into records."""
        content = payload.raw_data
        
        if isinstance(content, list):
            return content
        
        if isinstance(content, dict):
            return [content]
        
        if isinstance(content, bytes):
            # Try to decode and parse
            try:
                import json
                decoded = content.decode("utf-8")
                parsed = json.loads(decoded)
                if isinstance(parsed, list):
                    return parsed
                return [parsed]
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Not JSON, try CSV
                try:
                    import csv
                    import io
                    decoded = content.decode("utf-8")
                    reader = csv.DictReader(io.StringIO(decoded))
                    return list(reader)
                except Exception:
                    logger.warning(f"Could not parse payload content: {payload.filename}")
                    return []
        
        return []
    
    def _process(
        self,
        input_data: IngestionOutput,
        context: PipelineContext,
    ) -> PipelineResult[ValidationOutput]:
        """Process validation."""
        valid_records: list[dict[str, Any]] = []
        invalid_records: list[dict[str, Any]] = []
        total_errors = 0
        total_warnings = 0
        
        for payload in input_data.payloads:
            dataset_name = payload.metadata.get("dataset_name", "unknown")
            records = self._parse_payload_content(payload)
            
            for record in records:
                result = self._validate_record(record, dataset_name)
                
                if result.valid:
                    # Add metadata for lineage
                    record["_validation"] = {
                        "dataset": dataset_name,
                        "warnings": result.warnings,
                    }
                    valid_records.append(record)
                else:
                    record["_validation_errors"] = result.errors
                    invalid_records.append(record)
                    total_errors += len(result.errors)
                
                total_warnings += len(result.warnings)
        
        # Build summary
        summary = {
            "total_records": len(valid_records) + len(invalid_records),
            "valid_records": len(valid_records),
            "invalid_records": len(invalid_records),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "validation_rate": (
                len(valid_records) / (len(valid_records) + len(invalid_records))
                if (valid_records or invalid_records) else 1.0
            ),
        }
        
        context.add_lineage(self.name, summary)
        
        # Add errors to context
        for record in invalid_records:
            for error in record.get("_validation_errors", []):
                context.add_error(
                    layer=self.name,
                    error_type=error.get("rule", "validation_error"),
                    message=error.get("message", "Validation failed"),
                    details=error,
                )
        
        output = ValidationOutput(
            ingestion_id=input_data.ingestion_id,
            batch_id=input_data.batch_id,
            valid_records=valid_records,
            invalid_records=invalid_records,
            validation_summary=summary,
        )
        
        return PipelineResult(
            status=LayerStatus.SUCCEEDED,
            data=output,
            rows_input=len(valid_records) + len(invalid_records),
            rows_output=len(valid_records),
            rows_rejected=len(invalid_records),
        )
