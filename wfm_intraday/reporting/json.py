"""JSON report writer for AnalysisResult."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from wfm_intraday.domain.models import AnalysisResult

logger = logging.getLogger(__name__)


def _try_float(v: Any) -> Any:
    """Return float or None, preserving None and non-numeric values."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _interval_to_dict(iv) -> Dict[str, Any]:
    return {
        "date": iv.date,
        "interval": iv.interval_start,
        "lob": iv.lob,
        "channel": iv.channel,
        "forecast_volume": iv.forecast_volume,
        "forecast_aht_seconds": iv.forecast_aht_seconds,
        "actual_volume": iv.actual_volume,
        "actual_aht_seconds": iv.actual_aht_seconds,
        "reforecast_volume": iv.reforecast_volume,
        "forecast_required_net_fte": _try_float(iv.forecast_required_net_fte),
        "forecast_required_gross_fte": _try_float(iv.forecast_required_gross_fte),
        "actual_required_net_fte": _try_float(iv.actual_required_net_fte),
        "actual_required_gross_fte": _try_float(iv.actual_required_gross_fte),
        "reforecast_required_net_fte": _try_float(iv.reforecast_required_net_fte),
        "reforecast_required_gross_fte": _try_float(iv.reforecast_required_gross_fte),
        "scheduled_fte": _try_float(iv.scheduled_fte),
        "staffing_gap_fte": _try_float(iv.staffing_gap_fte),
    }


def _gap_to_dict(g) -> Dict[str, Any]:
    return {
        "date": g.date,
        "interval": g.interval_start,
        "lob": g.lob,
        "channel": g.channel,
        "forecast_required_net_fte": g.forecast_required_net_fte,
        "forecast_required_gross_fte": g.forecast_required_gross_fte,
        "actual_required_net_fte": g.actual_required_net_fte,
        "actual_required_gross_fte": g.actual_required_gross_fte,
        "reforecast_required_net_fte": g.reforecast_required_net_fte,
        "reforecast_required_gross_fte": g.reforecast_required_gross_fte,
        "scheduled_fte": g.scheduled_fte,
        "gap_fte": g.gap_fte,
        "status": g.status,
    }


def _reforecast_to_dict(rr) -> Dict[str, Any]:
    return {
        "date": rr.date,
        "lob": rr.lob,
        "channel": rr.channel,
        "checkpoint_interval": rr.checkpoint_interval,
        "deviation_pct": round(rr.deviation_pct, 4),
        "scale_factor": round(rr.scale_factor, 4),
        "blend_factor": rr.blend_factor,
        "original_total": round(sum(rr.original_forecast), 1),
        "adjusted_total": round(sum(rr.adjusted_forecast), 1),
    }


def _redist_to_dict(r) -> Dict[str, Any]:
    return {
        "date": r.date,
        "lob": r.lob,
        "channel": r.channel,
        "from_interval": r.from_interval_start,
        "to_interval": r.to_interval_start,
        "transfer_fte": r.recommended_transfer_fte,
        "transfer_hours": r.recommended_transfer_hours,
        "donor_remaining_surplus_fte": r.donor_remaining_surplus_fte,
        "rationale": r.rationale,
    }


def write_analysis_json(path: str, result: AnalysisResult) -> str:
    """Write AnalysisResult to a stable JSON structure.

    Interval records are fully serialized — no hardcoded empty list.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    data: Dict[str, Any] = {
        "schema_version": "1.0",
        "metadata": result.metadata,
        "validation": None,
        "forecast_accuracy": result.forecast_accuracy,
        "intervals": [_interval_to_dict(iv) for iv in result.intervals],
        "staffing_gaps": [_gap_to_dict(g) for g in result.staffing_gaps],
        "reforecast": [_reforecast_to_dict(rr) for rr in result.reforecast_results],
        "redistribution": [_redist_to_dict(r) for r in result.redistribution],
        "warnings": result.warnings,
    }

    if result.validation:
        data["validation"] = {
            "forecast_rows": result.validation.forecast_rows,
            "actual_rows": result.validation.actual_rows,
            "scheduled_rows": result.validation.scheduled_rows,
            "matched_keys": result.validation.matched_keys,
            "forecast_only": result.validation.forecast_only[:100],
            "actual_only": result.validation.actual_only[:100],
            "has_mismatch": result.validation.has_mismatch,
        }

    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    logger.info("JSON: %s (%d intervals)", path, len(result.intervals))
    return path