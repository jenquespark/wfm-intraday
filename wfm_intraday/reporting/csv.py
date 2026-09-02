"""CSV report writers for AnalysisResult."""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

from wfm_intraday.domain.models import AnalysisResult

logger = logging.getLogger(__name__)


def _present(value: Any) -> Any:
    """Return a numeric value as-is, or a blank cell for missing (None) data.

    A real zero (``0.0``) is a legitimate value and MUST never render blank.
    ``None`` means "missing" — for actuals that is a future as-of interval
    with no observed data, and for schedule/requirement fields it means the
    value was not computed.
    """
    return value if value is not None else ""


def write_interval_csv(path: str, result: AnalysisResult) -> str:
    """Write interval-level analysis to CSV with all computed fields."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = []
    for iv in result.intervals:
        rows.append(
            {
                "date": iv.date,
                "interval": iv.interval_start,
                "lob": iv.lob,
                "channel": iv.channel,
                "forecast_volume": iv.forecast_volume,
                "forecast_aht_seconds": iv.forecast_aht_seconds,
                "actual_volume": _present(iv.actual_volume),
                "actual_aht_seconds": _present(iv.actual_aht_seconds),
                "reforecast_volume": _present(iv.reforecast_volume),
                "forecast_required_net_fte": _present(iv.forecast_required_net_fte),
                "forecast_required_gross_fte": _present(iv.forecast_required_gross_fte),
                "actual_required_net_fte": _present(iv.actual_required_net_fte),
                "actual_required_gross_fte": _present(iv.actual_required_gross_fte),
                "reforecast_required_net_fte": _present(iv.reforecast_required_net_fte),
                "reforecast_required_gross_fte": _present(iv.reforecast_required_gross_fte),
                "scheduled_fte": _present(iv.scheduled_fte),
                "staffing_gap_fte": _present(iv.staffing_gap_fte),
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
    logger.info("Interval CSV: %s (%d rows)", path, len(rows))
    return path


def write_redistribution_csv(path: str, result: AnalysisResult) -> str:
    """Write redistribution recommendations to CSV."""
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
        for r in result.redistribution
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    logger.info("Redistribution CSV: %s", path)
    return path
