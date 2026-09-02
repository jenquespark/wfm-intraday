"""CSV input loaders and forecast/actual merge for WFM Intraday.

The *writers* live in :mod:`wfm_intraday.reporting` and consume a single
canonical ``AnalysisResult``.  This module retains only the legacy low-level
loaders and the merge helper.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from wfm_intraday.models import (
    ACTUALS_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
    ReconciliationReport,
    validate_columns,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_csv(path: str, expected_columns: list[str]) -> pd.DataFrame:
    """Load a CSV file and validate its column schema.

    Args:
        path: Path to CSV file.
        expected_columns: list of required column names.

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
) -> tuple[pd.DataFrame, ReconciliationReport]:
    """Merge forecast and actuals dataframes.

    Uses an inner join on (date, lob, interval_start, channel).  Key
    mismatches are reported in the ``ReconciliationReport`` rather than
    silently dropped.

    Args:
        forecast_df: Forecast dataframe.
        actuals_df:  Actuals dataframe.

    Returns:
        tuple of (merged DataFrame, ReconciliationReport).
    """
    # Build reconciliation
    fc_keys = set(
        zip(
            forecast_df["date"],
            forecast_df["lob"],
            forecast_df["interval_start"],
            forecast_df.get("channel", ""),
        )
    )
    ac_keys = set(
        zip(
            actuals_df["date"],
            actuals_df["lob"],
            actuals_df["interval_start"],
            actuals_df.get("channel", ""),
        )
    )

    matched = fc_keys & ac_keys
    forecast_only = fc_keys - ac_keys
    actual_only = ac_keys - fc_keys

    logger.info("Merging forecast and actuals data")
    logger.info(
        "Key reconciliation: %d matched, %d forecast-only, %d actual-only",
        len(matched),
        len(forecast_only),
        len(actual_only),
    )

    if forecast_only:
        logger.warning(
            "Forecast-only keys (not in actuals): %d — these will be dropped", len(forecast_only)
        )
    if actual_only:
        logger.warning(
            "Actual-only keys (not in forecast): %d — these will be dropped", len(actual_only)
        )

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
