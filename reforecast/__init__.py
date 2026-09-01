"""WFM Reforecast Engine — public API.

Usage::

    from reforecast import analyze

    result = analyze("forecast.csv", "actuals.csv")
    print(result.forecast_accuracy["overall"]["wape"])
"""

from __future__ import annotations

__version__ = "0.1.0"

import logging
import os
from typing import Any, Dict, List, Optional
from pathlib import Path

from reforecast.config import Config
from reforecast.domain.models import (
    AnalysisResult,
    IntervalRecord,
    ReconciliationReport,
    ReforecastResult,
    RedistributionRecommendation,
    StaffingGap,
)
from reforecast.metrics import calculate_all, calculate_per_lob
from reforecast.validation.inputs import validate_input_files, reconcile_keys
from reforecast.adapters import get_adapter

logger = logging.getLogger(__name__)


def validate(
    forecast_path: str,
    actuals_path: str,
    staffing_path: Optional[str] = None,
    config_path: Optional[str] = None,
) -> ReconciliationReport:
    """Validate input files and return a reconciliation report."""
    fc_df, ac_df, sd_df, _ = validate_input_files(forecast_path, actuals_path, staffing_path)
    return reconcile_keys(fc_df, ac_df, sd_df)


def analyze(
    forecast_path: str,
    actuals_path: str,
    staffing_path: Optional[str] = None,
    config_path: Optional[str] = None,
    config_obj: Optional[Config] = None,
    lob_filter: Optional[str] = None,
    date_filter: Optional[str] = None,
    checkpoint_override: Optional[str] = None,
    mode: str = "retrospective",
) -> AnalysisResult:
    """Run the full WFM analysis pipeline.

    Args:
        forecast_path: Path to forecast CSV.
        actuals_path: Path to actuals CSV.
        staffing_path: Optional path to schedule/staffing CSV.
        config_path: Path to config YAML (default: config.yaml).
        config_obj: Config object (overrides config_path).
        lob_filter: Optional LOB filter.
        date_filter: Optional date filter (YYYY-MM-DD).
        checkpoint_override: Override checkpoint time (HH:MM).
        mode: "retrospective" (all data) or "as-of" (checkpoint-aware).

    Returns:
        AnalysisResult with all computed data.
    """
    # --- Load config ---
    config = config_obj
    if config is None:
        config = Config.from_yaml(config_path or "config.yaml")

    # --- Load and validate data ---
    fc_df, ac_df, sd_df, warns = validate_input_files(forecast_path, actuals_path, staffing_path)
    report = reconcile_keys(fc_df, ac_df, sd_df)

    # --- Filter ---
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

    # --- Merge ---
    from reforecast.io import merge_forecast_actuals
    merged_df, merge_report = merge_forecast_actuals(fc_df, ac_df)

    # As-of mode: mask actuals after checkpoint
    if mode == "as-of" and checkpoint_override:
        checkpoint_minutes = _parse_time(checkpoint_override)
        before = merged_df["interval_start"].apply(
            lambda t: _parse_time(t) <= checkpoint_minutes
        )
        merged_df.loc[~before, "actual_volume"] = 0.0

    # --- Build metadata ---
    metadata: Dict[str, Any] = {
        "version": __version__,
        "mode": mode,
        "date": date_filter or "all",
        "checkpoint": checkpoint_override or "none",
        "forecast_rows": len(fc_df),
        "actual_rows": len(ac_df),
        "scheduled_rows": len(sd_df) if sd_df is not None else 0,
    }

    # --- Build interval records ---
    intervals: List[IntervalRecord] = []
    for _, row in merged_df.iterrows():
        intervals.append(
            IntervalRecord(
                date=str(row["date"]),
                interval_start=str(row["interval_start"]),
                lob=str(row["lob"]),
                channel=str(row.get("channel", config.channel)),
                forecast_volume=float(row["forecast_volume"]),
                forecast_aht_seconds=float(row.get("forecast_aht_seconds", config.aht_seconds)),
                actual_volume=float(row.get("actual_volume", 0)) or None,
                actual_aht_seconds=float(row.get("actual_aht_seconds", config.aht_seconds)) or None,
            )
        )

    # --- Forecast accuracy ---
    per_lob_metrics = calculate_per_lob(merged_df)
    overall = calculate_all(
        merged_df["actual_volume"].to_numpy(dtype=float),
        merged_df["forecast_volume"].to_numpy(dtype=float),
    )
    forecast_accuracy: Dict[str, Any] = {
        "per_lob": {
            lob: {"wape": round(m.wape, 2), "mape": round(m.mape, 2), "bias": round(m.bias, 4)}
            for lob, m in per_lob_metrics.items()
        },
        "overall": {
            "wape": round(overall.wape, 2),
            "mape": round(overall.mape, 2),
            "bias": round(overall.bias, 4),
        },
    }

    # --- Staffing gaps ---
    from reforecast.calculator import calculate_staffing_gap as _calc_gaps
    gaps = _calc_gaps(merged_df, config, schedule_df=sd_df, lob_filter=lob_filter)

    # --- Redistribution ---
    from reforecast.calculator import calculate_redistribution as _calc_redist
    redistribution = _calc_redist(gaps, config)

    # --- Reforecast ---
    from reforecast.calculator import calculate_reforecast as _calc_reforecast
    reforecast_results = _calc_reforecast(fc_df, ac_df, config, lob_filter=lob_filter)

    # --- Build result ---
    result = AnalysisResult(
        metadata=metadata,
        validation=report,
        forecast_accuracy=forecast_accuracy,
        intervals=intervals,
        staffing_gaps=gaps,
        reforecast_results=reforecast_results,
        redistribution=redistribution,
        warnings=warns,
    )

    return result


def generate_sample_data(output_dir: str = "data") -> None:
    """Generate synthetic sample data in *output_dir*."""
    from reforecast.sample_data import generate_synthetic_data
    generate_synthetic_data(output_dir)


def _parse_time(t: str) -> int:
    """Parse HH:MM to minutes since midnight."""
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])