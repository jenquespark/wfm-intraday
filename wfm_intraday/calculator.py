"""Core WFM calculations.

    staffing requirements (Erlang C / chat / async),
    gap analysis, redistribution recommendations, intra-day reforecast.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from wfm_intraday.config import Config
from wfm_intraday.erlang import (
    required_positions,
    chat_required_positions,
    async_required_positions,
)
from wfm_intraday.models import (
    AccuracyMetrics,
    ReconciliationReport,
    RedistributionRecommendation,
    ReforecastResult,
    StaffingGap,
    StaffingRequirement,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# 1.  Staffing requirements
# ════════════════════════════════════════════════════════════════════════════


def _channel_from_row(row: pd.Series, config: Config) -> str:
    """Extract the channel identifier from a row, falling back to config default."""
    ch = str(row.get("channel", "")).strip().lower()
    if ch and ch in ("voice", "chat", "async"):
        return ch
    return config.channel


def _compute_staffing_req(
    volume: float,
    aht_seconds: float,
    interval_seconds: int,
    config: Config,
    channel: str = "voice",
) -> StaffingRequirement:
    """Compute net and gross staffing required for one interval.

    ``channel`` selects the model:
        * ``voice`` — Erlang C (classical queueing).
        * ``chat``  — concurrency-aware.
        * ``async`` — workload / capacity model.

    Gross FTE is net FTE uplifted by the shrinkage factor:

        gross_fte = net_fte / (1 - shrinkage_pct)

    Shrinkage values near 1.0 are NOT silently clamped — the math is
    gross = net / (1 - s).  Config validation rejects s >= 1.0.
    """
    s = 1.0 - config.shrinkage_pct

    if channel == "chat":
        req = chat_required_positions(
            chats_per_interval=volume,
            aht_seconds=aht_seconds,
            interval_seconds=interval_seconds,
            concurrency=config.chat_concurrency,
            occupancy_target=config.max_occupancy,
        )
    elif channel == "async":
        req = async_required_positions(
            items_per_interval=volume,
            aht_seconds=aht_seconds,
            service_hours_per_day=config.async_service_hours_per_day,
            sla_business_days=config.async_sla_business_days,
        )
    else:  # voice
        req = required_positions(
            calls_per_interval=volume,
            aht_seconds=aht_seconds,
            interval_seconds=interval_seconds,
            service_level_target=config.service_level,
            sl_threshold_seconds=config.sl_threshold_seconds,
            max_occupancy=config.max_occupancy,
        )

    net = req["required_positions"]
    gross = net / s  # config.validate() guarantees s > 0

    return StaffingRequirement(net_fte=net, gross_fte=gross)


# Public alias for backward compatibility
compute_staffing_requirement = _compute_staffing_req


# ════════════════════════════════════════════════════════════════════════════
# 2.  Staffing gap analysis
# ════════════════════════════════════════════════════════════════════════════


def calculate_staffing_gap(
    merged_df: pd.DataFrame,
    config: Config,
    schedule_df: Optional[pd.DataFrame] = None,
    lob_filter: Optional[str] = None,
) -> List[StaffingGap]:
    """Calculate staffing gaps per interval per (date, lob, channel).

    ``forecast_required_fte`` is derived from forecast volume.
    ``actual_required_fte``   is derived from actual volume.
    ``scheduled_fte``         is only filled when ``schedule_df`` is supplied.

    The gap is: actual_required_gross_fte - scheduled_fte
    * positive → understaffed (shortage)
    * negative → overstaffed (surplus)
    """
    if lob_filter:
        merged_df = merged_df[merged_df["lob"] == lob_filter].copy()
        if merged_df.empty:
            logger.warning("No data found for LOB '%s'", lob_filter)
            return []

    interval_seconds = config.interval_length_minutes * 60
    gaps: List[StaffingGap] = []

    schedule_lookup: Dict[Tuple[str, str, str, str], float] = {}
    if schedule_df is not None and not schedule_df.empty:
        for _, row in schedule_df.iterrows():
            key = (
                str(row["date"]), str(row["lob"]),
                str(row["interval_start"]), str(row.get("channel", config.channel)),
            )
            schedule_lookup[key] = float(row["scheduled_fte"])

    for _, row in merged_df.iterrows():
        actual_vol = float(row.get("actual_volume", 0))
        actual_aht = float(row.get("actual_aht_seconds", config.aht_seconds))
        forecast_vol = float(row.get("forecast_volume", 0))
        forecast_aht = float(row.get("forecast_aht_seconds", config.aht_seconds))
        ch = _channel_from_row(row, config)

        date_val = str(row["date"])
        interval_start = str(row["interval_start"])
        lob = str(row["lob"])

        fc_req = _compute_staffing_req(forecast_vol, forecast_aht, interval_seconds, config, ch)
        act_req = _compute_staffing_req(actual_vol, actual_aht, interval_seconds, config, ch)

        schedule_key = (date_val, lob, interval_start, ch)
        scheduled_fte = schedule_lookup.get(schedule_key)

        gap_fte: Optional[float] = None
        status = "balanced"
        if scheduled_fte is not None:
            gap_fte = act_req.gross_fte - scheduled_fte
            if scheduled_fte <= 0:
                status = "no_schedule"
            elif gap_fte > config.understaff_threshold_pct * scheduled_fte:
                status = "understaffed"
            elif abs(gap_fte) < config.understaff_threshold_pct * scheduled_fte * 0.5:
                status = "balanced"
            elif gap_fte < -config.overstaff_threshold_pct * scheduled_fte:
                status = "overstaffed"
            else:
                status = "balanced"
        else:
            status = "no_schedule"

        gaps.append(StaffingGap(
            date=date_val,
            interval_start=interval_start,
            lob=lob,
            channel=ch,
            forecast_required_net_fte=fc_req.net_fte,
            forecast_required_gross_fte=fc_req.gross_fte,
            actual_required_net_fte=act_req.net_fte,
            actual_required_gross_fte=act_req.gross_fte,
            scheduled_fte=scheduled_fte,
            gap_fte=gap_fte,
            status=status,
        ))

    return gaps


# ════════════════════════════════════════════════════════════════════════════
# 3.  Redistribution (advisory capacity recommendations)
# ════════════════════════════════════════════════════════════════════════════


def _parse_interval_index(interval_id: str) -> int:
    """Parse an interval_start like '10:30' to minutes since midnight."""
    try:
        parts = interval_id.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def calculate_redistribution(
    gaps: List[StaffingGap],
    config: Config,
) -> List[RedistributionRecommendation]:
    """Generate advisory capacity redistribution recommendations.

    Rules:
        * Only moves capacity on the SAME date, SAME LOB, SAME channel.
        * Donor surplus is consumed and cannot be reused.
        * Movement window is limited by ``max_movement_window_intervals``.
        * Cross-day transfers are PROHIBITED.
    """
    recommendations: List[RedistributionRecommendation] = []
    groups: Dict[Tuple[str, str, str], List[StaffingGap]] = {}
    for g in gaps:
        key = (g.date, g.lob, g.channel)
        groups.setdefault(key, []).append(g)

    interval_hours = config.interval_length_minutes / 60.0
    window_intervals = config.max_movement_window_intervals

    for (date, lob, channel), group in groups.items():
        understaffed = sorted(
            [g for g in group if g.status == "understaffed" and g.gap_fte is not None and g.gap_fte > 0],
            key=lambda g: _parse_interval_index(g.interval_start),
        )
        overstaffed = sorted(
            [g for g in group if g.status == "overstaffed" and g.gap_fte is not None and g.gap_fte < 0],
            key=lambda g: _parse_interval_index(g.interval_start),
        )

        donor_remaining: Dict[str, float] = {}
        for o in overstaffed:
            donor_remaining[o.interval_start] = -o.gap_fte  # surplus is positive

        for under in understaffed:
            if under.gap_fte is None:
                continue
            shortage = under.gap_fte
            if shortage <= 0:
                continue

            under_idx = _parse_interval_index(under.interval_start)

            for over in overstaffed:
                over_idx = _parse_interval_index(over.interval_start)
                if abs(under_idx - over_idx) > window_intervals * config.interval_length_minutes:
                    continue

                available = donor_remaining.get(over.interval_start, 0.0)
                if available <= 0:
                    continue

                move = min(shortage, available)
                if move < 0.1:
                    continue

                donor_remaining[over.interval_start] = available - move
                shortage -= move

                recommendations.append(RedistributionRecommendation(
                    date=date,
                    lob=lob,
                    channel=channel,
                    from_interval_start=over.interval_start,
                    to_interval_start=under.interval_start,
                    recommended_transfer_fte=round(float(move), 2),
                    recommended_transfer_hours=round(float(move) * interval_hours, 2),
                    donor_remaining_surplus_fte=round(float(donor_remaining[over.interval_start]), 2),
                    rationale=(
                        f"Move {round(float(move), 2)} FTE "
                        f"({round(float(move) * interval_hours, 2)} agent-hours) "
                        f"from overstaffed interval {over.interval_start} ({lob}/{channel}) "
                        f"to understaffed interval {under.interval_start} ({lob}/{channel}) "
                        f"on {date}"
                    ),
                ))

                if shortage <= 0:
                    break

    return recommendations


# ════════════════════════════════════════════════════════════════════════════
# 4.  Intra-day reforecast (per-date, per-LOB, per-channel)
# ════════════════════════════════════════════════════════════════════════════


def calculate_reforecast(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    config: Config,
    lob_filter: Optional[str] = None,
    as_of_mask: Optional[pd.Series] = None,
) -> List[ReforecastResult]:
    """Perform intra-day reforecast for each (date, lob, channel).

    The reforecast is computed INDEPENDENTLY per operating day.

    At the checkpoint, cumulative actuals and forecasts are compared and
    the remaining intervals are scaled:

        deviation_pct = (cum_actual - cum_forecast) / cum_forecast
        scale = 1.0 + blend_factor * deviation_pct
        adjusted_forecast[i] = forecast[i] * scale

    In as-of mode, only actuals up to the checkpoint influence the scale
    factor.  Future actuals are ignored via ``as_of_mask``.

    Args:
        forecast_df: Forecast dataframe.
        actuals_df:  Actuals dataframe.
        config:      WFM configuration.
        lob_filter:  Optional LOB name filter.
        as_of_mask:  Boolean mask (True = interval has actual data).

    Returns:
        List of ``ReforecastResult``, one per (date, lob, channel).
    """
    results: List[ReforecastResult] = []

    merged = forecast_df.merge(
        actuals_df,
        on=["date", "lob", "interval_start", "channel"],
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

    for (date, lob, channel), group in merged.groupby(["date", "lob", "channel"]):
        group = group.sort_values("interval_start").reset_index(drop=True)

        forecasts = group["forecast_volume"].to_numpy(dtype=float)
        actuals_col = "actual_volume" if "actual_volume" in group.columns else "actual_volume_actual"
        actuals = group[actuals_col].to_numpy(dtype=float)

        if len(forecasts) == 0:
            continue

        n_intervals = len(forecasts)
        actual_checkpoint = min(checkpoint, n_intervals - 1)

        # In as-of mode, only use actuals up to the checkpoint
        if as_of_mask is not None:
            # Apply mask: zero out actuals after checkpoint so they don't affect
            # the cumulative sum.  This is the CRITICAL look-ahead prevention.
            # We use a local copy so the caller's data is not mutated.
            actuals_used = actuals.copy()
            for i in range(n_intervals):
                if i >= len(as_of_mask) or not as_of_mask.iloc[i % len(as_of_mask)]:
                    actuals_used[i] = 0.0
            cum_actual = float(np.sum(actuals_used[:actual_checkpoint]))
        else:
            cum_actual = float(np.sum(actuals[:actual_checkpoint]))

        cum_forecast = float(np.sum(forecasts[:actual_checkpoint]))

        if cum_forecast <= 0:
            logger.warning(
                "Zero cumulative forecast at checkpoint for %s / %s / %s — skipping",
                date, lob, channel,
            )
            continue

        deviation_pct = (cum_actual - cum_forecast) / cum_forecast
        scale = 1.0 + blend * deviation_pct

        adjusted = list(forecasts)
        for i in range(actual_checkpoint, n_intervals):
            adjusted[i] = max(0.0, forecasts[i] * scale)

        logger.info(
            "Reforecast for %s / %s / %s: checkpoint=%d, deviation=%.1f%%, scale=%.3f",
            date, lob, channel,
            actual_checkpoint, deviation_pct * 100, scale,
        )

        results.append(ReforecastResult(
            date=date,
            lob=lob,
            channel=channel,
            checkpoint_interval=actual_checkpoint,
            deviation_pct=deviation_pct,
            scale_factor=scale,
            blend_factor=blend,
            original_forecast=list(forecasts),
            adjusted_forecast=adjusted,
        ))

    return results


# ════════════════════════════════════════════════════════════════════════════
# 5.  Summary formatting
# ════════════════════════════════════════════════════════════════════════════


def format_summary(
    per_lob_metrics: Dict[str, AccuracyMetrics],
    overall_metrics: AccuracyMetrics,
    gap_counts: Dict[str, int],
    redistribution_count: int,
    reforecast_results: Optional[List[ReforecastResult]] = None,
    reconciliation: Optional[ReconciliationReport] = None,
) -> str:
    """Format a human-readable summary for terminal output."""
    from wfm_intraday.models import ReconciliationReport as RR
    if reconciliation is None:
        reconciliation = RR(
            forecast_rows=0, actual_rows=0, scheduled_rows=0,
            matched_keys=0, forecast_only=[], actual_only=[], schedule_only=[],
        )

    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("WFM INTRADAY — ANALYSIS SUMMARY")
    lines.append("=" * 60)

    if reconciliation.has_mismatch:
        lines.append("\n⚠️  KEY MISMATCH WARNING")
        if reconciliation.forecast_only:
            lines.append(f"  Forecast-only keys: {len(reconciliation.forecast_only)}")
        if reconciliation.actual_only:
            lines.append(f"  Actual-only keys:   {len(reconciliation.actual_only)}")
        if reconciliation.schedule_only:
            lines.append(f"  Schedule-only keys: {len(reconciliation.schedule_only)}")
        lines.append(
            f"  Matched keys: {reconciliation.matched_keys} / {reconciliation.forecast_rows} forecast rows"
        )

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

    lines.append("\n📋 STAFFING GAP ANALYSIS")
    lines.append(f"  Understaffed intervals:  {gap_counts.get('understaffed', 0)}")
    lines.append(f"  Overstaffed intervals:   {gap_counts.get('overstaffed', 0)}")
    lines.append(f"  Balanced intervals:      {gap_counts.get('balanced', 0)}")
    lines.append(f"  No schedule data:        {gap_counts.get('no_schedule', 0)}")
    lines.append(f"  Redistribution moves:    {redistribution_count}")

    if reforecast_results:
        lines.append(f"\n📈 REFORECAST ({len(reforecast_results)} results)")
        for rr in reforecast_results[:5]:
            lines.append(
                f"  {rr.date} {rr.lob:20s} D={rr.deviation_pct:+.2f} "
                f"S={rr.scale_factor:.3f} (n={rr.checkpoint_interval})"
            )
        if len(reforecast_results) > 5:
            lines.append(f"  ... and {len(reforecast_results) - 5} more")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)
