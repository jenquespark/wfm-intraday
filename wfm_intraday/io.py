"""CSV input loaders for WFM Intraday.

The *writers* live in :mod:`wfm_intraday.reporting` and consume a single
canonical ``AnalysisResult``.  This module retains only the low-level
loaders.  The production merge path lives in :mod:`wfm_intraday` as a
LEFT join (forecast spine preserved).  The legacy ``io.merge_forecast_actuals``
inner-join / warning-only path has been removed — use
:func:`wfm_intraday.analyze` for production analysis.
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
