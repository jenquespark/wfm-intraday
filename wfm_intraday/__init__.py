"""WFM Intraday — public API.

Usage::

    from wfm_intraday import analyze, validate

    result = analyze("forecast.csv", "actuals.csv", mode="as-of", checkpoint="12:00")
    print(result.forecast_accuracy["overall"]["wape"])

This module is the *single* analysis service shared by the CLI, the web
interface, and the public Python API.  No other module re-implements the
pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from wfm_intraday._version import __version__
from wfm_intraday.config import SUPPORTED_CHANNELS, Config
from wfm_intraday.domain.models import (
    AnalysisResult,
    IntervalRecord,
    ReconciliationReport,
    ReforecastResult,
    StaffingGap,
)
from wfm_intraday.metrics import calculate_all, calculate_per_lob
from wfm_intraday.validation.inputs import (
    reconcile_keys,
    require_no_mismatch,
    validate_input_files,
)

logger = logging.getLogger(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

_SUPPORTED_MODES = ("retrospective", "as-of")


def validate(
    forecast_path: str,
    actuals_path: str,
    staffing_path: str | None = None,
    column_mapping: dict[str, str] | None = None,
    config_path: str | None = None,
    config_obj: Config | None = None,
) -> ReconciliationReport:
    """Validate input files and return a reconciliation report.

    Args:
        forecast_path: Path to forecast CSV.
        actuals_path: Path to actuals CSV.
        staffing_path: Optional path to schedule CSV.
        column_mapping: Optional column name mapping dict (canonical → source).
        config_path: Optional path to config YAML (may carry column_mapping).
        config_obj: Optional Config object (overrides config_path).

    Returns:
        ReconciliationReport with key-matching statistics.

    Raises:
        FileNotFoundError: If a required input file is missing.
        ValueError: If input columns, values, or duplicates are invalid.
    """
    config = _load_config(config_obj, config_path)
    mapping = column_mapping if column_mapping is not None else config.column_mapping
    fc_df, ac_df, sd_df, _warns = validate_input_files(
        forecast_path, actuals_path, staffing_path, column_mapping=mapping
    )
    return reconcile_keys(fc_df, ac_df, sd_df)


def analyze(
    forecast_path: str,
    actuals_path: str,
    staffing_path: str | None = None,
    config_path: str | None = None,
    config_obj: Config | None = None,
    column_mapping: dict[str, str] | None = None,
    lob_filter: str | None = None,
    date_filter: str | None = None,
    checkpoint: str | None = None,
    mode: str = "retrospective",
) -> AnalysisResult:
    """Run the full WFM analysis pipeline.

    This is the single shared service used by the CLI, web interface, and
    Python API.

    Args:
        forecast_path: Path to forecast CSV.
        actuals_path: Path to actuals CSV.
        staffing_path: Optional path to schedule/staffing CSV.
        config_path: Path to config YAML.
        config_obj: Config object (overrides config_path).
        column_mapping: Optional dict mapping canonical→source column names.
        lob_filter: Optional LOB name filter.
        date_filter: Optional date filter (YYYY-MM-DD).
        checkpoint: Checkpoint time as HH:MM (required for as-of mode).
        mode: ``'retrospective'`` or ``'as-of'``.

    Returns:
        AnalysisResult with all computed data.

    Raises:
        FileNotFoundError: If a required input file is missing.
        ValueError: If input is invalid, keys mismatch, or as-of mode is used
            without a checkpoint.
    """
    # ── 0. Validate request-level arguments ─────────────────────────────
    if mode not in _SUPPORTED_MODES:
        raise ValueError(f"mode must be one of {_SUPPORTED_MODES}, got '{mode}'")
    if mode == "as-of" and checkpoint is None:
        raise ValueError("mode='as-of' requires a checkpoint time (HH:MM)")

    # ── 1. Load config ─────────────────────────────────────────────────
    config = _load_config(config_obj, config_path)

    # ── 2. Load & validate input data ──────────────────────────────────
    mapping = column_mapping if column_mapping is not None else config.column_mapping
    fc_df, ac_df, sd_df, warns = validate_input_files(
        forecast_path, actuals_path, staffing_path, column_mapping=mapping
    )

    # ── 3. Scope the analysis (date + LOB) BEFORE reconciliation ───────
    #    Out-of-scope rows (other days / LOBs) must not create key
    #    mismatches.  Every input is filtered to the same request scope so
    #    staffing is scoped identically and reconciliation only sees the
    #    rows the calculation will actually use.
    if date_filter:
        fc_df = fc_df[fc_df["date"] == date_filter].copy()
        ac_df = ac_df[ac_df["date"] == date_filter].copy()
        if sd_df is not None:
            sd_df = sd_df[sd_df["date"] == date_filter].copy()

    if lob_filter:
        fc_df = fc_df[fc_df["lob"] == lob_filter].copy()
        ac_df = ac_df[ac_df["lob"] == lob_filter].copy()
        if sd_df is not None:
            sd_df = sd_df[sd_df["lob"] == lob_filter].copy()

    # ── 4. Reconcile the SCOPED frames and hard-fail on mismatches ─────
    report = reconcile_keys(fc_df, ac_df, sd_df)

    # Key mismatches hard-fail.  In as-of mode, forecast-only keys are allowed
    # (future intervals); actual-only keys always fail.
    require_no_mismatch(report, mode=mode)

    # ── 5. Resolve checkpoint (single authority = the request parameter) ─
    #    Completion is KEY/TIME based: an interval is completed iff its end
    #    time (interval_start + interval_length) is <= the checkpoint clock
    #    time.  There is no positional or modulo masking.
    checkpoint_minutes: int | None = None
    if checkpoint is not None:
        checkpoint_minutes = _parse_time(checkpoint)

    # ── 6. Merge forecast + actuals (LEFT join => forecast spine preserved) ─
    #    Every forecast interval is retained.  Intervals with no matching
    #    actual row have NaN actual_volume / actual_aht_seconds.
    merged_df = fc_df.merge(
        ac_df,
        on=["date", "lob", "interval_start", "channel"],
        how="left",
        suffixes=("", "_actual"),
    )
    # Normalize column names (left join with matching names keeps names).
    if "actual_volume_actual" in merged_df.columns and "actual_volume" not in merged_df.columns:
        merged_df = merged_df.rename(
            columns={
                "actual_volume_actual": "actual_volume",
                "actual_aht_seconds_actual": "actual_aht_seconds",
            }
        )

    # ── 7. Completion is KEY/TIME based, computed per interval from the
    #       interval start time + config.  There is NO positional mask:
    #       the same predicate is applied to every consumer so the result
    #       is independent of input row order.
    #
    # ── 8. Compute forecast accuracy (as-of scoped to completed) ──────
    forecast_accuracy = _compute_forecast_accuracy(merged_df, config, mode, checkpoint_minutes)

    # ── 9. Compute reforecast (completed actuals only) ───────────────
    reforecast_results = _compute_reforecast(merged_df, config, mode, checkpoint_minutes)

    # ── 10. Build interval records (full forecast spine) ──────────────
    intervals = _build_intervals(
        merged_df,
        config,
        reforecast_results,
        sd_df,
        mode=mode,
        checkpoint_minutes=checkpoint_minutes,
    )

    # ── 10. Compute staffing gaps ──────────────────────────────────────
    gaps = _compute_staffing_gaps(
        merged_df,
        config,
        reforecast_results,
        sd_df,
        mode=mode,
        checkpoint_minutes=checkpoint_minutes,
    )

    # ── 11. Redistribution (uses canonical gaps) ───────────────────────
    from wfm_intraday.calculator import calculate_redistribution as _calc_redist

    redistribution = _calc_redist(gaps, config, mode=mode, checkpoint_minutes=checkpoint_minutes)

    # ── 12. Build result ───────────────────────────────────────────────
    metadata: dict[str, Any] = {
        "version": __version__,
        "mode": mode,
        "date": date_filter or "all",
        "checkpoint": checkpoint or "none",
        "forecast_rows": len(fc_df),
        "actual_rows": len(ac_df),
        "scheduled_rows": len(sd_df) if sd_df is not None else 0,
    }

    return AnalysisResult(
        metadata=metadata,
        validation=report,
        forecast_accuracy=forecast_accuracy,
        intervals=intervals,
        staffing_gaps=gaps,
        reforecast_results=reforecast_results,
        redistribution=redistribution,
        warnings=warns,
    )


def generate_sample_data(output_dir: str = "data") -> None:
    """Generate synthetic sample data in *output_dir*."""
    from wfm_intraday.sample_data import generate_synthetic_data

    generate_synthetic_data(output_dir)


# ════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ════════════════════════════════════════════════════════════════════════════


def _load_config(config_obj: Config | None, config_path: str | None) -> Config:
    if config_obj is not None:
        return config_obj
    if config_path:
        return Config.from_yaml(config_path)
    try:
        return Config.from_yaml("config.yaml")
    except FileNotFoundError:
        return Config()


def _parse_time(t: str) -> int:
    """Parse HH:MM (or HH:MM:SS best-effort) to minutes since midnight."""
    parts = t.strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"checkpoint must be HH:MM, got '{t}'")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        raise ValueError(f"checkpoint must be HH:MM, got '{t}'")
    return hours * 60 + minutes


def _interval_end_minutes(interval_start: str, config: Config) -> int:
    """Minutes since midnight of an interval's END time."""
    start = _parse_time(interval_start)
    return start + config.interval_length_minutes


