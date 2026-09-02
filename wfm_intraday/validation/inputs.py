"""Input validation and reconciliation."""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd

from wfm_intraday.domain.models import (
    ACTUALS_COLUMNS,
    BASE_KEY_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
    ReconciliationReport,
    validate_columns,
)

logger = logging.getLogger(__name__)

# The canonical join/identity keys shared by every input file.
KEY_COLUMNS: list[str] = BASE_KEY_COLUMNS


def validate_input_files(
    forecast_path: str,
    actuals_path: str,
    staffing_path: str | None = None,
    column_mapping: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None, list[str]]:
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
        ValueError: If required columns are missing, negative values are found,
            duplicate keys are present, or other structural issues exist.
    """
    warnings: list[str] = []
    mapping = column_mapping or {}

    forecast_df = _load_and_validate(forecast_path, FORECAST_COLUMNS, "forecast", mapping)
    actuals_df = _load_and_validate(actuals_path, ACTUALS_COLUMNS, "actuals", mapping)
    staffing_df = None
    if staffing_path:
        staffing_df = _load_and_validate(staffing_path, SCHEDULE_COLUMNS, "staffing", mapping)

    return forecast_df, actuals_df, staffing_df, warnings


def _load_and_validate(
    path: str,
    expected_cols: list[str],
    label: str,
    column_mapping: dict[str, str],
) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} file not found: {path}")

    df = pd.read_csv(path)

    # Apply column mapping if provided
    if column_mapping:
        reversed_map: dict[str, str] = {}
        for canonical, source in column_mapping.items():
            if source in reversed_map:
                raise ValueError(f"{label}: duplicate source column '{source}' in column mapping")
            reversed_map[source] = canonical
        df = df.rename(columns=reversed_map)

    # Validate required canonical columns exist
    try:
        validate_columns(expected_cols, list(df.columns))
    except ValueError as e:
        raise ValueError(f"{label}: {e}")

    # Duplicate canonical keys are a HARD error (silent data loss downstream).
    key_cols = [c for c in KEY_COLUMNS if c in df.columns]
    if key_cols:
        dup_mask = df.duplicated(subset=key_cols, keep=False)
        if dup_mask.any():
            dups = df.loc[dup_mask, key_cols].drop_duplicates()
            examples = ", ".join(
                "(" + ", ".join(str(v) for v in row) + ")"
                for row in dups.head(5).itertuples(index=False, name=None)
            )
            raise ValueError(
                f"{label}: {int(dup_mask.sum())} duplicate key rows across "
                f"{len(dups)} unique canonical key(s). "
                f"Representative keys: {examples}"
            )

    # Negative values are HARD errors (silent incorrectness).
    numeric_cols = [c for c in df.columns if c not in KEY_COLUMNS]
    for col in numeric_cols:
        if df[col].dtype in ("float64", "int64"):
            neg = (df[col] < 0).sum()
            if neg > 0:
                raise ValueError(
                    f"{label}: column '{col}' has {neg} negative values. "
                    f"Negative volume, AHT, or FTE is invalid operational data."
                )

    return df


def _key_set(df: pd.DataFrame | None) -> set:
    if df is None or df.empty:
        return set()
    cols = [c for c in KEY_COLUMNS if c in df.columns]
    if not cols:
        return set()
    return set(zip(*[df[c].astype(str) for c in cols]))


def reconcile_keys(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    staffing_df: pd.DataFrame | None = None,
) -> ReconciliationReport:
    """Compare key sets across input files and build a reconciliation report.

    This function only *describes* the alignment; it does not raise.  Callers
    that require strict alignment (the public ``analyze`` pipeline and the
    CLI) must inspect ``has_mismatch`` and raise/exit themselves.  See
    ``require_no_mismatch``.
    """
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


def require_no_mismatch(report: ReconciliationReport, mode: str = "retrospective") -> None:
    """Raise ``ValueError`` if the reconciliation report has a hard mismatch.

    * In ``retrospective`` mode, both forecast-only and actual-only keys are
      hard errors (full alignment required).
    * In ``as-of`` mode, forecast-only keys are ALLOWED — they represent future
      intervals whose actuals are not yet observed (the normal intra-day case).
      Actual-only keys remain a hard error (an actual with no forecast is
      always invalid).
    """
    parts: list[str] = []
    if report.actual_only:
        parts.append(f"{len(report.actual_only)} actual-only key(s)")
    if report.schedule_only:
        parts.append(f"{len(report.schedule_only)} schedule-only key(s)")
    if mode != "as-of" and report.forecast_only:
        parts.append(f"{len(report.forecast_only)} forecast-only key(s)")

    if parts:
        raise ValueError("Key mismatch between input files: " + ", ".join(parts) + ".")
