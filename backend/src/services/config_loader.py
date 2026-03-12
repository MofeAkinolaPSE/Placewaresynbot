"""
Configuration Loader for Pipeline Normalization Rules

Loads YAML configuration and converts to NormalizationConfig objects
for use by the normalization layer.
"""

from pathlib import Path
from typing import Any, Callable
import logging
import re

import yaml

from ..pipeline.normalization import NormalizationConfig, FieldMapping


logger = logging.getLogger(__name__)


# Default config path
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "normalization_rules.yaml"


def _create_transform_function(transform_type: str | None) -> Callable[[Any], Any] | None:
    """Create a transform function from config specification."""
    if not transform_type:
        return None
    
    if transform_type == "lowercase":
        return lambda val: str(val).lower() if val else None
    
    if transform_type == "decimal":
        def to_decimal(val: Any) -> float | None:
            if val is None:
                return None
            try:
                # Handle currency strings
                cleaned = re.sub(r"[,$₦]", "", str(val))
                return float(cleaned)
            except (ValueError, TypeError):
                return None
        return to_decimal
    
    if transform_type == "integer":
        def to_int(val: Any) -> int | None:
            if val is None:
                return None
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None
        return to_int
    
    if transform_type == "timestamp":
        # Timestamp normalization is handled separately in the layer
        return None
    
    return None


def _parse_field_mapping(target_field: str, config: dict[str, Any]) -> FieldMapping:
    """Parse a single field mapping from config."""
    sources = config.get("sources", [target_field])
    if isinstance(sources, str):
        sources = [sources]
    
    return FieldMapping(
        source=sources,
        target=target_field,
        transform=_create_transform_function(config.get("transform")),
        default=config.get("default"),
        required=config.get("required", False),
    )


def _parse_dataset_config(name: str, config: dict[str, Any]) -> NormalizationConfig:
    """Parse a dataset configuration into NormalizationConfig."""
    dataset_name = config.get("dataset_name", name)
    
    # Parse field mappings
    field_mappings: list[FieldMapping] = []
    for field_name, field_config in config.get("field_mappings", {}).items():
        if isinstance(field_config, dict):
            mapping = _parse_field_mapping(field_name, field_config)
        else:
            # Simple string mapping
            mapping = FieldMapping(source=field_config, target=field_name)
        field_mappings.append(mapping)
    
    # Parse enum mappings
    enum_mappings: dict[str, dict[str, str]] = {}
    for field_name, enum_map in config.get("enum_mappings", {}).items():
        if isinstance(enum_map, dict):
            enum_mappings[field_name] = {
                str(k).lower(): v for k, v in enum_map.items()
            }
    
    # Identify timestamp fields (those with transform: timestamp)
    timestamp_fields: list[str] = []
    for field_name, field_config in config.get("field_mappings", {}).items():
        if isinstance(field_config, dict) and field_config.get("transform") == "timestamp":
            timestamp_fields.append(field_name)
    
    return NormalizationConfig(
        dataset_name=dataset_name,
        field_mappings=field_mappings,
        enum_mappings=enum_mappings,
        timestamp_fields=timestamp_fields,
    )


def load_normalization_configs(
    config_path: Path | str | None = None,
) -> dict[str, NormalizationConfig]:
    """Load normalization configurations from YAML file.
    
    Args:
        config_path: Path to YAML config file. Uses default if not provided.
        
    Returns:
        Dictionary mapping dataset name to NormalizationConfig.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    
    if not path.exists():
        logger.warning(f"Normalization config not found at {path}, using defaults")
        return {}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load normalization config: {e}")
        return {}
    
    configs: dict[str, NormalizationConfig] = {}
    
    # Skip special keys
    skip_keys = {"transforms", "settings"}
    
    for name, config in raw_config.items():
        if name in skip_keys:
            continue
        if not isinstance(config, dict):
            continue
        
        try:
            parsed = _parse_dataset_config(name, config)
            # Store by both config name and dataset_name
            configs[name] = parsed
            configs[parsed.dataset_name] = parsed
            logger.debug(f"Loaded normalization config for {name}")
        except Exception as e:
            logger.warning(f"Failed to parse config for {name}: {e}")
    
    logger.info(f"Loaded {len(configs)} normalization configs from {path}")
    return configs


def get_transform_settings(
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load transform settings from config file.
    
    Args:
        config_path: Path to YAML config file.
        
    Returns:
        Transform settings dictionary.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    
    if not path.exists():
        return {}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
        return raw_config.get("transforms", {})
    except Exception as e:
        logger.error(f"Failed to load transform settings: {e}")
        return {}


def get_global_settings(
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load global settings from config file.
    
    Args:
        config_path: Path to YAML config file.
        
    Returns:
        Global settings dictionary.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    
    if not path.exists():
        return {}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
        return raw_config.get("settings", {})
    except Exception as e:
        logger.error(f"Failed to load global settings: {e}")
        return {}
