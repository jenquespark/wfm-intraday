"""Configuration management for WFM Intraday.

Parameters are validated at load time.  Unknown keys are preserved so that
forward-compatible configs can be shared without error, but critical misspellings
of known keys ARE rejected because they silently change staffing outputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml

from wfm_intraday.domain.models import (
    ACTUALS_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
)

logger = logging.getLogger(__name__)

# Per-source-type canonical columns, used to validate a column mapping.
_VALID_SECTIONS: dict[str, set[str]] = {
    "forecast": set(FORECAST_COLUMNS),
    "actuals": set(ACTUALS_COLUMNS),
    "staffing": set(SCHEDULE_COLUMNS),
}


def validate_column_mapping(mapping: dict[str, dict[str, str]] | None) -> None:
    """Validate a per-source column mapping ``{section: {canonical: source}}``.

    Hard-fails on:
    * unknown section (not forecast / actuals / staffing)
    * unknown canonical column for that section
    * duplicate source column mapped to two different canonicals

    The mapping is ALWAYS written canonical → source.  The adapter reverses
    it internally for ``df.rename``.  Missing *source* columns in an actual
    file are detected at load time (the rename leaves the canonical absent,
    which the adapter reports as missing required columns).
    """
    if not mapping:
        return
    for section, sec_map in mapping.items():
        if section not in _VALID_SECTIONS:
            raise ValueError(
                f"Unknown column_mapping section '{section}'. "
                f"Valid sections: {sorted(_VALID_SECTIONS)}."
            )
        expected = _VALID_SECTIONS[section]
        seen_sources: dict[str, str] = {}
        for canonical, source in sec_map.items():
            if canonical not in expected:
                raise ValueError(
                    f"Unknown canonical column '{canonical}' in "
                    f"column_mapping[{section}]. "
                    f"Valid canonical columns: {sorted(expected)}."
                )
            if source in seen_sources:
                raise ValueError(
                    f"Duplicate source column '{source}' in column_mapping[{section}] "
                    f"(mapped to both '{seen_sources[source]}' and '{canonical}')."
                )
            seen_sources[source] = canonical


class ChannelType(str, Enum):
    """Supported channel / contact-type models.

    ``VOICE``   — Classical Erlang C queueing (service level, ASA, occupancy).
    ``CHAT``    — Concurrency-aware (agents handle multiple chats at once).
    """

    VOICE = "voice"
    CHAT = "chat"


# Channels reachable through the public pipeline in v0.2.1.  Async is
# intentionally excluded — it is experimental and unreachable via CLI/web/API.
SUPPORTED_CHANNELS = frozenset({"voice", "chat"})


@dataclass(frozen=True)
class ChannelConfig:
    """Per-channel configuration.

    ``channel_type`` controls which staffing model is used.
    ``concurrency`` is the number of simultaneous chats one agent can handle
    (only meaningful for CHAT).

    Concurrency of 1 means one chat at a time (treats chat like voice — not
    recommended but safe).
    """

    channel_type: ChannelType = ChannelType.VOICE
    concurrency: int = 1
    enabled: bool = True

    def validate(self) -> None:
        errors: list[str] = []
        if self.concurrency < 1:
            errors.append(f"concurrency must be >= 1, got {self.concurrency}")
        if errors:
            raise ValueError("ChannelConfig validation: " + "; ".join(errors))


@dataclass(frozen=True)
class Config:
    """WFM configuration parameters.

    Unless documented otherwise, all rate-like values are decimals in [0, 1].
    """

    # ------------------------------------------------------------------
    # Interval
    # ------------------------------------------------------------------
    interval_length_minutes: int = 30

    # ------------------------------------------------------------------
    # Default AHT (used as fallback when per-row AHT is missing)
    # ------------------------------------------------------------------
    aht_seconds: int = 270

    # ------------------------------------------------------------------
    # Shrinkage
    # ------------------------------------------------------------------
    shrinkage_pct: float = 0.34

    # ------------------------------------------------------------------
    # Service level (voice only)
    # ------------------------------------------------------------------
    service_level: float = 0.80  # 80 % answered within threshold
    sl_threshold_seconds: int = 20
    max_occupancy: float = 0.85

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    chat_concurrency: int = 3
    chat_sl_threshold_seconds: int = 60  # chat SLA is usually longer

    # ------------------------------------------------------------------
    # Gap thresholds
    # ------------------------------------------------------------------
    understaff_threshold_pct: float = 0.10
    overstaff_threshold_pct: float = 0.15

    # ------------------------------------------------------------------
    # Reforecast
    # ------------------------------------------------------------------
    reforecast_blend_factor: float = 0.50

    # ------------------------------------------------------------------
    # Redistribution constraints
    # ------------------------------------------------------------------
    max_movement_window_intervals: int = 4  # max intervals apart for a move
    max_movement_window_minutes: int = 120  # max minutes apart for a move

    # ------------------------------------------------------------------
    # Channel type — DEPRECATED: use per-channel config in channels dict
    # ------------------------------------------------------------------
    channel: str = "voice"

    # ------------------------------------------------------------------
    # Per-channel configuration overrides
    # ------------------------------------------------------------------
    channels: dict[str, ChannelConfig] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Column mapping: {section: {canonical: source}}, canonical → source.
    # Consumed by analyze()/validate()/CLI/web through the shared adapter
    # pipeline.  Validated in Config.validate().
    # ------------------------------------------------------------------
    column_mapping: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Raise ``ValueError`` if any config value is out of range."""
        errors: list[str] = []

        if self.interval_length_minutes <= 0:
            errors.append(
                f"interval_length_minutes must be > 0, got {self.interval_length_minutes}"
            )
        if self.aht_seconds <= 0:
            errors.append(f"aht_seconds must be > 0, got {self.aht_seconds}")
        if not 0 <= self.shrinkage_pct < 1:
            errors.append(f"shrinkage_pct must be in [0, 1), got {self.shrinkage_pct}")
        if not 0 <= self.service_level <= 1:
            errors.append(f"service_level must be in [0, 1], got {self.service_level}")
        if self.sl_threshold_seconds <= 0:
            errors.append(f"sl_threshold_seconds must be > 0, got {self.sl_threshold_seconds}")
        if not 0 <= self.max_occupancy <= 1:
            errors.append(f"max_occupancy must be in [0, 1], got {self.max_occupancy}")
        if self.chat_concurrency < 1:
            errors.append(f"chat_concurrency must be >= 1, got {self.chat_concurrency}")
        if not 0 <= self.understaff_threshold_pct <= 1:
            errors.append(
                f"understaff_threshold_pct must be in [0, 1], got {self.understaff_threshold_pct}"
            )
        if not 0 <= self.overstaff_threshold_pct <= 1:
            errors.append(
                f"overstaff_threshold_pct must be in [0, 1], got {self.overstaff_threshold_pct}"
            )
        if not 0 <= self.reforecast_blend_factor <= 1:
            errors.append(
                f"reforecast_blend_factor must be in [0, 1], got {self.reforecast_blend_factor}"
            )
        if self.max_movement_window_intervals < 0:
            errors.append(
                f"max_movement_window_intervals must be >= 0, got {self.max_movement_window_intervals}"
            )
        if self.max_movement_window_minutes < 0:
            errors.append(
                f"max_movement_window_minutes must be >= 0, got {self.max_movement_window_minutes}"
            )

        if self.channel not in ("voice", "chat"):
            errors.append(f"channel must be 'voice' or 'chat', got '{self.channel}'")

        # Validate per-channel configs
        for ch_name, ch_cfg in self.channels.items():
            try:
                ch_cfg.validate()
            except ValueError as e:
                errors.append(f"channel '{ch_name}': {e}")

        # Validate the column mapping (canonical→source per section).
        try:
            validate_column_mapping(self.column_mapping)
        except ValueError as e:
            errors.append(str(e))

        if errors:
            raise ValueError("Config validation failed:\n" + "\n".join(errors))

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Config:
        """Create Config from a dictionary (e.g. parsed YAML).

        Unknown keys cause a hard failure.  This prevents silent misspellings
        from changing staffing outputs without any indication.
        """
        known_keys = set(cls.__dataclass_fields__.keys())
        aliases = cls._legacy_aliases()

        unknown_keys = [k for k in d if k not in known_keys and k not in aliases]
        if unknown_keys:
            raise ValueError(
                f"Unknown config key(s): {sorted(unknown_keys)}. "
                f"Valid keys: {sorted(known_keys)}. "
                f"Legacy aliases: {sorted(aliases.keys())}."
            )

        filtered: dict[str, Any] = {}
        for k, v in d.items():
            if k in known_keys:
                filtered[k] = v
            elif k in aliases:
                filtered[aliases[k]] = v

        # Convert channels dict to typed ChannelConfig objects
        if "channels" in filtered and isinstance(filtered["channels"], dict):
            channels: dict[str, ChannelConfig] = {}
            for ch_name, ch_data in filtered["channels"].items():
                if isinstance(ch_data, dict):
                    ct = ChannelType(ch_data.get("channel_type", "voice"))
                    channels[ch_name] = ChannelConfig(
                        channel_type=ct,
                        concurrency=ch_data.get("concurrency", 1),
                        enabled=ch_data.get("enabled", True),
                    )
                else:
                    channels[ch_name] = ch_data
            filtered["channels"] = channels

        cfg = cls(**filtered)
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> Config:
        """Load config from a YAML file using ``yaml.safe_load``."""
        logger.info("Loading config from %s", path)
        with open(path) as f:
            data = yaml.safe_load(f)
        if data is None:
            logger.warning("Config file %s is empty — using defaults", path)
            return cls()
        return cls.from_dict(data)

    @classmethod
    def _legacy_aliases(cls) -> dict[str, str]:
        """Map old key names to new ones."""
        return {
            "interval_length": "interval_length_minutes",
        }

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for field_name in self.__dataclass_fields__:
            val = getattr(self, field_name)
            if field_name == "channels":
                d[field_name] = {
                    k: {
                        "channel_type": v.channel_type.value,
                        "concurrency": v.concurrency,
                        "enabled": v.enabled,
                    }
                    for k, v in val.items()
                }
            else:
                d[field_name] = val
        return d
