"""Canonical WFM data models — the internal schema used by the engine.

Every input adapter translates source data into these models.
Every calculation operates on these models.
Every output reporter formats these models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class IntervalRecord:
    """A single interval's data for one (date, LOB, channel).

    ``scheduled_fte`` is None when no schedule input was provided.
    ``actual_volume`` and ``actual_aht_seconds`` may be None for
    future intervals in an as-of analysis.
    """

    date: str
    interval_start: str
    lob: str
    channel: str
    forecast_volume: float
    forecast_aht_seconds: float
    actual_volume: Optional[float] = None
    actual_aht_seconds: Optional[float] = None
    reforecast_volume: Optional[float] = None
    scheduled_fte: Optional[float] = None


@dataclass(frozen=True)
class StaffingRequirement:
    """Staffing required for one interval, split into net and gross.

    * net   = agents actively handling contacts (Erlang C result)
    * gross = net uplifted for shrinkage:  gross = net / (1 - shrinkage_pct)
    """

    net_fte: float
    gross_fte: float

    @property
    def shrinkage_fte(self) -> float:
        return self.gross_fte - self.net_fte


@dataclass(frozen=True)
class StaffingGap:
    """Comparison between required and scheduled staffing for one interval."""

    date: str
    interval_start: str
    lob: str
    channel: str
    forecast_required_net_fte: Optional[float] = None
    forecast_required_gross_fte: Optional[float] = None
    actual_required_net_fte: Optional[float] = None
    actual_required_gross_fte: Optional[float] = None
    scheduled_fte: Optional[float] = None
    gap_fte: Optional[float] = None
    status: str = "no_schedule"  # understaffed / overstaffed / balanced / no_schedule


@dataclass(frozen=True)
class AccuracyMetrics:
    """Forecast accuracy for a LOB or overall.

    Conventions:
        * WAPE = sum(|actual - forecast|) / sum(actual) * 100
        * MAPE = mean(|actual - forecast| / actual) * 100
        * bias = sum(actual - forecast) / sum(actual)
    """

    wape: float
    mape: float
    bias: float

    @property
    def wape_fraction(self) -> float:
        return self.wape / 100.0


@dataclass(frozen=True)
class ReforecastResult:
    """Intra-day reforecast for one (date, LOB, channel)."""

    date: str
    lob: str
    channel: str
    checkpoint_interval: int
    deviation_pct: float
    scale_factor: float
    original_forecast: List[float]
    adjusted_forecast: List[float]


@dataclass(frozen=True)
class RedistributionRecommendation:
    """Advisory capacity move between two intervals on the same day/LOB/channel."""

    date: str
    lob: str
    channel: str
    from_interval_start: str
    to_interval_start: str
    recommended_transfer_fte: float
    recommended_transfer_hours: float
    donor_remaining_surplus_fte: float
    rationale: str


@dataclass(frozen=True)
class ReconciliationReport:
    """Key-set reconciliation between input files."""

    forecast_rows: int
    actual_rows: int
    scheduled_rows: int
    matched_keys: int
    forecast_only: List[str]
    actual_only: List[str]
    schedule_only: List[str]

    @property
    def has_mismatch(self) -> bool:
        return bool(self.forecast_only or self.actual_only or self.schedule_only)


@dataclass
class AnalysisResult:
    """Complete result of a WFM analysis run.

    This is the single canonical result object consumed by all reporters
    (CLI, Excel, CSV, JSON, web UI).
    """

    metadata: Dict[str, Any] = field(default_factory=dict)
    validation: Optional[ReconciliationReport] = None
    forecast_accuracy: Dict[str, Any] = field(default_factory=dict)
    intervals: List[IntervalRecord] = field(default_factory=list)
    staffing_gaps: List[StaffingGap] = field(default_factory=list)
    reforecast_results: List[ReforecastResult] = field(default_factory=list)
    redistribution: List[RedistributionRecommendation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# Canonical column schemas -------------------------------------------------

BASE_KEY_COLUMNS: List[str] = ["date", "lob", "interval_start", "channel"]

FORECAST_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "channel",
    "forecast_volume", "forecast_aht_seconds",
]

ACTUALS_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "channel",
    "actual_volume", "actual_aht_seconds",
]

SCHEDULE_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "channel", "scheduled_fte",
]


def validate_columns(expected: List[str], actual: List[str]) -> None:
    """Raise ValueError if any expected column is missing from actual."""
    missing = [c for c in expected if c not in actual]
    if missing:
        raise ValueError(
            f"Missing columns: {sorted(missing)}. "
            f"Expected: {sorted(expected)}. Found: {sorted(actual)}."
        )