def _is_completed(
    interval_start: str,
    config: Config,
    mode: str,
    checkpoint_minutes: int | None,
) -> bool:
    """Key/time completion predicate.

    An interval is *completed* iff its END time (interval_start +
    interval_length) is <= the checkpoint clock time.  This is a pure
    function of the interval's canonical key and the checkpoint — there is
    NO positional or modulo masking, so the answer is independent of input
    row order.

    In retrospective mode (no checkpoint) every interval is completed.
    """
    if mode != "as-of" or checkpoint_minutes is None:
        return True
    return _interval_end_minutes(str(interval_start), config) <= checkpoint_minutes


def _compute_forecast_accuracy(
    merged_df: pd.DataFrame,
    config: Config,
    mode: str,
    checkpoint_minutes: int | None,
) -> dict[str, Any]:
    """Compute forecast accuracy, scoped to completed intervals in as-of mode.

    Rows with NaN actual_volume (missing actuals) are excluded so they do not
    contaminate accuracy metrics.
    """
    df = merged_df.copy()
    # Drop rows where actual volume is genuinely missing.
    df = df[df["actual_volume"].notna()]

    if mode == "as-of":
        # Keep only completed intervals (key/time based, order-independent).
        completed = df["interval_start"].map(
            lambda s: _is_completed(str(s), config, mode, checkpoint_minutes)
        )
        df = df[completed.to_numpy(dtype=bool)]

    if df.empty:
        return {"per_lob": {}, "overall": {"wape": 0.0, "mape": 0.0, "bias": 0.0}}

    per_lob = calculate_per_lob(df)
    overall = calculate_all(
        df["actual_volume"].to_numpy(dtype=float),
        df["forecast_volume"].to_numpy(dtype=float),
    )
    return {
        "per_lob": {
            lob: {"wape": round(m.wape, 2), "mape": round(m.mape, 2), "bias": round(m.bias, 4)}
            for lob, m in per_lob.items()
        },
        "overall": {
            "wape": round(overall.wape, 2),
            "mape": round(overall.mape, 2),
            "bias": round(overall.bias, 4),
        },
    }


