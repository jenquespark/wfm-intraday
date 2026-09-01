"""Forecast accuracy metrics for WFM analysis."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from reforecast.models import AccuracyMetrics

logger = logging.getLogger(__name__)


def calculate_wape(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Weighted Absolute Percentage Error.

    WAPE = sum(|actual - forecast|) / sum(actual) * 100

    Args:
        actuals: Array of actual volumes.
        forecasts: Array of forecast volumes.

    Returns:
        WAPE as a percentage (e.g. 15.2 for 15.2%).

    Raises:
        ValueError: If arrays are empty or lengths differ.
    """
    if len(actuals) == 0:
        raise ValueError("Cannot calculate WAPE: empty actuals array")
    if len(actuals) != len(forecasts):
        raise ValueError(
            f"Cannot calculate WAPE: length mismatch "
            f"actuals={len(actuals)} forecasts={len(forecasts)}"
        )

    total_actual = float(np.sum(actuals))
    if total_actual == 0:
        logger.warning("Total actual volume is 0 — returning WAPE=0")
        return 0.0

    abs_error = float(np.sum(np.abs(actuals - forecasts)))
    return (abs_error / total_actual) * 100


def calculate_mape(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Mean Absolute Percentage Error.

    MAPE = mean(|actual - forecast| / actual) * 100

    Args:
        actuals: Array of actual volumes.
        forecasts: Array of forecast volumes.

    Returns:
        MAPE as a percentage.

    Raises:
        ValueError: If arrays are empty or lengths differ.
    """
    if len(actuals) == 0:
        raise ValueError("Cannot calculate MAPE: empty actuals array")
    if len(actuals) != len(forecasts):
        raise ValueError(
            f"Cannot calculate MAPE: length mismatch "
            f"actuals={len(actuals)} forecasts={len(forecasts)}"
        )

    # Guard: avoid division by zero per-interval
    safe_actuals = np.where(actuals == 0, np.nan, actuals)
    with np.errstate(invalid="ignore"):
        pct_errors = np.abs((actuals - forecasts) / safe_actuals) * 100

    valid = ~np.isnan(pct_errors)
    if not np.any(valid):
        logger.warning("All intervals have zero actual volume — returning MAPE=0")
        return 0.0

    return float(np.mean(pct_errors[valid]))


def calculate_bias(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Forecast bias.

    bias = sum(actual - forecast) / sum(actual)
    Positive = underforecast (actual > forecast).
    Negative = overforecast (actual < forecast).

    Args:
        actuals: Array of actual volumes.
        forecasts: Array of forecast volumes.

    Returns:
        Bias as a decimal fraction (e.g. 0.12 for +12%).
    """
    if len(actuals) == 0:
        raise ValueError("Cannot calculate bias: empty actuals array")
    if len(actuals) != len(forecasts):
        raise ValueError(f"Length mismatch: actuals={len(actuals)} forecasts={len(forecasts)}")

    total_actual = float(np.sum(actuals))
    if total_actual == 0:
        logger.warning("Total actual volume is 0 — returning bias=0")
        return 0.0

    return float(np.sum(actuals - forecasts) / total_actual)


def calculate_all(
    actuals: np.ndarray,
    forecasts: np.ndarray,
) -> AccuracyMetrics:
    """Calculate all three accuracy metrics at once.

    Args:
        actuals: Array of actual volumes.
        forecasts: Array of forecast volumes.

    Returns:
        AccuracyMetrics with wape, mape, bias.
    """
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
        df: DataFrame with lob, actual_volume, forecast_volume columns.
        actual_col: Name of column with actual volumes.
        forecast_col: Name of column with forecast volumes.

    Returns:
        Dict mapping LOB names to AccuracyMetrics.
    """
    if df.empty:
        return {}

    results: Dict[str, AccuracyMetrics] = {}
    for lob_name, group in df.groupby("lob"):
        actuals = group[actual_col].to_numpy()
        forecasts = group[forecast_col].to_numpy()
        assert isinstance(lob_name, str)
        results[lob_name] = calculate_all(actuals, forecasts)

    return results