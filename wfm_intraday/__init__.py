"""WFM Intraday — public API.

Usage::

    from wfm_intraday import analyze, validate

    result = analyze("forecast.csv", "actuals.csv", mode="as-of", checkpoint="12:00")
    print(result.forecast_accuracy["overall"]["wape"])
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from wfm_intraday.config import Config
from wfm_intraday.domain.models import (
    AnalysisResult,
    IntervalRecord,
    ReconciliationReport,
    ReforecastResult,
    StaffingGap,
)
from wfm_intraday.metrics import calculate_all, calculate_per_lob
from wfm_intraday.validation.inputs import validate_input_files, reconcile_keys

logger = logging.getLogger(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def validate(
    forecast_path: str,
    actuals_path: str,
    staffing_path: Optional[str] = None,
    column_mapping: Optional[Dict[str, str]] = None,
) -> ReconciliationReport:
    """Validate input files and return a reconciliation report.

    Args:
        forecast_path: Path to forecast CSV.
        actuals_path: Path to actuals CSV.
        staffing_path: Optional path to schedule CSV.
        column_mapping: Optional column name mapping dict.

    Returns:
        ReconciliationReport with key-matching statistics.

    Raises:
        FileNotFoundError: If a required input file is missing.
        ValueError: If input columns or values are invalid.
    """
    fc_df, ac_df, sd_df, warns = validate_input_files(
        forecast_path, actuals_path, staffing_path, column_mapping=column_mapping
    )
    report = reconcile_keys(fc_df, ac_df, sd_df)

    print("=== INPUT VALIDATION ===")
    print(f"  Forecast: {report.forecast_rows} rows")
    print(f"  Actuals:  {report.actual_rows} rows")
    if sd_df is not None:
        print(f"  Staffing: {report.scheduled_rows} rows")
    else:
        print("  Staffing: not provided")
    print(f"  Matched keys: {report.matched_keys}")
    if report.has_mismatch:
        if report.forecast_only:
            print(f"  WARNING: {len(report.forecast_only)} forecast-only keys")
        if report.actual_only:
            print(f"  WARNING: {len(report.actual_only)} actual-only keys")
    if warns:
        for w in warns:
            print(f"  WARNING: {w}")

    if report.has_mismatch or warns:
        print("  Status: PASSED WITH WARNINGS")
    else:
        print("  Status: OK")

    return report


def analyze(
    forecast_path: str,
    actuals_path: str,
    staffing_path: Optional[str] = None,
    config_path: Optional[str] = None,
    config_obj: Optional[Config] = None,
    column_mapping: Optional[Dict[str, str]] = None,
    lob_filter: Optional[str] = None,
    date_filter: Optional[str] = None,
    checkpoint: Optional[str] = None,
    mode: str = "retrospective",
) -> AnalysisResult:
    """Run the full WFM analysis pipeline.

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
        ValueError: If input is invalid.
    """
    # ── 1. Load config ─────────────────────────────────────────────────
    config = _load_config(config_obj, config_path)

    # ── 2. Load & validate input data ──────────────────────────────────
    fc_df, ac_df, sd_df, warns = validate_input_files(
        forecast_path, actuals_path, staffing_path, column_mapping=column_mapping
    )
    report = reconcile_keys(fc_df, ac_df, sd_df)

    # ── 3. Filter ─────────────────────────────────────────────────────
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

    # ── 4. Resolve checkpoint ──────────────────────────────────────────
    checkpoint_interval_idx: Optional[int] = None
    if checkpoint:
        checkpoint_minutes = _parse_time(checkpoint)
        checkpoint_interval_idx = _resolve_checkpoint_idx(fc_df, checkpoint_minutes, config)

    # ── 5. Merge forecast + actuals ───────────────────────────────────
    merged_df = fc_df.merge(
        ac_df,
        on=["date", "lob", "interval_start", "channel"],
        how="inner",
        suffixes=("", "_actual"),
    )

    # ── 6. Apply as-of masking ────────────────────────────────────────
    #    In as-of mode, "unknown" future values are set to NaN (not zero).
    #    Zero volume is valid operational data; NaN means "not yet observed."
    as_of_mask: Optional[pd.Series] = None
    if mode == "as-of" and checkpoint_interval_idx is not None:
        as_of_mask = _build_as_of_mask(merged_df, config, checkpoint_interval_idx)

    # ── 7. Compute forecast accuracy (before masking for proper scope) ─
    forecast_accuracy = _compute_forecast_accuracy(merged_df, mode, as_of_mask)

    # ── 8. Compute reforecast (uses actuals only up to checkpoint) ────
    reforecast_results = _compute_reforecast(fc_df, ac_df, config, as_of_mask, mode)

    # ── 9. Build interval records (fully populated) ───────────────────
    intervals = _build_intervals(
        merged_df, config, reforecast_results, sd_df,
        as_of_mask=as_of_mask, mode=mode,
    )

    # ── 10. Compute staffing gaps ──────────────────────────────────────
    gaps = _compute_staffing_gaps(
        merged_df, config, reforecast_results, sd_df,
        as_of_mask=as_of_mask, mode=mode,
    )

    # ── 11. Redistribution (uses canonical gaps) ───────────────────────
    from wfm_intraday.calculator import calculate_redistribution as _calc_redist
    redistribution = _calc_redist(gaps, config)

    # ── 12. Build result ───────────────────────────────────────────────
    metadata: Dict[str, Any] = {
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


def _load_config(config_obj: Optional[Config], config_path: Optional[str]) -> Config:
    if config_obj is not None:
        return config_obj
    if config_path:
        return Config.from_yaml(config_path)
    try:
        return Config.from_yaml("config.yaml")
    except FileNotFoundError:
        return Config()


def _parse_time(t: str) -> int:
    """Parse HH:MM to minutes since midnight."""
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _resolve_checkpoint_idx(
    fc_df: pd.DataFrame, checkpoint_minutes: int, config: Config,
) -> int:
    """Convert a checkpoint time (minutes since midnight) to an interval index.

    Returns the count of intervals fully completed at or before the
    checkpoint time within each day.  Uses the smallest returned value
    across dates (conservative).
    """
    interval_length = config.interval_length_minutes
    interval_end = checkpoint_minutes
    # Count intervals that end at or before checkpoint
    idx = interval_end // interval_length
    return max(0, idx)


def _build_as_of_mask(
    merged_df: pd.DataFrame, config: Config, checkpoint_idx: int,
) -> pd.Series:
    """Build a boolean mask: True = completed (actual data available)."""
    pattern = r"(\d+):(\d+)"
    extracted = merged_df["interval_start"].str.extract(pattern)
    minutes = extracted[0].astype(int) * 60 + extracted[1].astype(int)
    interval_length = config.interval_length_minutes
    # An interval is "completed" if its end time ≤ checkpoint
    interval_end = minutes + interval_length
    checkpoint_minutes = checkpoint_idx * interval_length
    return interval_end <= checkpoint_minutes


def _compute_forecast_accuracy(
    merged_df: pd.DataFrame,
    mode: str,
    as_of_mask: Optional[pd.Series],
) -> Dict[str, Any]:
    """Compute forecast accuracy, scoped to appropriate intervals."""
    if mode == "as-of" and as_of_mask is not None:
        df = merged_df.loc[as_of_mask].copy()
    else:
        df = merged_df

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
    fc_df: pd.DataFrame,
    ac_df: pd.DataFrame,
    config: Config,
    as_of_mask: Optional[pd.Series],
    mode: str,
) -> List[ReforecastResult]:
    """Compute reforecast per (date, lob, channel).

    In as-of mode, only actuals up to the checkpoint influence the scale
    factor.  Future actuals are ignored even if present in the input.
    """
    from wfm_intraday.calculator import calculate_reforecast as _calc

    if mode == "as-of" and as_of_mask is not None:
        # Mask actuals after checkpoint so reforecast only sees completed data
        masked_ac = ac_df.copy()
        # Only mask rows that have an actual_volume column
        for col in ["actual_volume", "actual_aht_seconds"]:
            if col in masked_ac.columns:
                # Figure out which rows are completed by joining with as_of_mask
                # Build a key-based lookup for masking
                merged = fc_df.merge(masked_ac[["date", "lob", "interval_start", "channel"] + [col]],
                                     on=["date", "lob", "interval_start", "channel"],
                                     how="left", suffixes=("", "_right"))
                # We handle this differently: use the as_of_mask approach
                break
        return _calc(fc_df, masked_ac, config, as_of_mask=as_of_mask)
    return _calc(fc_df, ac_df, config)


def _build_intervals(
    merged_df: pd.DataFrame,
    config: Config,
    reforecast_results: List[ReforecastResult],
    schedule_df: Optional[pd.DataFrame],
    as_of_mask: Optional[pd.Series] = None,
    mode: str = "retrospective",
) -> List[IntervalRecord]:
    """Build fully-populated interval records including all computed values."""
    from wfm_intraday.calculator import (
        _compute_staffing_req,
        _channel_from_row,
    )

    interval_seconds = config.interval_length_minutes * 60

    # Build reforecast lookup: (date, lob, channel) -> list of adjusted volumes
    reforecast_lookup: Dict[str, List[float]] = {}
    for rr in reforecast_results:
        key = f"{rr.date}|{rr.lob}|{rr.channel}"
        reforecast_lookup[key] = rr.adjusted_forecast

    # Build schedule lookup
    schedule_lookup: Dict[str, float] = {}
    if schedule_df is not None and not schedule_df.empty:
        for _, row in schedule_df.iterrows():
            key = f"{row['date']}|{row['lob']}|{row['interval_start']}|{row['channel']}"
            schedule_lookup[key] = float(row["scheduled_fte"])

    # Sort by date, interval for ordered indexing into reforecast list
    merged_df = merged_df.sort_values(["date", "lob", "channel", "interval_start"]).reset_index(drop=True)

    intervals: List[IntervalRecord] = []
    group_counts: Dict[str, int] = {}

    for _, row in merged_df.iterrows():
        date_val = str(row["date"])
        lob_val = str(row["lob"])
        ch = _channel_from_row(row, config)
        int_start = str(row["interval_start"])

        group_key = f"{date_val}|{lob_val}|{ch}"
        idx = group_counts.get(group_key, 0)
        group_counts[group_key] = idx + 1

        forecast_vol = float(row["forecast_volume"])
        forecast_aht = float(row.get("forecast_aht_seconds", config.aht_seconds))
        actual_vol_raw = row.get("actual_volume")
        actual_aht_raw = row.get("actual_aht_seconds")

        # Determine whether this interval is completed
        is_completed = True
        if mode == "as-of" and as_of_mask is not None:
            is_completed = as_of_mask.iloc[idx] if idx < len(as_of_mask) else False

        # Actual values: None for unknown future intervals
        actual_vol: Optional[float] = None
        actual_aht: Optional[float] = None
        if is_completed and actual_vol_raw is not None:
            actual_vol = float(actual_vol_raw) if actual_vol_raw is not None else None
        if is_completed and actual_aht_raw is not None:
            actual_aht = float(actual_aht_raw) if actual_aht_raw is not None else None

        # Reforecast volume
        reforecast_vol: Optional[float] = None
        rf_key = f"{date_val}|{lob_val}|{ch}"
        if rf_key in reforecast_lookup:
            rf_list = reforecast_lookup[rf_key]
            if idx < len(rf_list):
                reforecast_vol = rf_list[idx]

        # Staffing requirements
        fc_req = _compute_staffing_req(forecast_vol, forecast_aht, interval_seconds, config, ch)

        # Actual-based requirement: only for completed intervals
        act_req = None
        if actual_vol is not None and actual_aht is not None and actual_vol > 0:
            act_req = _compute_staffing_req(actual_vol, actual_aht, interval_seconds, config, ch)

        # Reforecast-based requirement
        rf_req = None
        if reforecast_vol is not None and reforecast_vol > 0:
            rf_req = _compute_staffing_req(reforecast_vol, forecast_aht, interval_seconds, config, ch)

        # Scheduled FTE
        sch_key = f"{date_val}|{lob_val}|{int_start}|{ch}"
        scheduled_fte = schedule_lookup.get(sch_key)

        # Staffing gap: for completed intervals use actual, for future use reforecast
        staffing_gap_fte: Optional[float] = None
        if scheduled_fte is not None:
            if is_completed and act_req is not None:
                staffing_gap_fte = act_req.gross_fte - scheduled_fte
            elif not is_completed and rf_req is not None:
                staffing_gap_fte = rf_req.gross_fte - scheduled_fte
            elif act_req is not None:
                staffing_gap_fte = act_req.gross_fte - scheduled_fte

        intervals.append(IntervalRecord(
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
        ))

    return intervals


def _compute_staffing_gaps(
    merged_df: pd.DataFrame,
    config: Config,
    reforecast_results: List[ReforecastResult],
    schedule_df: Optional[pd.DataFrame],
    as_of_mask: Optional[pd.Series] = None,
    mode: str = "retrospective",
) -> List[StaffingGap]:
    """Compute StaffingGap objects with proper future-interval handling."""
    from wfm_intraday.calculator import (
        _compute_staffing_req,
        _channel_from_row,
    )

    interval_seconds = config.interval_length_minutes * 60

    # Build schedule lookup
    schedule_lookup: Dict[str, float] = {}
    if schedule_df is not None and not schedule_df.empty:
        for _, row in schedule_df.iterrows():
            key = f"{row['date']}|{row['lob']}|{row['interval_start']}|{row['channel']}"
            schedule_lookup[key] = float(row["scheduled_fte"])

    # Build reforecast lookup
    reforecast_lookup: Dict[str, List[float]] = {}
    for rr in reforecast_results:
        key = f"{rr.date}|{rr.lob}|{rr.channel}"
        reforecast_lookup[key] = rr.adjusted_forecast

    merged_df = merged_df.sort_values(["date", "lob", "channel", "interval_start"]).reset_index(drop=True)
    gaps: List[StaffingGap] = []
    group_counts: Dict[str, int] = {}

    for _, row in merged_df.iterrows():
        date_val = str(row["date"])
        lob_val = str(row["lob"])
        ch = _channel_from_row(row, config)
        int_start = str(row["interval_start"])

        group_key = f"{date_val}|{lob_val}|{ch}"
        idx = group_counts.get(group_key, 0)
        group_counts[group_key] = idx + 1

        forecast_vol = float(row["forecast_volume"])
        forecast_aht = float(row.get("forecast_aht_seconds", config.aht_seconds))
        actual_vol = float(row.get("actual_volume", 0))
        actual_aht = float(row.get("actual_aht_seconds", config.aht_seconds))

        is_completed = True
        if mode == "as-of" and as_of_mask is not None:
            is_completed = as_of_mask.iloc[idx] if idx < len(as_of_mask) else True

        fc_req = _compute_staffing_req(forecast_vol, forecast_aht, interval_seconds, config, ch)
        act_req = _compute_staffing_req(actual_vol, actual_aht, interval_seconds, config, ch)

        # Reforecast-based requirement for future intervals
        rf_net: Optional[float] = None
        rf_gross: Optional[float] = None
        if not is_completed:
            rf_key = f"{date_val}|{lob_val}|{ch}"
            if rf_key in reforecast_lookup:
                rf_list = reforecast_lookup[rf_key]
                if idx < len(rf_list) and rf_list[idx] > 0:
                    rf_req = _compute_staffing_req(
                        rf_list[idx], forecast_aht, interval_seconds, config, ch
                    )
                    rf_net = rf_req.net_fte
                    rf_gross = rf_req.gross_fte

        sch_key = f"{date_val}|{lob_val}|{int_start}|{ch}"
        scheduled_fte = schedule_lookup.get(sch_key)

        # Gap: use reforecast requirement for future intervals
        gap_fte: Optional[float] = None
        status = "no_schedule"

        if scheduled_fte is not None:
            # Choose the appropriate requirement for gap calculation
            if not is_completed and rf_gross is not None:
                required_for_gap = rf_gross
            else:
                required_for_gap = act_req.gross_fte

            gap_fte = required_for_gap - scheduled_fte

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

        gaps.append(StaffingGap(
            date=date_val,
            interval_start=int_start,
            lob=lob_val,
            channel=ch,
            forecast_required_net_fte=fc_req.net_fte,
            forecast_required_gross_fte=fc_req.gross_fte,
            actual_required_net_fte=act_req.net_fte,
            actual_required_gross_fte=act_req.gross_fte,
            reforecast_required_net_fte=rf_net,
            reforecast_required_gross_fte=rf_gross,
            scheduled_fte=scheduled_fte,
            gap_fte=gap_fte,
            status=status,
        ))

    return gaps