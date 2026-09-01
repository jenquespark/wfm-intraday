"""Input validation and reconciliation."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

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
    column_mapping: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Optional[pd.DataFrame], List[str]]:
    """Load and validate input CSV files.

    Args:
        forecast_path: Path to forecast CSV.
        actuals_path: Path to actuals CSV.
        staffing_path: Optional path to schedule CSV.
        column_mapping: Optional dict mapping canonical → source column names
            (e.g. ``{'date': 'Contact Date', 'lob': 'Queue'}``).

    Returns:
        (forecast_df, actuals_df, staffing_df_or_None, warnings)

    Raises:
        FileNotFoundError: If a required file does not exist.
        ValueError: If required columns are missing, negative values found,
            or other structural issues.
    """
    warnings: List[str] = []
    mapping = column_mapping or {}

    forecast_df = _load_and_validate(
        forecast_path, FORECAST_COLUMNS, "forecast", warnings, mapping
    )
    actuals_df = _load_and_validate(
        actuals_path, ACTUALS_COLUMNS, "actuals", warnings, mapping
    )
    staffing_df = None
    if staffing_path:
        staffing_df = _load_and_validate(
            staffing_path, SCHEDULE_COLUMNS, "staffing", warnings, mapping
        )

    return forecast_df, actuals_df, staffing_df, warnings


def _load_and_validate(
    path: str,
    expected_cols: List[str],
    label: str,
    warnings: List[str],
    column_mapping: Dict[str, str],
) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} file not found: {path}")

    df = pd.read_csv(path)

    # Apply column mapping if provided
    if column_mapping:
        reversed_map: Dict[str, str] = {}
        for canonical, source in column_mapping.items():
            if source in reversed_map:
                raise ValueError(
                    f"{label}: duplicate source column '{source}' in column mapping"
                )
            reversed_map[source] = canonical
        df = df.rename(columns=reversed_map)

    # Validate required canonical columns exist
    try:
        validate_columns(expected_cols, list(df.columns))
    except ValueError as e:
        raise ValueError(f"{label}: {e}")

    # Check for duplicates — WARNING (may be handled downstream)
    key_cols = [c for c in ["date", "lob", "interval_start", "channel"] if c in df.columns]
    if key_cols:
        dups = df.duplicated(subset=key_cols).sum()
        if dups:
            warnings.append(f"{label}: {dups} duplicate key rows found")

    # Negative values are HARD errors (silent incorrectness)
    numeric_cols = [c for c in df.columns if c not in ("date", "lob", "interval_start", "channel")]
    for col in numeric_cols:
        if df[col].dtype in ("float64", "int64"):
            neg = (df[col] < 0).sum()
            if neg > 0:
                raise ValueError(
                    f"{label}: column '{col}' has {neg} negative values. "
                    f"Negative volume, AHT, or FTE is invalid operational data."
                )

    return df


def reconcile_keys(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    staffing_df: Optional[pd.DataFrame] = None,
) -> ReconciliationReport:
    """Compare key sets across input files."""
    def _key_set(df: pd.DataFrame) -> set:
        cols = [c for c in ["date", "lob", "interval_start", "channel"] if c in df.columns]
        if not cols:
            return set()
        return set(zip(*[df[c].astype(str) for c in cols]))

    fc_keys = _key_set(forecast_df)
    ac_keys = _key_set(actuals_df)
    sd_keys = _key_set(staffing_df) if staffing_df is not None else set()

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