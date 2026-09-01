"""Input validation and reconciliation."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import pandas as pd

from reforecast.domain.models import (
    ACTUALS_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
    ReconciliationReport,
    validate_columns,
)

logger = logging.getLogger(__name__)


def validate_input_files(
    forecast_path: str,
    actuals_path: str,
    staffing_path: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Optional[pd.DataFrame], List[str]]:
    """Load and validate input CSV files.

    Returns:
        (forecast_df, actuals_df, staffing_df_or_None, warnings)
    """
    warnings: List[str] = []

    forecast_df = _load_and_validate(forecast_path, FORECAST_COLUMNS, "forecast", warnings)
    actuals_df = _load_and_validate(actuals_path, ACTUALS_COLUMNS, "actuals", warnings)
    staffing_df = None
    if staffing_path:
        staffing_df = _load_and_validate(staffing_path, SCHEDULE_COLUMNS, "staffing", warnings)

    return forecast_df, actuals_df, staffing_df, warnings


def _load_and_validate(path: str, expected_cols: List[str], label: str, warnings: List[str]) -> pd.DataFrame:
    import os
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} file not found: {path}")

    df = pd.read_csv(path)
    try:
        validate_columns(expected_cols, list(df.columns))
    except ValueError as e:
        raise ValueError(f"{label}: {e}")

    # Check for duplicates
    key_cols = [c for c in ["date", "lob", "interval_start", "channel"] if c in df.columns]
    if key_cols:
        dups = df.duplicated(subset=key_cols).sum()
        if dups:
            warnings.append(f"{label}: {dups} duplicate key rows found")

    # Check negative values
    for col in df.columns:
        if df[col].dtype in ("float64", "int64"):
            neg = (df[col] < 0).sum()
            if neg:
                warnings.append(f"{label}: column '{col}' has {neg} negative values")

    return df


def reconcile_keys(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    staffing_df: Optional[pd.DataFrame] = None,
) -> ReconciliationReport:
    """Compare key sets across input files."""
    def _key_set(df):
        cols = [c for c in ["date", "lob", "interval_start", "channel"] if c in df.columns]
        return set(zip(*[df[c] for c in cols]))

    fc_keys = _key_set(forecast_df)
    ac_keys = _key_set(actuals_df)
    sd_keys = _key_set(staffing_df) if staffing_df is not None else set()

    all_keys = fc_keys | ac_keys | sd_keys
    matched = fc_keys & ac_keys

    return ReconciliationReport(
        forecast_rows=len(forecast_df),
        actual_rows=len(actuals_df),
        scheduled_rows=len(staffing_df) if staffing_df is not None else 0,
        matched_keys=len(matched),
        forecast_only=sorted(str(k) for k in (fc_keys - ac_keys)),
        actual_only=sorted(str(k) for k in (ac_keys - fc_keys)),
        schedule_only=sorted(str(k) for k in (sd_keys - fc_keys - ac_keys)),
    )