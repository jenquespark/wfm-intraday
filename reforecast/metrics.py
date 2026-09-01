"""Forecast accuracy metrics for WFM analysis.

All metrics are computed from arrays of actual and forecast volumes.
Division-by-zero is handled explicitly: intervals with zero actual volume
are excluded from MAPE and the overall WAPE denominator is guarded.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from reforecast.models import AccuracyMetrics

logger = logging.getLogger(__name__)


def calculate_wape(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Weighted Absolute Percentage Error.

    WAPE = sum(|actual - forecast|) / sum(actual) * 100

    When total actual volume is zero, returns 0.0.

    Args:
        actuals:   Array of actual volumes.
        forecasts: Array of forecast volumes.

    Returns:
        WAPE as a percentage (e.g. 15.2 for 15.2%).
    """
    if len(actuals) == 0:
        raise ValueError("Cannot calculate WAPE: empty arrays")
    if len(actuals) != len(forecasts):
        raise ValueError(
            f"Length mismatch: actuals={len(actuals)} forecasts={len(forecasts)}"
        )

    total_actual = float(np.sum(actuals))
    if total_actual <= 0:
        return 0.0

    abs_error = float(np.sum(np.abs(np.asarray(actuals, dtype=float) - np.asarray(forecasts, dtype=float))))
    return (abs_error / total_actual) * 100.0


def calculate_mape(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Mean Absolute Percentage Error.

    MAPE = mean(|actual - forecast| / actual) * 100

    Intervals with zero actual volume are excluded from the mean.
    If no interval has valid actual volume, returns 0.0.

    Args:
        actuals:   Array of actual volumes.
        forecasts: Array of forecast volumes.

    Returns:
        MAPE as a percentage.
    """
    if len(actuals) == 0:
        raise ValueError("Cannot calculate MAPE: empty arrays")
    if len(actuals) != len(forecasts):
        raise ValueError(f"Length mismatch: actuals={len(actuals)} forecasts={len(forecasts)}")

    a = np.asarray(actuals, dtype=float)
    f = np.asarray(forecasts, dtype=float)

    mask = a > 0
    if not np.any(mask):
        return 0.0

    pct_errors = np.abs((a[mask] - f[mask]) / a[mask]) * 100.0
    return float(np.mean(pct_errors))


def calculate_bias(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Forecast bias.

    bias = sum(actual - forecast) / sum(actual)

    * Positive -> underforecast (actual > forecast).
    * Negative -> overforecast  (actual < forecast).

    When total actual volume is zero, returns 0.0.
    """
    if len(actuals) == 0:
        raise ValueError("Cannot calculate bias: empty arrays")
    if len(actuals) != len(forecasts):
        raise ValueError(f"Length mismatch: actuals={len(actuals)} forecasts={len(forecasts)}")

    a = np.asarray(actuals, dtype=float)
    f = np.asarray(forecasts, dtype=float)

    total_actual = float(np.sum(a))
    if total_actual <= 0:
        return 0.0

    return float(np.sum(a - f) / total_actual)


def calculate_all(
    actuals: np.ndarray,
    forecasts: np.ndarray,
) -> AccuracyMetrics:
    """Calculate WAPE, MAPE, and bias in one call."""
    return AccuracyMetrics(
        wape=calculate_wape(actuals, forecasts),
        mape=calculate_mape(actuals, forecasts),
        bias=calculate_bias(actuals, forecasts),
    )


def calculate_per_lob(
    df: pd.DataFrame,
    actual_col: str = "actual_volume",
    forecast_col: str = "forecast_volume",
) -> Dict[str, AccuracyMetrics]:
    """Calculate accuracy metrics per LOB.

    Args:
        df: DataFrame with ``lob``, ``actual_volume``, ``forecast_volume`` columns.
        actual_col: Name of the actual-volume column.
        forecast_col: Name of the forecast-volume column.

    Returns:
        Dict mapping LOB names to ``AccuracyMetrics``.
    """
    if df.empty:
        return {}

    results: Dict[str, AccuracyMetrics] = {}
    for lob_name, group in df.groupby("lob"):
        actuals = group[actual_col].to_numpy(dtype=float)
        forecasts = group[forecast_col].to_numpy(dtype=float)
        results[str(lob_name)] = calculate_all(actuals, forecasts)

    return results