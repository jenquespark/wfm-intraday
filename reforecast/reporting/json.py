"""JSON report writer for AnalysisResult."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from reforecast.domain.models import AnalysisResult

logger = logging.getLogger(__name__)


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
    """Write AnalysisResult to a stable JSON structure."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    data: Dict[str, Any] = {
        "metadata": result.metadata,
        "validation": None,
        "forecast_accuracy": result.forecast_accuracy,
        "intervals": [],
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
        json.dump(data, f, indent=2)

    logger.info("JSON: %s", path)
    return path