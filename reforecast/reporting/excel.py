"""Excel report writer for AnalysisResult."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import pandas as pd

from reforecast.domain.models import AnalysisResult

logger = logging.getLogger(__name__)


def write_excel_report(path: str, result: AnalysisResult) -> str:
    """Write AnalysisResult to a multi-sheet Excel workbook."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Summary
        _write_summary(writer, result)
        # Interval Analysis
        _write_intervals(writer, result)
        # Forecast Accuracy
        _write_accuracy(writer, result)
        # Staffing Gaps
        _write_gaps(writer, result)
        # Redistribution
        _write_redistribution(writer, result)
        # Validation
        _write_validation(writer, result)

    logger.info("Excel report: %s", path)
    return path


def _write_summary(writer: Any, result: AnalysisResult) -> None:
    fa = result.forecast_accuracy
    row: Dict[str, Any] = {}
    if "overall" in fa:
        o = fa["overall"]
        row["WAPE (%)"] = o["wape"]
        row["MAPE (%)"] = o["mape"]
        row["Bias"] = o["bias"]
    if result.metadata:
        row["Analysis Date"] = result.metadata.get("date", "")
        row["Checkpoint"] = result.metadata.get("checkpoint", "")
        row["Mode"] = result.metadata.get("mode", "retrospective")
    if result.staffing_gaps:
        counts = {}
        for g in result.staffing_gaps:
            counts[g.status] = counts.get(g.status, 0) + 1
        row["Understaffed Intervals"] = counts.get("understaffed", 0)
        row["Overstaffed Intervals"] = counts.get("overstaffed", 0)
    if result.redistribution:
        row["Redistribution Moves"] = len(result.redistribution)
    pd.DataFrame([row]).to_excel(writer, sheet_name="Summary", index=False)


def _write_intervals(writer: Any, result: AnalysisResult) -> None:
    if not result.intervals:
        return
    rows = []
    for iv in result.intervals:
        rows.append({
            "Date": iv.date,
            "Interval": iv.interval_start,
            "LOB": iv.lob,
            "Channel": iv.channel,
            "Forecast Volume": iv.forecast_volume,
            "Forecast AHT (s)": iv.forecast_aht_seconds,
            "Actual Volume": iv.actual_volume or "",
            "Actual AHT (s)": iv.actual_aht_seconds or "",
            "Reforecast Volume": iv.reforecast_volume or "",
            "Scheduled FTE": iv.scheduled_fte or "",
        })
    pd.DataFrame(rows).to_excel(writer, sheet_name="Interval_Analysis", index=False)


def _write_accuracy(writer: Any, result: AnalysisResult) -> None:
    fa = result.forecast_accuracy
    rows = []
    for lob, m in fa.get("per_lob", {}).items():
        rows.append({"LOB": lob, "WAPE (%)": m["wape"], "MAPE (%)": m["mape"], "Bias": m["bias"]})
    if "overall" in fa:
        o = fa["overall"]
        rows.append({"LOB": "OVERALL", "WAPE (%)": o["wape"], "MAPE (%)": o["mape"], "Bias": o["bias"]})
    if rows:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Forecast_Accuracy", index=False)


def _write_gaps(writer: Any, result: AnalysisResult) -> None:
    if not result.staffing_gaps:
        return
    rows = []
    for g in result.staffing_gaps[:2000]:
        rows.append({
            "Date": g.date,
            "Interval": g.interval_start,
            "LOB": g.lob,
            "Channel": g.channel,
            "Forecast Required Net FTE": g.forecast_required_net_fte or "",
            "Forecast Required Gross FTE": g.forecast_required_gross_fte or "",
            "Actual Required Net FTE": g.actual_required_net_fte or "",
            "Actual Required Gross FTE": g.actual_required_gross_fte or "",
            "Scheduled FTE": g.scheduled_fte or "N/A",
            "Gap FTE": g.gap_fte or "N/A",
            "Status": g.status,
        })
    pd.DataFrame(rows).to_excel(writer, sheet_name="Staffing_Gaps", index=False)


def _write_redistribution(writer: Any, result: AnalysisResult) -> None:
    if not result.redistribution:
        return
    rows = [
        {
            "Date": r.date,
            "LOB": r.lob,
            "Channel": r.channel,
            "From Interval": r.from_interval_start,
            "To Interval": r.to_interval_start,
            "Transfer FTE": r.recommended_transfer_fte,
            "Transfer Hours": r.recommended_transfer_hours,
            "Donor Remaining": r.donor_remaining_surplus_fte,
            "Rationale": r.rationale,
        }
        for r in result.redistribution
    ]
    pd.DataFrame(rows).to_excel(writer, sheet_name="Redistribution", index=False)


def _write_validation(writer: Any, result: AnalysisResult) -> None:
    rows = []
    v = result.validation
    if v:
        rows.append({"Check": "Forecast rows", "Value": v.forecast_rows})
        rows.append({"Check": "Actual rows", "Value": v.actual_rows})
        rows.append({"Check": "Scheduled rows", "Value": v.scheduled_rows})
        rows.append({"Check": "Matched keys", "Value": v.matched_keys})
        if v.forecast_only:
            rows.append({"Check": "Forecast-only keys", "Value": len(v.forecast_only)})
        if v.actual_only:
            rows.append({"Check": "Actual-only keys", "Value": len(v.actual_only)})
    if result.warnings:
        for w in result.warnings:
            rows.append({"Check": "Warning", "Value": w})
    pd.DataFrame(rows).to_excel(writer, sheet_name="Validation", index=False)