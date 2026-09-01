"""CSV/Excel input/output for WFM Reforecast Engine."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd

from reforecast.models import FORECAST_COLUMNS, ACTUALS_COLUMNS, AccuracyMetrics, validate_columns

logger = logging.getLogger(__name__)


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
    validate_columns(expected_columns, list(df.columns))
    return df


def load_forecast(path: str) -> pd.DataFrame:
    """Load a forecast CSV file.

    Expected columns: date, lob, interval_start, forecast_volume, forecast_aht
    """
    return load_csv(path, FORECAST_COLUMNS)


def load_actuals(path: str) -> pd.DataFrame:
    """Load an actuals CSV file.

    Expected columns: date, lob, interval_start, actual_volume, actual_aht
    """
    return load_csv(path, ACTUALS_COLUMNS)


def merge_forecast_actuals(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge forecast and actuals dataframes on date, lob, interval_start.

    Args:
        forecast_df: Forecast dataframe.
        actuals_df: Actuals dataframe.

    Returns:
        Merged dataframe with all columns.
    """
    logger.info("Merging forecast and actuals data")
    merged = forecast_df.merge(
        actuals_df,
        on=["date", "lob", "interval_start"],
        how="inner",
        suffixes=("", "_actual"),
    )

    if merged.empty:
        raise ValueError(
            "Forecast and actuals data have no overlapping "
            "(date, lob, interval_start) records"
        )

    # If actual_aht came through with _actual suffix, rename it
    if "actual_aht" not in merged.columns and "actual_aht_actual" in merged.columns:
        merged.rename(columns={"actual_aht_actual": "actual_aht"}, inplace=True)
    if "actual_volume" not in merged.columns and "actual_volume_actual" in merged.columns:
        merged.rename(columns={"actual_volume_actual": "actual_volume"}, inplace=True)

    return merged


def write_excel_report(
    path: str,
    dfs_dict: Dict[str, pd.DataFrame],
    per_lob_metrics: Dict[str, AccuracyMetrics],
    overall_metrics: Optional[AccuracyMetrics] = None,
) -> str:
    """Write a multi-sheet Excel report.

    One sheet per LOB containing interval-level forecast vs actual data,
    plus a summary sheet with accuracy metrics.

    Args:
        path: Output Excel file path.
        dfs_dict: Dict mapping LOB names to interval DataFrames.
        per_lob_metrics: Dict mapping LOB names to AccuracyMetrics.
        overall_metrics: Optional overall accuracy metrics.

    Returns:
        Path to the written file.
    """
    logger.info("Writing Excel report to %s", path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for lob_name, df in dfs_dict.items():
            sheet_name = str(lob_name)[:31]  # Excel sheet name max 31 chars
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Summary sheet
        summary_rows: List[Dict[str, Any]] = []
        for lob_name, metrics in per_lob_metrics.items():
            summary_rows.append(
                {
                    "LOB": lob_name,
                    "WAPE (%)": round(float(metrics.wape), 2),
                    "MAPE (%)": round(float(metrics.mape), 2),
                    "Bias": round(float(metrics.bias), 4),
                }
            )
        if overall_metrics:
            summary_rows.append(
                {
                    "LOB": "OVERALL",
                    "WAPE (%)": round(float(overall_metrics.wape), 2),
                    "MAPE (%)": round(float(overall_metrics.mape), 2),
                    "Bias": round(float(overall_metrics.bias), 4),
                }
            )
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

    return path


def write_redistribution_csv(path: str, recommendations: List[Dict[str, Any]]) -> str:
    """Write redistribution recommendations to CSV.

    Args:
        path: Output CSV file path.
        recommendations: List of dicts with keys: from_interval, to_interval,
                        from_lob, to_lob, flexible_hours, rationale.

    Returns:
        Path to the written file.
    """
    logger.info("Writing redistribution plan to %s", path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = pd.DataFrame(recommendations)
    df.to_csv(path, index=False)
    return path


def write_accuracy_json(
    path: str,
    per_lob_metrics: Dict[str, AccuracyMetrics],
    overall_metrics: Optional[AccuracyMetrics] = None,
) -> str:
    """Write accuracy metrics to JSON.

    Args:
        path: Output JSON file path.
        per_lob_metrics: Dict mapping LOB names to AccuracyMetrics.
        overall_metrics: Optional overall accuracy metrics.

    Returns:
        Path to the written file.
    """
    logger.info("Writing accuracy summary to %s", path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    data: Dict[str, Any] = {
        "per_lob": {
            lob: {
                "wape": round(float(m.wape), 2),
                "mape": round(float(m.mape), 2),
                "bias": round(float(m.bias), 4),
            }
            for lob, m in per_lob_metrics.items()
        }
    }
    if overall_metrics:
        data["overall"] = {
            "wape": round(float(overall_metrics.wape), 2),
            "mape": round(float(overall_metrics.mape), 2),
            "bias": round(float(overall_metrics.bias), 4),
        }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return path