def _compute_reforecast(
    merged_df: pd.DataFrame,
    config: Config,
    mode: str,
    checkpoint_minutes: int | None,
) -> list[ReforecastResult]:
    """Compute reforecast per (date, lob, channel) using completed actuals.

    In as-of mode, only actuals from COMPLETED intervals influence the scale
    factor.  Completion is key/time based (per-interval from its interval
    start + config), never positional/modulo — so input row order does not
    matter.  Future actuals are ignored even if present in the input.  In
    retrospective mode there is no checkpoint: no scaling is meaningful, so
    we return an empty list.
    """
    if mode == "retrospective":
        return []

    # Per-interval completion (key/time).  usable = completed AND has actual.
    df = merged_df.copy()
    df["_completed_t"] = df["interval_start"].map(
        lambda s: _is_completed(str(s), config, mode, checkpoint_minutes)
    )
    df["_usable"] = (df["_completed_t"]) & (df["actual_volume"].notna())

    results: list[ReforecastResult] = []
    for (date, lob, channel), group in df.groupby(["date", "lob", "channel"]):
        group = group.sort_values("interval_start").reset_index(drop=True)

        # Reject async/unknown channels defensively (should be unreachable).
        ch = str(channel).strip().lower()
        if ch not in SUPPORTED_CHANNELS:
            raise ValueError(f"Unknown channel '{ch}'")

        forecasts = group["forecast_volume"].to_numpy(dtype=float)
        actuals_arr = group["actual_volume"].to_numpy(dtype=float)
        usable = group["_usable"].to_numpy(dtype=bool)

        # Completed actuals only (future actuals contribute exactly zero).
        cum_actual = float(actuals_arr[usable].sum())
        # Forecast over the same completed intervals for apples-to-apples.
        cum_forecast = float(forecasts[usable].sum())

        if cum_forecast <= 0:
            continue

        deviation_pct = (cum_actual - cum_forecast) / cum_forecast
        scale = 1.0 + config.reforecast_blend_factor * deviation_pct

        # Apply scale to FUTURE (non-completed) intervals only.
        adjusted = list(forecasts)
        for i in range(len(adjusted)):
            if not usable[i]:
                adjusted[i] = max(0.0, forecasts[i] * scale)

        n_completed = int(usable.sum())
        results.append(
            ReforecastResult(
                date=str(date),
                lob=str(lob),
                channel=ch,
                checkpoint_interval=n_completed,
                deviation_pct=deviation_pct,
                scale_factor=scale,
                blend_factor=config.reforecast_blend_factor,
                original_forecast=list(forecasts),
                adjusted_forecast=adjusted,
            )
        )

    return results


