"""Reporter zero-preservation tests.

A real numeric zero (``0.0``) — zero actual volume, zero scheduled FTE, zero
staffing gap, zero FTE requirement — is legitimate data and MUST appear as
``0.0`` in every reporter output.  Only ``None`` (missing data) may render as
a blank cell (CSV/Excel intervals/Web) or ``"N/A"`` (Excel staffing gaps).

``value or ""``-style fallbacks are lossy because ``0.0 or ""`` evaluates to
``""``; these tests would catch that regression.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from wfm_intraday.domain.models import (
    AnalysisResult,
    IntervalRecord,
    StaffingGap,
)


def _zero_interval() -> IntervalRecord:
    """An interval where every computed value IS a real zero."""
    return IntervalRecord(
        date="2026-09-01",
        interval_start="08:00",
        lob="inbound",
        channel="voice",
        forecast_volume=100.0,
        forecast_aht_seconds=180.0,
        actual_volume=0.0,
        actual_aht_seconds=180.0,
        reforecast_volume=0.0,
        forecast_required_net_fte=10.0,
        forecast_required_gross_fte=15.0,
        actual_required_net_fte=0.0,
        actual_required_gross_fte=0.0,
        reforecast_required_net_fte=None,
        reforecast_required_gross_fte=None,
        scheduled_fte=0.0,
        staffing_gap_fte=0.0,
    )


def _missing_interval() -> IntervalRecord:
    """A future as-of interval with genuinely missing (None) data."""
    return IntervalRecord(
        date="2026-09-01",
        interval_start="09:00",
        lob="inbound",
        channel="voice",
        forecast_volume=100.0,
        forecast_aht_seconds=180.0,
        actual_volume=None,
        actual_aht_seconds=None,
        reforecast_volume=None,
        forecast_required_net_fte=10.0,
        forecast_required_gross_fte=15.0,
        actual_required_net_fte=None,
        actual_required_gross_fte=None,
        reforecast_required_net_fte=None,
        reforecast_required_gross_fte=None,
        scheduled_fte=None,
        staffing_gap_fte=None,
    )


def _zero_gap() -> StaffingGap:
    """A staffing gap where requirement, schedule, and gap are all real zeros."""
    return StaffingGap(
        date="2026-09-01",
        interval_start="08:00",
        lob="inbound",
        channel="voice",
        forecast_required_net_fte=10.0,
        forecast_required_gross_fte=15.0,
        actual_required_net_fte=0.0,
        actual_required_gross_fte=0.0,
        reforecast_required_net_fte=None,
        reforecast_required_gross_fte=None,
        scheduled_fte=0.0,
        gap_fte=0.0,
        status="balanced",
    )


def _missing_gap() -> StaffingGap:
    """A gap with no schedule input: schedule and gap are missing (None)."""
    return StaffingGap(
        date="2026-09-01",
        interval_start="09:00",
        lob="inbound",
        channel="voice",
        forecast_required_net_fte=10.0,
        forecast_required_gross_fte=15.0,
        actual_required_net_fte=None,
        actual_required_gross_fte=None,
        reforecast_required_net_fte=None,
        reforecast_required_gross_fte=None,
        scheduled_fte=None,
        gap_fte=None,
        status="no_schedule",
    )


def _result() -> AnalysisResult:
    return AnalysisResult(
        metadata={"version": "0.2.1", "mode": "retrospective"},
        forecast_accuracy={"overall": {"wape": 5.0, "mape": 6.0, "bias": 0.05}, "per_lob": {}},
        intervals=[_zero_interval(), _missing_interval()],
        staffing_gaps=[_zero_gap(), _missing_gap()],
        reforecast_results=[],
        redistribution=[],
        warnings=[],
    )


class TestCsvZeroPreservation:
    def test_zero_values_remain_numeric_zero(self, tmp_path):
        from wfm_intraday.reporting.csv import write_interval_csv

        path = write_interval_csv(str(tmp_path / "interval.csv"), _result())
        df = pd.read_csv(path)
        # Zero interval — every zero must survive as numeric 0.0.
        row = df[df["interval"] == "08:00"].iloc[0]
        assert row["actual_volume"] == 0.0
        assert row["actual_required_gross_fte"] == 0.0
        assert row["scheduled_fte"] == 0.0
        assert row["staffing_gap_fte"] == 0.0
        assert row["reforecast_volume"] == 0.0

    def test_missing_values_render_blank(self, tmp_path):
        from wfm_intraday.reporting.csv import write_interval_csv

        path = write_interval_csv(str(tmp_path / "interval.csv"), _result())
        df = pd.read_csv(path)
        # Missing interval — actual/schedule/gap cells must be blank (NaN read-back).
        row = df[df["interval"] == "09:00"].iloc[0]
        assert pd.isna(row["actual_volume"])
        assert pd.isna(row["scheduled_fte"])
        assert pd.isna(row["staffing_gap_fte"])


class TestExcelZeroPreservation:
    def test_interval_sheet_keeps_numeric_zeros(self, tmp_path):
        from wfm_intraday.reporting.excel import write_excel_report

        path = write_excel_report(str(tmp_path / "intraday_report.xlsx"), _result())
        df = pd.read_excel(path, sheet_name="Interval_Analysis")
        row = df[df["Interval"] == "08:00"].iloc[0]
        assert row["Actual Volume"] == 0.0
        assert row["Actual Req Gross FTE"] == 0.0
        assert row["Scheduled FTE"] == 0.0
        assert row["Staffing Gap FTE"] == 0.0

    def test_gaps_sheet_distinguishes_zero_from_na(self, tmp_path):
        from wfm_intraday.reporting.excel import write_excel_report

        path = write_excel_report(str(tmp_path / "intraday_report.xlsx"), _result())
        # keep_default_na=False so the "N/A" missing-data sentinel survives the
        # read-back: pandas' default NA conversion would silently fold the
        # literal "N/A" string back into NaN, defeating the assertion.
        df = pd.read_excel(path, sheet_name="Staffing_Gaps", keep_default_na=False)
        by_start = {r.Interval: r for _, r in df.iterrows()}

        zero = by_start["08:00"]
        assert zero["Scheduled FTE"] == 0.0
        assert zero["Gap FTE"] == 0.0

        missing = by_start["09:00"]
        # Missing schedule is still the "N/A" sentinel — not a lossy 0.0.
        assert missing["Scheduled FTE"] == "N/A"
        assert missing["Gap FTE"] == "N/A"


class TestJsonZeroPreservation:
    def test_zero_values_serialize_as_zero(self, tmp_path):
        from wfm_intraday.reporting.json import write_analysis_json

        path = write_analysis_json(str(tmp_path / "analysis.json"), _result())
        with open(path) as f:
            data = json.load(f)

        zero = next(iv for iv in data["intervals"] if iv["interval"] == "08:00")
        assert zero["actual_volume"] == 0.0
        assert zero["scheduled_fte"] == 0.0
        assert zero["actual_required_gross_fte"] == 0.0
        assert zero["staffing_gap_fte"] == 0.0

        missing = next(iv for iv in data["intervals"] if iv["interval"] == "09:00")
        assert missing["actual_volume"] is None
        assert missing["scheduled_fte"] is None


class TestWebHelperZeroPreservation:
    def test_interval_table_rows_preserve_zeros(self):
        from wfm_intraday.web.app import _interval_table_rows

        rows = _interval_table_rows(_result().intervals)
        by_start = {r["Interval"]: r for r in rows}

        zero = by_start["08:00"]
        assert zero["Actual Vol"] == 0.0
        assert zero["Sched FTE"] == 0.0

        missing = by_start["09:00"]
        assert missing["Actual Vol"] == ""
        assert missing["Sched FTE"] == ""
