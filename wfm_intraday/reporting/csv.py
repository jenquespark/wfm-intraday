"""CSV report writers for AnalysisResult."""

from __future__ import annotations

import logging
import os

import pandas as pd

from wfm_intraday.domain.models import AnalysisResult

logger = logging.getLogger(__name__)


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
                "actual_volume": iv.actual_volume or "",
                "actual_aht_seconds": iv.actual_aht_seconds or "",
                "reforecast_volume": iv.reforecast_volume or "",
                "forecast_required_net_fte": iv.forecast_required_net_fte or "",
                "forecast_required_gross_fte": iv.forecast_required_gross_fte or "",
                "actual_required_net_fte": iv.actual_required_net_fte or "",
                "actual_required_gross_fte": iv.actual_required_gross_fte or "",
                "reforecast_required_net_fte": iv.reforecast_required_net_fte or "",
                "reforecast_required_gross_fte": iv.reforecast_required_gross_fte or "",
                "scheduled_fte": iv.scheduled_fte or "",
                "staffing_gap_fte": iv.staffing_gap_fte or "",
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
