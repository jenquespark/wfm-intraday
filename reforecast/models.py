"""Data models for WFM Reforecast Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class IntervalData:
    """A single interval's forecast and actual data for one LOB."""

    date: str
    lob: str
    interval_start: str
    forecast_volume: float
    forecast_aht: float
    actual_volume: float
    actual_aht: float


@dataclass(frozen=True)
class StaffingGap:
    """Staffing gap for one interval of one LOB."""

    interval: str
    lob: str
    required_fte: float
    scheduled_fte: float
    gap: float  # positive = understaffed, negative = overstaffed
    status: str  # 'overstaffed', 'understaffed', 'balanced'


@dataclass(frozen=True)
class AccuracyMetrics:
    """Forecast accuracy metrics for a LOB or overall."""

    wape: float  # Weighted Absolute Percentage Error
    mape: float  # Mean Absolute Percentage Error (%)
    bias: float  # Forecast bias (positive = underforecast)


@dataclass(frozen=True)
class ReforecastResult:
    """Result of intra-day reforecasting at a checkpoint interval."""

    checkpoint_interval: int
    original_forecast: List[float]
    adjusted_forecast: List[float]
    blend_factor: float


# Expected column schema for forecast and actual CSV files
FORECAST_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "forecast_volume", "forecast_aht",
]
ACTUALS_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "actual_volume", "actual_aht",
]


def validate_columns(expected: List[str], actual: List[str]) -> None:
    """Validate that actual columns contain all expected columns.

    Args:
        expected: List of required column names.
        actual: List of column names found in the file.

    Raises:
        ValueError: With a clear message listing missing and unexpected columns.
    """
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]

    if missing or extra:
        parts: List[str] = []
        if missing:
            parts.append(f"Missing columns: {sorted(missing)}")
        if extra:
            parts.append(f"Unexpected columns: {sorted(extra)}")
        parts.append(f"Expected columns: {sorted(expected)}")
        raise ValueError(" | ".join(parts))