def _build_reforecast_lookup(
    reforecast_results: list[ReforecastResult],
) -> dict[tuple[str, str, str], list[float]]:
    lookup: dict[tuple[str, str, str], list[float]] = {}
    for rr in reforecast_results:
        lookup[(rr.date, rr.lob, rr.channel)] = rr.adjusted_forecast
    return lookup


def _build_schedule_lookup(
    schedule_df: pd.DataFrame | None,
) -> dict[tuple[str, str, str, str], float]:
    lookup: dict[tuple[str, str, str, str], float] = {}
    if schedule_df is not None and not schedule_df.empty:
        for _, row in schedule_df.iterrows():
            key = (
                str(row["date"]),
                str(row["lob"]),
                str(row["interval_start"]),
                str(row["channel"]).strip().lower(),
            )
            lookup[key] = float(row["scheduled_fte"])
    return lookup


def _build_intervals(
    merged_df: pd.DataFrame,
    config: Config,
    reforecast_results: list[ReforecastResult],
    sd_df: pd.DataFrame | None,
    mode: str = "retrospective",
    checkpoint_minutes: int | None = None,
) -> list[IntervalRecord]:
    """Build fully-populated interval records (full forecast spine)."""
    from wfm_intraday.calculator import _channel_from_row, _compute_staffing_req

    interval_seconds = config.interval_length_minutes * 60
    reforecast_lookup = _build_reforecast_lookup(reforecast_results)
    schedule_lookup = _build_schedule_lookup(sd_df)

    merged_df = merged_df.sort_values(["date", "lob", "channel", "interval_start"]).reset_index(
        drop=True
    )

    intervals: list[IntervalRecord] = []
    group_counts: dict[tuple[str, str, str], int] = {}

    for i, row in merged_df.iterrows():
        date_val = str(row["date"])
        lob_val = str(row["lob"])
        ch = _channel_from_row(row, config)
        int_start = str(row["interval_start"])

        group_key = (date_val, lob_val, ch)
        idx = group_counts.get(group_key, 0)
        group_counts[group_key] = idx + 1

        forecast_vol = float(row["forecast_volume"])
        forecast_aht = float(row.get("forecast_aht_seconds", config.aht_seconds))

        raw_actual = row.get("actual_volume")
        actual_vol: float | None
        if pd.isna(raw_actual):
            actual_vol = None
        else:
            actual_vol = float(raw_actual)

        raw_aht = row.get("actual_aht_seconds")
        actual_aht: float | None
        if pd.isna(raw_aht):
            actual_aht = None
        else:
            actual_aht = float(raw_aht)

        # Completion status: key/time based (independent of input row order).
        is_completed = _is_completed(int_start, config, mode, checkpoint_minutes)

        # In as-of mode, future intervals have their actuals suppressed (None),
        # independent of whether the input file happened to contain future rows.
        if mode == "as-of" and not is_completed:
            actual_vol = None
            actual_aht = None

        # Reforecast volume for future intervals (as-of).
        reforecast_vol: float | None = None
        rf_list = reforecast_lookup.get(group_key)
        if rf_list is not None and idx < len(rf_list):
            reforecast_vol = rf_list[idx]

        # Staffing requirements.
        fc_req = _compute_staffing_req(forecast_vol, forecast_aht, interval_seconds, config, ch)

        act_req = None
        if actual_vol is not None and actual_aht is not None:
            # Note: zero volume is a REAL zero -> zero requirement, kept as a
            # populated requirement (not None).
            act_req = _compute_staffing_req(actual_vol, actual_aht, interval_seconds, config, ch)

        rf_req = None
        if not is_completed and reforecast_vol is not None:
            rf_req = _compute_staffing_req(
                reforecast_vol, forecast_aht, interval_seconds, config, ch
            )

        sch_key = (date_val, lob_val, int_start, ch)
        scheduled_fte = schedule_lookup.get(sch_key)

        staffing_gap_fte: float | None = None
        if scheduled_fte is not None:
            if is_completed and act_req is not None:
                staffing_gap_fte = act_req.gross_fte - scheduled_fte
            elif not is_completed and rf_req is not None:
                staffing_gap_fte = rf_req.gross_fte - scheduled_fte
            elif act_req is not None:
                staffing_gap_fte = act_req.gross_fte - scheduled_fte

        intervals.append(
            IntervalRecord(
                date=date_val,
                interval_start=int_start,
                lob=lob_val,
                channel=ch,
                forecast_volume=forecast_vol,
                forecast_aht_seconds=forecast_aht,
                actual_volume=actual_vol,
                actual_aht_seconds=actual_aht,
                reforecast_volume=reforecast_vol,
                forecast_required_net_fte=fc_req.net_fte,
                forecast_required_gross_fte=fc_req.gross_fte,
                actual_required_net_fte=act_req.net_fte if act_req else None,
                actual_required_gross_fte=act_req.gross_fte if act_req else None,
                reforecast_required_net_fte=rf_req.net_fte if rf_req else None,
                reforecast_required_gross_fte=rf_req.gross_fte if rf_req else None,
                scheduled_fte=scheduled_fte,
                staffing_gap_fte=staffing_gap_fte,
            )
        )

    return intervals


