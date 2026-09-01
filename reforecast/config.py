"""Configuration management for WFM Reforecast Engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """WFM configuration parameters.

    All fields have sensible defaults for a typical contact center operation.
    """

    # Interval
    interval_length: int = 30  # minutes per interval

    # Average Handle Time
    aht_seconds: int = 270  # seconds
    shrinkage_pct: float = 0.34  # 34% shrinkage

    # Service Level
    service_level: float = 0.80  # 80% answered within threshold
    sl_threshold_seconds: int = 20  # seconds
    max_occupancy: float = 0.85  # 85% max occupancy

    # Thresholds for staffing gap classification
    overstaff_threshold_pct: float = 0.15  # >15% overstaffed
    understaff_threshold_pct: float = 0.10  # >10% understaffed

    # Reforecasting
    reforecast_checkpoint_interval: int = 10  # interval index for checkpoint
    reforecast_blend_factor: float = 0.50  # 50% persistence

    def validate(self) -> None:
        """Validate config values, raising ValueError on invalid inputs."""
        errors: list[str] = []

        if self.interval_length <= 0:
            errors.append(f"interval_length must be > 0, got {self.interval_length}")
        if self.aht_seconds <= 0:
            errors.append(f"aht_seconds must be > 0, got {self.aht_seconds}")
        if not 0 <= self.shrinkage_pct <= 1:
            errors.append(f"shrinkage_pct must be between 0 and 1, got {self.shrinkage_pct}")
        if not 0 <= self.service_level <= 1:
            errors.append(f"service_level must be between 0 and 1, got {self.service_level}")
        if self.sl_threshold_seconds <= 0:
            errors.append(f"sl_threshold_seconds must be > 0, got {self.sl_threshold_seconds}")
        if not 0 <= self.max_occupancy <= 1:
            errors.append(f"max_occupancy must be between 0 and 1, got {self.max_occupancy}")
        if not 0 <= self.overstaff_threshold_pct <= 1:
            errors.append(
                f"overstaff_threshold_pct must be between 0 and 1, got {self.overstaff_threshold_pct}"
            )
        if not 0 <= self.understaff_threshold_pct <= 1:
            errors.append(
                f"understaff_threshold_pct must be between 0 and 1, got {self.understaff_threshold_pct}"
            )
        if self.reforecast_checkpoint_interval < 0:
            errors.append(
                f"reforecast_checkpoint_interval must be >= 0, got {self.reforecast_checkpoint_interval}"
            )
        if not 0 <= self.reforecast_blend_factor <= 1:
            errors.append(
                f"reforecast_blend_factor must be between 0 and 1, got {self.reforecast_blend_factor}"
            )

        if errors:
            raise ValueError("Config validation failed:\n" + "\n".join(errors))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Config":
        """Create Config from a dictionary (e.g. parsed YAML)."""
        valid_keys = {
            "interval_length",
            "aht_seconds",
            "shrinkage_pct",
            "service_level",
            "sl_threshold_seconds",
            "max_occupancy",
            "overstaff_threshold_pct",
            "understaff_threshold_pct",
            "reforecast_checkpoint_interval",
            "reforecast_blend_factor",
        }
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        cfg = cls(**filtered)
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Load config from a YAML file using safe_load."""
        logger.info("Loading config from %s", path)
        with open(path) as f:
            data = yaml.safe_load(f)
        if data is None:
            logger.warning("Config file %s is empty — using defaults", path)
            return cls()
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interval_length": self.interval_length,
            "aht_seconds": self.aht_seconds,
            "shrinkage_pct": self.shrinkage_pct,
            "service_level": self.service_level,
            "sl_threshold_seconds": self.sl_threshold_seconds,
            "max_occupancy": self.max_occupancy,
            "overstaff_threshold_pct": self.overstaff_threshold_pct,
            "understaff_threshold_pct": self.understaff_threshold_pct,
            "reforecast_checkpoint_interval": self.reforecast_checkpoint_interval,
            "reforecast_blend_factor": self.reforecast_blend_factor,
        }