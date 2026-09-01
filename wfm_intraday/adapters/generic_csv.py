"""Generic CSV adapter with column mapping support.

This is the default input adapter.  It reads CSV files and maps external
column names to the canonical schema via a user-supplied mapping dict.

The mapping is loaded from ``config.yaml`` under the ``column_mapping`` key.
If no mapping is provided, the adapter expects canonical column names
directly.

Example config::

    column_mapping:
      forecast:
        date: "Date"
        interval_start: "Interval"
        lob: "Skill"
        channel: "Channel"
        forecast_volume: "Calls Forecast"
        forecast_aht_seconds: "Forecast AHT"
      actuals:
        date: "Date"
        interval_start: "Interval"
        lob: "Skill"
        channel: "Channel"
        actual_volume: "Calls Actual"
        actual_aht_seconds: "Actual AHT"
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from wfm_intraday.adapters.base import InputAdapter, register_adapter
from wfm_intraday.domain.models import (
    ACTUALS_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
)

logger = logging.getLogger(__name__)

CANONICAL_FORECAST = set(FORECAST_COLUMNS)
CANONICAL_ACTUALS = set(ACTUALS_COLUMNS)
CANONICAL_STAFFING = set(SCHEDULE_COLUMNS)


@register_adapter
class GenericCSVAdapter(InputAdapter):
    """Reads CSV files and maps columns to the canonical schema."""

    name = "generic_csv"

    def __init__(self, column_mapping: Optional[Dict[str, Dict[str, str]]] = None):
        self._mapping = column_mapping or {}

    @classmethod
    def can_handle(cls, source_hint: str) -> bool:
        """Always returns True — this is the fallback adapter."""
        return True

    def _map_columns(self, df: pd.DataFrame, source_type: str, expected: set) -> pd.DataFrame:
        """Rename columns according to mapping, then validate canonical names."""
        mapping = self._mapping.get(source_type, {})
        if mapping:
            df = df.rename(columns=mapping)
            logger.debug("Applied column mapping for %s: %s", source_type, mapping)
        # Check which canonical columns are present
        missing = expected - set(df.columns)
        if missing:
            raise ValueError(
                f"Required columns missing for {source_type}: "
                f"{sorted(missing)}. "
                f"Available columns: {sorted(df.columns)}. "
                "Configure a column_mapping in config.yaml if your CSV uses "
                "different column names."
            )
        # Keep only canonical columns + extra keys
        keep = list(expected | {"date", "lob", "interval_start", "channel"})
        return df[[c for c in keep if c in df.columns]]

    def load_forecast(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        logger.info("Loaded forecast CSV: %s (%d rows, %d cols)", path, len(df), len(df.columns))
        df = self._map_columns(df, "forecast", CANONICAL_FORECAST)
        return df

    def load_actuals(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        logger.info("Loaded actuals CSV: %s (%d rows, %d cols)", path, len(df), len(df.columns))
        df = self._map_columns(df, "actuals", CANONICAL_ACTUALS)
        return df

    def load_staffing(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        logger.info("Loaded staffing CSV: %s (%d rows, %d cols)", path, len(df), len(df.columns))
        df = self._map_columns(df, "staffing", CANONICAL_STAFFING)
        return df