"""Tests for CSV/Excel/JSON input/output."""

from __future__ import annotations

import os
import tempfile

import pandas as pd
import pytest

from reforecast.io import (
    load_csv,
    load_forecast,
    load_actuals,
    load_schedule,
    merge_forecast_actuals,
    write_excel_report,
    write_redistribution_csv,
    write_accuracy_json,
)
from reforecast.models import (
    FORECAST_COLUMNS,
    ACTUALS_COLUMNS,
    SCHEDULE_COLUMNS,
    AccuracyMetrics,
    RedistributionRecommendation,
    StaffingGap,
    validate_columns,
)


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

    def test_valid_csv(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("date,lob,interval_start,channel,forecast_volume,forecast_aht_seconds\n")
            f.write("2026-05-04,inbound,08:00,voice,100.0,180.0\n")
            fname = f.name
        df = load_csv(fname, FORECAST_COLUMNS)
        assert len(df) == 1
        assert list(df.columns) == FORECAST_COLUMNS
        os.unlink(fname)

    def test_missing_columns_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("date,lob\n2026-05-04,inbound\n")
            fname = f.name
        with pytest.raises(ValueError, match="Missing columns"):
            load_csv(fname, FORECAST_COLUMNS)
        os.unlink(fname)


class TestMergeForecastActuals:
    def test_merge_matched(self):
        fc = pd.DataFrame({
            "date": ["2026-05-04"], "lob": ["inbound"], "interval_start": ["08:00"],
            "channel": ["voice"], "forecast_volume": [100.0], "forecast_aht_seconds": [180.0],
        })
        ac = pd.DataFrame({
            "date": ["2026-05-04"], "lob": ["inbound"], "interval_start": ["08:00"],
            "channel": ["voice"], "actual_volume": [110.0], "actual_aht_seconds": [185.0],
        })
        merged, report = merge_forecast_actuals(fc, ac)
        assert len(merged) == 1
        assert report.matched_keys == 1

    def test_empty_merge_raises(self):
        fc = pd.DataFrame({
            "date": ["2026-05-04"], "lob": ["inbound"], "interval_start": ["08:00"],
            "channel": ["voice"], "forecast_volume": [100.0], "forecast_aht_seconds": [180.0],
        })
        ac = pd.DataFrame({
            "date": ["2026-05-05"], "lob": ["inbound"], "interval_start": ["08:00"],
            "channel": ["voice"], "actual_volume": [110.0], "actual_aht_seconds": [185.0],
        })
        with pytest.raises(ValueError, match="no overlapping"):
            merge_forecast_actuals(fc, ac)


class TestWriters:
    def test_write_accuracy_json(self, tmp_path):
        metrics = {"inbound": AccuracyMetrics(10.0, 12.0, 0.05)}
        overall = AccuracyMetrics(10.0, 12.0, 0.05)
        path = os.path.join(tmp_path, "metrics.json")
        result = write_accuracy_json(path, metrics, overall)
        assert os.path.exists(result)
        import json
        with open(result) as f:
            data = json.load(f)
        assert "per_lob" in data
        assert "overall" in data

    def test_write_redistribution_csv(self, tmp_path):
        recs = [
            RedistributionRecommendation(
                date="2026-05-04", lob="inbound", channel="voice",
                from_interval_start="08:00", to_interval_start="09:00",
                recommended_transfer_fte=1.5, recommended_transfer_hours=0.75,
                donor_remaining_surplus_fte=0.0,
                rationale="Test move",
            )
        ]
        path = os.path.join(tmp_path, "redist.csv")
        result = write_redistribution_csv(path, recs)
        assert os.path.exists(result)
        df = pd.read_csv(result)
        assert len(df) == 1

    def test_write_excel_report(self, tmp_path):
        lob_dfs = {"inbound": pd.DataFrame({"x": [1.0]})}
        metrics = {"inbound": AccuracyMetrics(10.0, 12.0, 0.05)}
        path = os.path.join(tmp_path, "report.xlsx")
        result = write_excel_report(path, lob_dfs, metrics, metrics["inbound"])
        assert os.path.exists(result)