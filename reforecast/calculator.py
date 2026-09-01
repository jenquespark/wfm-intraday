"""Core WFM calculations: Erlang C, staffing gaps, redistribution, reforecast."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import math
import numpy as np
import pandas as pd

from reforecast.config import Config
from reforecast.models import (
    AccuracyMetrics,
    IntervalData,
    StaffingGap,
    ReforecastResult,
)

logger = logging.getLogger(__name__)


def _erlang_c_pw(offered_load: float, positions: int) -> float:
    """Compute Erlang C probability of waiting (Pw).

    Uses the standard iterative formula:
        Pw = E^N / (E^N + N! * sum_{k=0}^{N-1} E^k / k!)
    where E = offered_load, N = positions.

    Args:
        offered_load: Traffic intensity in Erlangs.
        positions: Number of agents (positions).

    Returns:
        Probability that a call waits (0 <= Pw <= 1).
    """
    # Hand-coded Erlang C to avoid scipy dependency
    # Use the recursive Erlang B approach then convert to Erlang C
    # Erlang B: B(E, 0) = 1; B(E, n) = E * B(E, n-1) / (E * B(E, n-1) + n)
    erlang_b = 1.0
    for n in range(1, positions + 1):
        erlang_b = offered_load * erlang_b / (offered_load * erlang_b + n)

    # Erlang C: C(E, N) = N * B(E, N) / (N - E * (1 - B(E, N)))
    # when N > E
    if positions <= offered_load:
        return 1.0  # Will always wait when agents <= load
    return positions * erlang_b / (positions - offered_load * (1 - erlang_b))


def erlang_c_required(
    calls_per_interval: float,
    aht_seconds: float,
    interval_seconds: float,
    service_level_target: float,
    sl_threshold_seconds: float,
    max_occupancy: float,
) -> Dict[str, float]:
    """Calculate required Erlang C positions for a single interval.

    Uses the exponential approximation:
        P(wait > t) = Pw * exp(-(N - E) * t / AHT)

    Iterates N upward until service level is met, respecting max_occupancy.

    Args:
        calls_per_interval: Number of calls arriving in this interval.
        aht_seconds: Average handle time in seconds.
        interval_seconds: Length of interval in seconds.
        service_level_target: Target service level fraction (e.g. 0.80).
        sl_threshold_seconds: Service level threshold in seconds.
        max_occupancy: Maximum allowed occupancy fraction.

    Returns:
        Dict with keys:
            - required_positions: Minimum agents needed to meet SL
            - occupancy: Expected occupancy at that staffing level
            - service_level_achieved: Expected service level
            - constrained_by_occupancy: True if max_occupancy cap was applied
    """
    if calls_per_interval <= 0 or aht_seconds <= 0:
        return {
            "required_positions": 0.0,
            "occupancy": 0.0,
            "service_level_achieved": 1.0,
            "constrained_by_occupancy": False,
        }

    offered_load = (calls_per_interval * aht_seconds) / interval_seconds

    # Minimum staff is offered_load + 1 (rounded up)
    min_n = max(1, int(math.ceil(offered_load + 0.5)))

    # Max staff: prevent runaway iteration
    max_n = min_n + 200

    best_n = min_n
    best_sl = 0.0

    for n in range(min_n, max_n + 1):
        # Occupancy at N agents
        occ = offered_load / n
        if occ > max_occupancy:
            # Occupancy cap: we need more agents than offered_load suggests
            continue

        pw = _erlang_c_pw(offered_load, n)

        # Exponential approximation for P(wait > t)
        if n > offered_load:
            p_wait_gt_threshold = pw * math.exp(
                -(n - offered_load) * sl_threshold_seconds / aht_seconds
            )
        else:
            p_wait_gt_threshold = 1.0

        sl_achieved = 1.0 - p_wait_gt_threshold
        best_n = n
        best_sl = sl_achieved

        if sl_achieved >= service_level_target:
            break

    constrained = best_sl < service_level_target
    required = best_n
    occupancy = offered_load / best_n if best_n > 0 else 0.0

    # Shrinkage uplift
    return {
        "required_positions": float(required),
        "occupancy": float(occupancy),
        "service_level_achieved": float(min(1.0, max(0.0, best_sl))),
        "constrained_by_occupancy": bool(constrained),
    }


def calculate_staffing_gap(
    merged_df: pd.DataFrame,
    config: Config,
    lob_filter: Optional[str] = None,
) -> List[StaffingGap]:
    """Calculate staffing gaps per interval per LOB.

    For each interval and LOB, computes:
    - Required FTE via Erlang C + shrinkage uplift
    - Scheduled FTE from available AHT data
    - Gap = required - scheduled (positive = understaffed)

    Args:
        merged_df: DataFrame with merged forecast and actual data.
        config: WFM configuration.
        lob_filter: Optional LOB name to filter.

    Returns:
        List of StaffingGap objects.
    """
    if lob_filter:
        merged_df = merged_df[merged_df["lob"] == lob_filter].copy()
        if merged_df.empty:
            logger.warning("No data found for LOB '%s'", lob_filter)
            return []

    interval_seconds = config.interval_length * 60
    gaps: List[StaffingGap] = []

    for _, row in merged_df.iterrows():
        actual_volume = float(row.get("actual_volume", 0))
        actual_aht = float(row.get("actual_aht", config.aht_seconds))
        forecast_volume = float(row.get("forecast_volume", 0))
        forecast_aht = float(row.get("forecast_aht", config.aht_seconds))

        # Required FTE based on ACTUAL volume (what we really need)
        req_actual = erlang_c_required(
            calls_per_interval=actual_volume,
            aht_seconds=actual_aht,
            interval_seconds=interval_seconds,
            service_level_target=config.service_level,
            sl_threshold_seconds=config.sl_threshold_seconds,
            max_occupancy=config.max_occupancy,
        )
        required_fte = req_actual["required_positions"]

        # Scheduled FTE based on FORECAST volume (what was planned)
        req_forecast = erlang_c_required(
            calls_per_interval=forecast_volume,
            aht_seconds=forecast_aht,
            interval_seconds=interval_seconds,
            service_level_target=config.service_level,
            sl_threshold_seconds=config.sl_threshold_seconds,
            max_occupancy=config.max_occupancy,
        )
        scheduled_fte = req_forecast["required_positions"]

        interval_id = f"{row['date']}_{row['interval_start']}"
        gap = required_fte - scheduled_fte

        # Classify status
        if scheduled_fte <= 0:
            status = "balanced"
        elif gap > config.understaff_threshold_pct * scheduled_fte:
            status = "understaffed"
        elif abs(gap) < config.understaff_threshold_pct * scheduled_fte * 0.5:
            status = "balanced"
        elif gap < -config.overstaff_threshold_pct * scheduled_fte:
            status = "overstaffed"
        else:
            status = "balanced"

        gaps.append(
            StaffingGap(
                interval=interval_id,
                lob=str(row.get("lob", "unknown")),
                required_fte=required_fte,
                scheduled_fte=scheduled_fte,
                gap=gap,
                status=status,
            )
        )

    return gaps


def calculate_redistribution(
    gaps: List[StaffingGap],
    config: Config,
) -> List[Dict[str, Any]]:
    """Generate advisory redistribution recommendations.

    Looks for understaffed and overstaffed intervals and suggests moving
    flexible hours from overstaffed to understaffed slots.

    Args:
        gaps: List of StaffingGap objects.
        config: WFM configuration.

    Returns:
        List of recommendation dicts with keys:
            from_interval, from_lob, to_interval, to_lob,
            flexible_hours, rationale.
    """
    understaffed = [g for g in gaps if g.status == "understaffed"]
    overstaffed = [g for g in gaps if g.status == "overstaffed"]

    recommendations: List[Dict[str, Any]] = []

    for under in understaffed:
        # How many FTE are we short?
        shortage = under.gap  # gap is positive when understaffed
        for over in overstaffed:
            surplus = -over.gap  # gap is negative when overstaffed
            if surplus <= 0 or shortage <= 0:
                continue

            move = min(shortage, surplus)
            if move < 0.1:
                continue  # Skip trivial moves

            recommendations.append(
                {
                    "from_interval": over.interval,
                    "from_lob": over.lob,
                    "to_interval": under.interval,
                    "to_lob": under.lob,
                    "flexible_hours": round(float(move), 2),
                    "rationale": (
                        f"Move {round(float(move), 2)} FTE from overstaffed "
                        f"interval {over.interval} ({over.lob}) to understaffed "
                        f"interval {under.interval} ({under.lob})"
                    ),
                }
            )
            shortage -= move

    return recommendations


def calculate_reforecast(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    config: Config,
    lob_filter: Optional[str] = None,
) -> List[ReforecastResult]:
    """Perform intra-day reforecast for each LOB.

    At the checkpoint interval, compares cumulative actuals vs forecast
    and scales remaining intervals by the blend factor.

    Reforecast formula:
        deviation_pct = (cumulative_actual - cumulative_forecast) / cumulative_forecast
        scale_factor = 1 + blend_factor * deviation_pct
        adjusted_forecast[i] = forecast[i] * scale_factor (for i >= checkpoint)

    Args:
        forecast_df: Forecast dataframe.
        actuals_df: Actuals dataframe.
        config: WFM configuration.
        lob_filter: Optional LOB filter.

    Returns:
        List of ReforecastResult for each LOB.
    """
    results: List[ReforecastResult] = []

    merged = forecast_df.merge(
        actuals_df,
        on=["date", "lob", "interval_start"],
        how="inner",
        suffixes=("", "_actual"),
    )

    if lob_filter:
        merged = merged[merged["lob"] == lob_filter]

    if merged.empty:
        logger.warning("No merged data for reforecast")
        return results

    checkpoint = config.reforecast_checkpoint_interval
    blend = config.reforecast_blend_factor

    for lob_name, group in merged.groupby("lob"):
        group = group.sort_values(["date", "interval_start"])
        group = group.reset_index(drop=True)

        forecasts = group["forecast_volume"].to_numpy(dtype=float)
        actuals_col = "actual_volume" if "actual_volume" in group.columns else "actual_volume_actual"
        actuals = group[actuals_col].to_numpy(dtype=float)

        if len(forecasts) == 0:
            continue

        n_intervals = len(forecasts)

        # Cumulative actuals and forecasts up to checkpoint (exclusive)
        if checkpoint > n_intervals:
            checkpoint = n_intervals - 1

        cum_actual = float(np.sum(actuals[:checkpoint]))
        cum_forecast = float(np.sum(forecasts[:checkpoint]))

        if cum_forecast <= 0:
            logger.warning("Zero cumulative forecast at checkpoint for LOB '%s' — skipping", lob_name)
            continue

        deviation_pct = (cum_actual - cum_forecast) / cum_forecast
        scale = 1.0 + blend * deviation_pct

        # Build adjusted forecast
        adjusted = list(forecasts)
        for i in range(checkpoint, n_intervals):
            adjusted[i] = max(0.0, forecasts[i] * scale)

        assert isinstance(lob_name, str)
        logger.info(
            "Reforecast for LOB '%s': checkpoint=%d, deviation=%.1f%%, scale=%.3f",
            lob_name,
            checkpoint,
            deviation_pct * 100,
            scale,
        )

        results.append(
            ReforecastResult(
                checkpoint_interval=checkpoint,
                original_forecast=list(forecasts),
                adjusted_forecast=adjusted,
                blend_factor=blend,
            )
        )

    return results


def format_summary(
    per_lob_metrics: Dict[str, AccuracyMetrics],
    overall_metrics: AccuracyMetrics,
    gap_counts: Dict[str, int],
    redistribution_count: int,
    reforecast_results: Optional[List[ReforecastResult]] = None,
) -> str:
    """Format a human-readable summary for terminal output.

    Args:
        per_lob_metrics: Per-LOB accuracy metrics.
        overall_metrics: Overall accuracy metrics.
        gap_counts: Dict with 'overstaffed', 'understaffed', 'balanced' counts.
        redistribution_count: Number of redistribution recommendations.
        reforecast_results: Optional reforecast results.

    Returns:
        Formatted summary string.
    """
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("WFM REFORECAST ENGINE — ANALYSIS SUMMARY")
    lines.append("=" * 60)

    lines.append("\n📊 FORECAST ACCURACY")
    for lob, m in sorted(per_lob_metrics.items()):
        lines.append(
            f"  {lob:15s}  WAPE: {m.wape:6.2f}%  "
            f"MAPE: {m.mape:6.2f}%  Bias: {m.bias:+.4f}"
        )
    if overall_metrics:
        lines.append(
            f"  {'OVERALL':15s}  WAPE: {overall_metrics.wape:6.2f}%  "
            f"MAPE: {overall_metrics.mape:6.2f}%  Bias: {overall_metrics.bias:+.4f}"
        )

    lines.append(f"\n📋 STAFFING GAP ANALYSIS")
    lines.append(f"  Understaffed intervals:  {gap_counts.get('understaffed', 0)}")
    lines.append(f"  Overstaffed intervals:   {gap_counts.get('overstaffed', 0)}")
    lines.append(f"  Balanced intervals:      {gap_counts.get('balanced', 0)}")
    lines.append(f"  Redistribution moves:    {redistribution_count}")

    if reforecast_results:
        lines.append(f"\n🔄 REFORECAST CHECKPOINT")
        for rr in reforecast_results:
            orig_total = sum(rr.original_forecast)
            adj_total = sum(rr.adjusted_forecast)
            lines.append(
                f"  Checkpoint={rr.checkpoint_interval}, "
                f"blend={rr.blend_factor:.0%}"
            )
            lines.append(
                f"  Original forecast total: {orig_total:.0f} → "
                f"Adjusted total: {adj_total:.0f}"
            )

    lines.append("\n" + "=" * 60)
    lines.append("Output files written to output/ directory")
    lines.append("Review reforecast_report.xlsx for per-LOB detail.")
    lines.append("=" * 60)

    return "\n".join(lines)