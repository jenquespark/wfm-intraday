"""Core WFM calculations.

staffing requirements (Erlang C / chat / async),
gap analysis, redistribution recommendations, intra-day reforecast.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from wfm_intraday.config import SUPPORTED_CHANNELS, Config
from wfm_intraday.erlang import (
    chat_required_positions,
    required_positions,
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
    """Extract and validate the channel identifier from a row.

    Channels are normalized with ``strip().lower()``.  Unknown channels and
    ``async`` raise ``ValueError`` — there is NO silent fallback to the config
    default or to voice.
    """
    ch = str(row.get("channel", "")).strip().lower()
    if not ch:
        raise ValueError("channel must not be null or blank")
    if ch == "async":
        raise ValueError("Async staffing is not supported in WFM Intraday 0.2.1")
    if ch not in SUPPORTED_CHANNELS:
        raise ValueError(
            f"Unknown channel '{ch}'. Supported channels: {sorted(SUPPORTED_CHANNELS)}"
        )
    return ch


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

    ``async`` and any unknown channel raise ``ValueError``.

    Zero volume is a valid known zero and produces a zero requirement (not
    ``None``).

    Gross FTE is net FTE uplifted by the shrinkage factor:

        gross_fte = net_fte / (1 - shrinkage_pct)

    Shrinkage near 1.0 is NOT silently clamped — config validation rejects
    ``shrinkage_pct >= 1``.
    """
    ch = str(channel).strip().lower()
    if ch == "async":
        raise ValueError("Async staffing is not supported in WFM Intraday 0.2.1")
    if ch not in SUPPORTED_CHANNELS:
        raise ValueError(
            f"Unknown channel '{ch}'. Supported channels: {sorted(SUPPORTED_CHANNELS)}"
        )

    if volume <= 0 or aht_seconds <= 0:
        return StaffingRequirement(net_fte=0.0, gross_fte=0.0)

    s = 1.0 - config.shrinkage_pct

    if ch == "chat":
        req = chat_required_positions(
            chats_per_interval=volume,
            aht_seconds=aht_seconds,
            interval_seconds=interval_seconds,
            concurrency=config.chat_concurrency,
            occupancy_target=config.max_occupancy,
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
# 2.  Redistribution (advisory capacity recommendations)
# ════════════════════════════════════════════════════════════════════════════


def _parse_interval_index(interval_id: str) -> int:
    """Parse an interval_start like '10:30' to minutes since midnight."""
    try:
        parts = interval_id.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def calculate_redistribution(
    gaps: list[StaffingGap],
    config: Config,
    mode: str = "retrospective",
    checkpoint_minutes: int | None = None,
) -> list[RedistributionRecommendation]:
    """Generate advisory capacity redistribution recommendations.

    Rules:
        * Only moves capacity on the SAME date, SAME LOB, SAME channel.
        * Donor surplus is consumed and cannot be reused (donor-conserving).
        * Movement is FORWARD-ONLY in time: a donor (overstaffed interval) may
          fund a recipient (understaffed interval) only when the donor precedes
          or equals the recipient in clock time.
        * In ``as-of`` mode, redistribution is FUTURE-ONLY: only intervals with
          an interval START time at or after the checkpoint are eligible as
          recipients, and only intervals already completed are excluded as
          donors (you cannot move capacity that is already in the past).
        * Movement window is limited by ``max_movement_window_minutes``.
        * Cross-day transfers are PROHIBITED.
    """
    recommendations: list[RedistributionRecommendation] = []
    groups: dict[tuple[str, str, str], list[StaffingGap]] = {}
    for g in gaps:
        key = (g.date, g.lob, g.channel)
        groups.setdefault(key, []).append(g)

    interval_hours = config.interval_length_minutes / 60.0
    window_minutes = config.max_movement_window_minutes

    for (date, lob, channel), group in groups.items():
        understaffed = sorted(
            [
                g
                for g in group
                if g.status == "understaffed" and g.gap_fte is not None and g.gap_fte > 0
            ],
            key=lambda g: _parse_interval_index(g.interval_start),
        )
        overstaffed = sorted(
            [
                g
                for g in group
                if g.status == "overstaffed" and g.gap_fte is not None and g.gap_fte < 0
            ],
            key=lambda g: _parse_interval_index(g.interval_start),
        )

        # In as-of mode, only FUTURE intervals are eligible recipients, and
        # only FUTURE intervals may act as donors (past capacity is spent).
        # "Future" uses the SAME key/time predicate as the rest of the
        # pipeline: an interval is completed iff its END time
        # (interval_start + interval_length) <= checkpoint.  A non-completed
        # (future) interval has END > checkpoint.  This keeps redistribution
        # consistent with reforecast / IntervalRecord / StaffingGap /
        # accuracy and independent of input row order.
        if mode == "as-of" and checkpoint_minutes is not None:

            def _is_future(g) -> bool:
                return (
                    _parse_interval_index(g.interval_start) + config.interval_length_minutes
                    > checkpoint_minutes
                )

            understaffed = [g for g in understaffed if _is_future(g)]
            overstaffed = [g for g in overstaffed if _is_future(g)]

        donor_remaining: dict[str, float] = {}
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

                # FORWARD-ONLY: donor must not be later than recipient.
                if over_idx > under_idx:
                    continue

                # Movement window.
                if (under_idx - over_idx) > window_minutes:
                    continue

                available = donor_remaining.get(over.interval_start, 0.0)
                if available <= 0:
                    continue

                move = min(shortage, available)
                if move < 0.1:
                    continue

                donor_remaining[over.interval_start] = available - move
                shortage -= move

                recommendations.append(
                    RedistributionRecommendation(
                        date=date,
                        lob=lob,
                        channel=channel,
                        from_interval_start=over.interval_start,
                        to_interval_start=under.interval_start,
                        recommended_transfer_fte=round(float(move), 2),
                        recommended_transfer_hours=round(float(move) * interval_hours, 2),
                        donor_remaining_surplus_fte=round(
                            float(donor_remaining[over.interval_start]), 2
                        ),
                        rationale=(
                            f"Move {round(float(move), 2)} FTE "
                            f"({round(float(move) * interval_hours, 2)} agent-hours) "
                            f"from overstaffed interval {over.interval_start} ({lob}/{channel}) "
                            f"to understaffed interval {under.interval_start} ({lob}/{channel}) "
                            f"on {date}"
                        ),
                    )
                )

                if shortage <= 0:
                    break

    return recommendations


# ════════════════════════════════════════════════════════════════════════════
# 3.  Summary formatting
# ════════════════════════════════════════════════════════════════════════════


def format_summary(
    per_lob_metrics: dict[str, AccuracyMetrics],
    overall_metrics: AccuracyMetrics,
    gap_counts: dict[str, int],
    redistribution_count: int,
    reforecast_results: list[ReforecastResult] | None = None,
    reconciliation: ReconciliationReport | None = None,
) -> str:
    """Format a human-readable summary for terminal output."""
    from wfm_intraday.models import ReconciliationReport as RR

    if reconciliation is None:
        reconciliation = RR(
            forecast_rows=0,
            actual_rows=0,
            scheduled_rows=0,
            matched_keys=0,
            forecast_only=[],
            actual_only=[],
            schedule_only=[],
        )

    lines: list[str] = []
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
            f"  {lob:15s}  WAPE: {m.wape:6.2f}%  MAPE: {m.mape:6.2f}%  Bias: {m.bias:+.4f}"
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