def _compute_staffing_gaps(
    merged_df: pd.DataFrame,
    config: Config,
    reforecast_results: list[ReforecastResult],
    sd_df: pd.DataFrame | None,
    mode: str = "retrospective",
    checkpoint_minutes: int | None = None,
) -> list[StaffingGap]:
    """Compute StaffingGap objects with proper future-interval handling.

    Zero scheduled FTE is a REAL scheduled zero (status computed against the
    gap), NOT "no_schedule".  "no_schedule" is reserved for intervals with no
    schedule row at all.

    Completion is key/time based (per interval from its interval start +
    config), independent of input row order.  No positional mask is used.
    """
    from wfm_intraday.calculator import _channel_from_row, _compute_staffing_req

    interval_seconds = config.interval_length_minutes * 60
    schedule_lookup = _build_schedule_lookup(sd_df)
    reforecast_lookup = _build_reforecast_lookup(reforecast_results)

    merged_df = merged_df.sort_values(["date", "lob", "channel", "interval_start"]).reset_index(
        drop=True
    )

    gaps: list[StaffingGap] = []
    group_counts: dict[tuple[str, str, str], int] = {}

    for i, row in merged_df.iterrows():
        date_val = str(row["date"])
        lob_val = str(row["lob"])
        ch = _channel_from_row(row, config)
        int_start = str(row["interval_start"])

        group_key = (date_val, lob_val, ch)
        idx = group_counts.get(group_key, 0)
        group_counts[group_key] = idx + 1

        forecast_vol = float(row["forecast_volume"])
        forecast_aht = float(row.get("forecast_aht_seconds", config.aht_seconds))

        raw_actual = row.get("actual_volume")
        actual_vol = None if pd.isna(raw_actual) else float(raw_actual)
        raw_aht = row.get("actual_aht_seconds")
        actual_aht = None if pd.isna(raw_aht) else float(raw_aht)

        is_completed = _is_completed(int_start, config, mode, checkpoint_minutes)

        if mode == "as-of" and not is_completed:
            actual_vol = None
            actual_aht = None

        fc_req = _compute_staffing_req(forecast_vol, forecast_aht, interval_seconds, config, ch)

        act_req = None
        if actual_vol is not None and actual_aht is not None:
            act_req = _compute_staffing_req(actual_vol, actual_aht, interval_seconds, config, ch)

        rf_req = None
        rf_list = reforecast_lookup.get(group_key)
        if not is_completed and rf_list is not None and idx < len(rf_list):
            rf_req = _compute_staffing_req(rf_list[idx], forecast_aht, interval_seconds, config, ch)

        sch_key = (date_val, lob_val, int_start, ch)
        scheduled_fte = schedule_lookup.get(sch_key)

        gap_fte: float | None = None
        status = "no_schedule"

        if scheduled_fte is not None:
            # Choose the appropriate requirement.
            if is_completed and act_req is not None:
                required_gross = act_req.gross_fte
            elif not is_completed and rf_req is not None:
                required_gross = rf_req.gross_fte
            elif act_req is not None:
                required_gross = act_req.gross_fte
            else:
                required_gross = fc_req.gross_fte

            gap_fte = required_gross - scheduled_fte

            # Zero scheduled FTE is a real zero -> must NOT be "no_schedule".
            if gap_fte > config.understaff_threshold_pct * max(scheduled_fte, 1e-9):
                status = "understaffed"
            elif gap_fte < -config.overstaff_threshold_pct * max(scheduled_fte, 1e-9):
                status = "overstaffed"
            else:
                status = "balanced"

        gaps.append(
            StaffingGap(
                date=date_val,
                interval_start=int_start,
                lob=lob_val,
                channel=ch,
                forecast_required_net_fte=fc_req.net_fte,
                forecast_required_gross_fte=fc_req.gross_fte,
                actual_required_net_fte=act_req.net_fte if act_req else None,
                actual_required_gross_fte=act_req.gross_fte if act_req else None,
                reforecast_required_net_fte=rf_req.net_fte if rf_req else None,
                reforecast_required_gross_fte=rf_req.gross_fte if rf_req else None,
                scheduled_fte=scheduled_fte,
                gap_fte=gap_fte,
                status=status,
            )
        )

    return gaps
