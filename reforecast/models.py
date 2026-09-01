"""Data models for WFM Reforecast Engine.

This module defines the core domain types used across the engine. The naming
is deliberately explicit about what each FTE value represents, because the
most common WFM mistake is conflating *required* staffing with *scheduled*
staffing.

FTE semantics:
    * ``forecast_required_fte``  — staffing needed to meet service targets
      given the *forecast* demand for an interval.
    * ``actual_required_fte``    — staffing needed given the *actual*
      (or reforecasted) demand for an interval.
    * ``scheduled_fte``          — staffing that was *actually planned* for
      the interval, supplied through an explicit schedule input. This value is
      NEVER derived from forecast workload.

Every required-FTE figure is split into net (agents actually handling
contacts) and gross (net uplifted for shrinkage) so the two are never
conflated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class StaffingRequirement:
    """Staffing required for a single interval, split into net and gross.

    net  = agents actively handling contacts (Erlang C result for voice,
           concurrency-aware result for chat, workload result for async).
    gross = net uplifted for shrinkage:  gross = net / (1 - shrinkage_pct).
    """

    net_fte: float
    gross_fte: float

    @property
    def shrinkage_fte(self) -> float:
        """The shrinkage component of gross staffing (gross - net)."""
        return self.gross_fte - self.net_fte


@dataclass(frozen=True)
class StaffingGap:
    """The gap between required and scheduled staffing for one interval.

    ``gap_fte`` is defined as::

        gap_fte = actual_required_gross_fte - scheduled_fte

    * positive  -> understaffed (shortage)
    * negative  -> overstaffed  (surplus)

    ``status`` is one of ``understaffed`` / ``overstaffed`` / ``balanced``.
    ``scheduled_fte`` is only meaningful when schedule input was supplied;
    otherwise it is None and gap analysis against schedule is unavailable.
    """

    date: str
    interval_start: str
    lob: str
    channel: str
    forecast_required_net_fte: Optional[float]
    forecast_required_gross_fte: Optional[float]
    actual_required_net_fte: Optional[float]
    actual_required_gross_fte: Optional[float]
    scheduled_fte: Optional[float]
    gap_fte: Optional[float]  # None when no schedule input
    status: str  # 'understaffed', 'overstaffed', 'balanced', 'no_schedule'


@dataclass(frozen=True)
class AccuracyMetrics:
    """Forecast accuracy metrics.

    Conventions (all derived from actual demand as the denominator):
        * WAPE  = sum(|actual - forecast|) / sum(actual)          (as %)
        * MAPE  = mean(|actual - forecast| / actual) * 100        (as %, per-interval)
        * bias  = sum(actual - forecast) / sum(actual)            (as fraction)
    """

    wape: float
    mape: float
    bias: float

    @property
    def wape_fraction(self) -> float:
        return self.wape / 100.0


@dataclass(frozen=True)
class ReforecastResult:
    """Result of an intra-day reforecast for one (date, lob, channel).

    ``checkpoint`` is the number of completed intervals used to derive the
    scaling factor — it is always interpreted as an *interval index within a
    single operating day*, never a position in a multi-day dataset.
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


@dataclass(frozen=True)
class RedistributionRecommendation:
    """An advisory capacity move from one interval to another.

    This is a *capacity recommendation*, NOT an executable agent schedule.
    It tells a planner how many FTE (or agent-hours) could sensibly move
    from an overstaffed donor interval to an understaffed recipient interval
    on the SAME date and SAME LOB.

    ``recommended_transfer_fte`` is in FTE units.
    ``recommended_transfer_hours`` is in agent-hours (fte * interval_length/60).
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


@dataclass(frozen=True)
class ReconciliationReport:
    """Key-set reconciliation between the supplied input files.

    ``forecast_only`` / ``actual_only`` / ``schedule_only`` are the keys that
    appeared in one file but not another. A non-empty list means data was
    present in the input but could not be matched — this is surfaced rather
    than silently dropped.
    """

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


# Column schemas -----------------------------------------------------------------

BASE_KEY_COLUMNS: List[str] = ["date", "lob", "interval_start"]

FORECAST_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "channel", "forecast_volume", "forecast_aht_seconds",
]

ACTUALS_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "channel", "actual_volume", "actual_aht_seconds",
]

SCHEDULE_COLUMNS: List[str] = [
    "date", "lob", "interval_start", "channel", "scheduled_fte",
]


def validate_columns(expected: List[str], actual: List[str]) -> None:
    """Validate that ``actual`` contains every column in ``expected``.

    Args:
        expected: Required column names.
        actual: Column names found in the file.

    Raises:
        ValueError: Listing missing and unexpected columns with a clear message.
    """
    missing = [c for c in expected if c not in actual]
    if missing:
        raise ValueError(
            "Missing columns: {0}. Expected: {1}. Found: {2}".format(
                sorted(missing), sorted(expected), sorted(actual)
            )
        )
