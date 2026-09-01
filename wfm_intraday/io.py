"""CSV/Excel/JSON input/output for WFM Intraday."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from wfm_intraday.models import (
    ACTUALS_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
    AccuracyMetrics,
    ReconciliationReport,
    RedistributionRecommendation,
    StaffingGap,
    validate_columns,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_csv(path: str, expected_columns: List[str]) -> pd.DataFrame:
    """Load a CSV file and validate its column schema.

    Args:
        path: Path to CSV file.
        expected_columns: List of required column names.

    Returns:
        DataFrame with the loaded data.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If required columns are missing.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    logger.info("Loading CSV from %s", path)
    df = pd.read_csv(path)
    # Validate but allow extra columns (they may be ignored)
    validate_columns(expected_columns, list(df.columns))
    return df


def load_forecast(path: str) -> pd.DataFrame:
    """Load a forecast CSV file.

    Expected columns: date, lob, interval_start, channel, forecast_volume, forecast_aht_seconds
    """
    return load_csv(path, FORECAST_COLUMNS)


def load_actuals(path: str) -> pd.DataFrame:
    """Load an actuals CSV file.

    Expected columns: date, lob, interval_start, channel, actual_volume, actual_aht_seconds
    """
    return load_csv(path, ACTUALS_COLUMNS)


