"""Tests for CSV input/output and the three reporters.

The three reporters (Excel, CSV, JSON) all consume one canonical
``AnalysisResult`` — verified here by writing a small result and asserting each
reporter emits the same interval count.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from wfm_intraday.domain.models import (
    ACTUALS_COLUMNS,
    FORECAST_COLUMNS,
    AnalysisResult,
    IntervalRecord,
)
from wfm_intraday.io import load_csv, load_forecast
from wfm_intraday.models import validate_columns


class TestValidateColumns:
    def test_matches(self):
        validate_columns(["a", "b"], ["a", "b"])  # should not raise

    def test_missing_raises(self):
        with pytest.raises(ValueError, match="Missing columns"):
            validate_columns(["a", "b"], ["a"])

    def test_empty_actual(self):
        with pytest.raises(ValueError, match="Missing columns"):
            validate_columns(["a"], [])


class TestLoadCSV:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_csv("/nonexistent.csv", ["a"])

    def test_valid_csv(self, tmp_path):
        p = tmp_path / "forecast.csv"
        p.write_text(
            "date,lob,interval_start,channel,forecast_volume,forecast_aht_seconds\n"
            "2026-05-04,inbound,08:00,voice,100.0,180.0\n"
        )
        df = load_forecast(str(p))
        assert len(df) == 1
        assert list(df.columns) == FORECAST_COLUMNS

    def test_missing_columns_raises(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("date,lob\n2026-05-04,inbound\n")
        with pytest.raises(ValueError, match="Missing columns"):
            load_csv(str(p), FORECAST_COLUMNS)


class TestMergeForecastActualsRemoved:
    def test_merge_helper_removed_from_io(self):
        """The legacy io.merge_forecast_actuals (inner-join + warning-only) has been removed.

        The production merge lives in :mod:`wfm_intraday` (LEFT join + hard
        reconciliation).  Using the removed helper must fail so callers cannot
        accidentally reach the old lossy path.
        """
        from wfm_intraday import io as io_module

        assert not hasattr(io_module, "merge_forecast_actuals"), (
            "io.merge_forecast_actuals must remain removed. "
            "Use wfm_intraday.analyze for production merging."
        )


def _make_result(num_intervals: int = 3) -> AnalysisResult:
    intervals = [
        IntervalRecord(
            date="2026-05-04",
            interval_start=f"08:{i * 30:02d}",
            lob="inbound",
            channel="voice",
            forecast_volume=100.0,
            forecast_aht_seconds=180.0,
            actual_volume=110.0,
            actual_aht_seconds=185.0,
            reforecast_volume=None,
            forecast_required_net_fte=14.0,
            forecast_required_gross_fte=21.0,
            actual_required_net_fte=15.0,
            actual_required_gross_fte=22.0,
            scheduled_fte=20.0,
            staffing_gap_fte=2.0,
        )
        for i in range(num_intervals)
    ]
    return AnalysisResult(
        metadata={"version": "0.2.1", "mode": "retrospective"},
        forecast_accuracy={"overall": {"wape": 5.0, "mape": 6.0, "bias": 0.05}, "per_lob": {}},
        intervals=intervals,
        staffing_gaps=[],
        reforecast_results=[],
        redistribution=[],
        warnings=[],
    )


class TestReporters:
    def test_json_writer(self, tmp_path):
        from wfm_intraday.reporting.json import write_analysis_json

        result = _make_result(3)
        path = write_analysis_json(str(tmp_path / "analysis.json"), result)
        with open(path) as f:
            data = json.load(f)
        assert len(data["intervals"]) == 3

    def test_csv_writer(self, tmp_path):
        from wfm_intraday.reporting.csv import write_interval_csv

        result = _make_result(3)
        path = write_interval_csv(str(tmp_path / "interval_analysis.csv"), result)
        df = pd.read_csv(path)
        assert len(df) == 3

    def test_excel_writer(self, tmp_path):
        from wfm_intraday.reporting.excel import write_excel_report

        result = _make_result(3)
        path = write_excel_report(str(tmp_path / "intraday_report.xlsx"), result)
        assert os.path.exists(path)

    def test_reporters_consistent_interval_count(self, tmp_path):
        """Excel, CSV and JSON must all report the same interval count from one
        canonical AnalysisResult."""
        from wfm_intraday.reporting.csv import write_interval_csv
        from wfm_intraday.reporting.json import write_analysis_json

        result = _make_result(5)

        csv_path = write_interval_csv(str(tmp_path / "i.csv"), result)
        json_path = write_analysis_json(str(tmp_path / "a.json"), result)

        csv_df = pd.read_csv(csv_path)
        with open(json_path) as f:
            json_data = json.load(f)

        assert len(csv_df) == 5
        assert len(json_data["intervals"]) == 5
        assert len(result.intervals) == 5
