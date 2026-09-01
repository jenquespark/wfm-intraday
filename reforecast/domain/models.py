"""Canonical domain models for the WFM Reforecast Engine.

Every typed data object is defined ONCE here.  The module reforecast.models
now re-exports from this module for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Core staffing types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class StaffingRequirement:
    """Staffing required for one interval, split into net and gross.

    * net   = agents actively handling contacts (Erlang C result for voice,
              concurrency-aware for chat, workload for async).
    * gross = net uplifted for shrinkage:  gross = net / (1 - shrinkage_pct).
    """

    net_fte: float
    gross_fte: float

    @property
    def shrinkage_fte(self) -> float:
        return self.gross_fte - self.net_fte


@dataclass(frozen=True)
class StaffingGap:
    """Comparison between required and scheduled staffing for one interval.

    ``gap_fte`` is defined as::

        gap_fte = actual_required_gross_fte - scheduled_fte

    * positive  -> understaffed (shortage)
    * negative  -> overstaffed  (surplus)
    * ``scheduled_fte`` is None when no schedule input was supplied.
    """

    date: str
    interval_start: str
    lob: str
    channel: str
    forecast_required_net_fte: Optional[float] = None
    forecast_required_gross_fte: Optional[float] = None
    actual_required_net_fte: Optional[float] = None
    actual_required_gross_fte: Optional[float] = None
    reforecast_required_net_fte: Optional[float] = None
    reforecast_required_gross_fte: Optional[float] = None
    scheduled_fte: Optional[float] = None
    gap_fte: Optional[float] = None  # None when no schedule input
    status: str = "no_schedule"      # understaffed / overstaffed / balanced / no_schedule


@dataclass(frozen=True)
class AccuracyMetrics:
    """Forecast accuracy metrics.

    Conventions (actual demand as denominator):
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


# ── Reforecast ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReforecastResult:
    """Intra-day reforecast for one (date, LOB, channel).

    ``checkpoint_interval`` is an interval index within a single operating
    day, never a position in a multi-day dataset.
    """

    date: str
    lob: str
    channel: str
    checkpoint_interval: int
    deviation_pct: float
    scale_factor: float
    blend_factor: float
    original_forecast: List[float]
    adjusted_forecast: List[float]


# ── Redistribution ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RedistributionRecommendation:
    """Advisory capacity move between two intervals.

    This is a CAPACITY recommendation, not an executable agent schedule.
    """

    date: str
    lob: str
    channel: str
    from_interval_start: str
    to_interval_start: str
    recommended_transfer_fte: float
    recommended_transfer_hours: float
    donor_remaining_surplus_fte: float
    rationale: str


# ── Reconciliation ─────────────────────────────────────────────────────────


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


# ── Interval record ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IntervalRecord:
    """All computed values for one interval.

    ``scheduled_fte`` is None when no schedule input was provided.
    ``actual_volume`` and ``actual_aht_seconds`` are None for future
    intervals in an as-of analysis.
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
    forecast_required_net_fte: Optional[float] = None
    forecast_required_gross_fte: Optional[float] = None
    actual_required_net_fte: Optional[float] = None
    actual_required_gross_fte: Optional[float] = None
    reforecast_required_net_fte: Optional[float] = None
    reforecast_required_gross_fte: Optional[float] = None
    scheduled_fte: Optional[float] = None
    staffing_gap_fte: Optional[float] = None


# ── Complete analysis result ───────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """Complete result of a WFM analysis run.

    This is the single canonical result object consumed by all reporters
    (CLI, Excel, CSV, JSON, web UI).  No reporter may recompute values.
    """

    metadata: Dict[str, Any] = field(default_factory=dict)
    validation: Optional[ReconciliationReport] = None
    forecast_accuracy: Dict[str, Any] = field(default_factory=dict)
    intervals: List[IntervalRecord] = field(default_factory=list)
    staffing_gaps: List[StaffingGap] = field(default_factory=list)
    reforecast_results: List[ReforecastResult] = field(default_factory=list)
    redistribution: List[RedistributionRecommendation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── Column schemas ─────────────────────────────────────────────────────────

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