def load_schedule(path: str) -> pd.DataFrame:
    """Load a schedule/staffing CSV file.

    Expected columns: date, lob, interval_start, channel, scheduled_fte
    """
    return load_csv(path, SCHEDULE_COLUMNS)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_forecast_actuals(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, ReconciliationReport]:
    """Merge forecast and actuals dataframes.

    Uses an inner join on (date, lob, interval_start, channel).  Key
    mismatches are reported in the ``ReconciliationReport`` rather than
    silently dropped.

    Args:
        forecast_df: Forecast dataframe.
        actuals_df:  Actuals dataframe.

    Returns:
        Tuple of (merged DataFrame, ReconciliationReport).
    """
    # Build reconciliation
    fc_keys = set(zip(forecast_df["date"], forecast_df["lob"], forecast_df["interval_start"], forecast_df.get("channel", "")))
    ac_keys = set(zip(actuals_df["date"], actuals_df["lob"], actuals_df["interval_start"], actuals_df.get("channel", "")))

    matched = fc_keys & ac_keys
    forecast_only = fc_keys - ac_keys
    actual_only = ac_keys - fc_keys

    logger.info("Merging forecast and actuals data")
    logger.info(
        "Key reconciliation: %d matched, %d forecast-only, %d actual-only",
        len(matched), len(forecast_only), len(actual_only),
    )

    if forecast_only:
        logger.warning("Forecast-only keys (not in actuals): %d — these will be dropped", len(forecast_only))
    if actual_only:
        logger.warning("Actual-only keys (not in forecast): %d — these will be dropped", len(actual_only))

    merged = forecast_df.merge(
        actuals_df,
        on=["date", "lob", "interval_start", "channel"],
        how="inner",
        suffixes=("", "_actual"),
    )

    reconciliation = ReconciliationReport(
        forecast_rows=len(forecast_df),
        actual_rows=len(actuals_df),
        scheduled_rows=0,
        matched_keys=len(merged),
        forecast_only=sorted(str(k) for k in forecast_only),
        actual_only=sorted(str(k) for k in actual_only),
        schedule_only=[],
    )

    if merged.empty:
        raise ValueError(
            "Forecast and actuals data have no overlapping "
            "(date, lob, interval_start, channel) records"
        )

    # Ensure column naming consistency
    for col in ["actual_aht_seconds", "actual_volume"]:
        alt = col + "_actual"
        if col not in merged.columns and alt in merged.columns:
            merged.rename(columns={alt: col}, inplace=True)

    return merged, reconciliation


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_excel_report(
    path: str,
    dfs_dict: Dict[str, pd.DataFrame],
    per_lob_metrics: Dict[str, AccuracyMetrics],
    overall_metrics: Optional[AccuracyMetrics] = None,
    gaps: Optional[List[StaffingGap]] = None,
    recommendations: Optional[List[RedistributionRecommendation]] = None,
) -> str:
    """Write a multi-sheet Excel report.

    Args:
        path: Output Excel file path.
        dfs_dict: Dict mapping LOB names to interval DataFrames.
        per_lob_metrics: Dict mapping LOB names to AccuracyMetrics.
        overall_metrics: Optional overall accuracy metrics.
        gaps: Optional list of StaffingGap for a gap detail sheet.
        recommendations: Optional redistribution recommendations.

    Returns:
        Path to the written file.
    """
    logger.info("Writing Excel report to %s", path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for lob_name, df in dfs_dict.items():
            sheet_name = str(lob_name)[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Summary sheet
        summary_rows: List[Dict[str, Any]] = []
        for lob_name, metrics in per_lob_metrics.items():
            summary_rows.append({
                "LOB": lob_name,
                "WAPE (%)": round(float(metrics.wape), 2),
                "MAPE (%)": round(float(metrics.mape), 2),
                "Bias": round(float(metrics.bias), 4),
            })
        if overall_metrics:
            summary_rows.append({
                "LOB": "OVERALL",
                "WAPE (%)": round(float(overall_metrics.wape), 2),
                "MAPE (%)": round(float(overall_metrics.mape), 2),
                "Bias": round(float(overall_metrics.bias), 4),
            })
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

        # Staffing gap sheet
        if gaps:
            gap_rows = []
            for g in gaps[:2000]:  # cap rows for Excel
                gap_rows.append({
                    "Date": g.date,
                    "Interval": g.interval_start,
                    "LOB": g.lob,
                    "Channel": g.channel,
                    "Forecast Required Net FTE": round(g.forecast_required_net_fte, 2) if g.forecast_required_net_fte is not None else "",
                    "Forecast Required Gross FTE": round(g.forecast_required_gross_fte, 2) if g.forecast_required_gross_fte is not None else "",
                    "Actual Required Net FTE": round(g.actual_required_net_fte, 2) if g.actual_required_net_fte is not None else "",
                    "Actual Required Gross FTE": round(g.actual_required_gross_fte, 2) if g.actual_required_gross_fte is not None else "",
                    "Scheduled FTE": round(g.scheduled_fte, 2) if g.scheduled_fte is not None else "N/A",
                    "Gap FTE": round(g.gap_fte, 2) if g.gap_fte is not None else "N/A",
                    "Status": g.status,
                })
            pd.DataFrame(gap_rows).to_excel(writer, sheet_name="Staffing_Gaps", index=False)

        # Redistribution sheet
        if recommendations:
            redist_rows = []
            for r in recommendations:
                redist_rows.append({
                    "Date": r.date,
                    "LOB": r.lob,
                    "Channel": r.channel,
                    "From Interval": r.from_interval_start,
                    "To Interval": r.to_interval_start,
                    "Transfer FTE": r.recommended_transfer_fte,
                    "Transfer Hours": r.recommended_transfer_hours,
                    "Donor Remaining Surplus": r.donor_remaining_surplus_fte,
                    "Rationale": r.rationale,
                })
            pd.DataFrame(redist_rows).to_excel(writer, sheet_name="Redistribution", index=False)

    return path


def write_redistribution_csv(path: str, recommendations: List[RedistributionRecommendation]) -> str:
    """Write redistribution recommendations to CSV."""
    logger.info("Writing redistribution plan to %s", path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    rows = [
        {
            "date": r.date,
            "lob": r.lob,
            "channel": r.channel,
            "from_interval": r.from_interval_start,
            "to_interval": r.to_interval_start,
            "recommended_transfer_fte": r.recommended_transfer_fte,
            "recommended_transfer_hours": r.recommended_transfer_hours,
            "donor_remaining_surplus_fte": r.donor_remaining_surplus_fte,
            "rationale": r.rationale,
        }
        for r in recommendations
    ]
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return path


def write_accuracy_json(
    path: str,
    per_lob_metrics: Dict[str, AccuracyMetrics],
    overall_metrics: Optional[AccuracyMetrics] = None,
) -> str:
    """Write accuracy metrics to JSON."""
    logger.info("Writing accuracy summary to %s", path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    data: Dict[str, Any] = {
        "per_lob": {
            lob: {
                "wape_pct": round(float(m.wape), 2),
                "mape_pct": round(float(m.mape), 2),
                "bias": round(float(m.bias), 4),
            }
            for lob, m in per_lob_metrics.items()
        }
    }
    if overall_metrics:
        data["overall"] = {
            "wape_pct": round(float(overall_metrics.wape), 2),
            "mape_pct": round(float(overall_metrics.mape), 2),
            "bias": round(float(overall_metrics.bias), 4),
        }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return path
