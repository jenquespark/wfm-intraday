"""CLI exit-code tests."""

from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

REPO = os.path.join(os.path.dirname(__file__), "..")


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "wfm_intraday.cli.main", *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO,
        check=False,
    )


class TestCLI:
    def test_missing_forecast_returns_2(self):
        result = _run(["analyze", "--forecast", "/nonexistent.csv", "--actual", "/nonexistent.csv"])
        assert result.returncode == 2

    def test_missing_config_returns_1(self):
        result = _run(
            [
                "analyze",
                "--forecast",
                "/nonexistent.csv",
                "--actual",
                "/nonexistent.csv",
                "--config",
                "/nonexistent.yaml",
            ]
        )
        assert result.returncode == 1

    def test_as_of_without_checkpoint_returns_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        result = _run(["analyze", "--forecast", str(fc), "--actual", str(ac), "--mode", "as-of"])
        assert result.returncode == 2

    def test_key_mismatch_returns_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        pd.DataFrame(
            {
                "date": ["2026-09-01"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
                "forecast_volume": [100.0],
                "forecast_aht_seconds": [180.0],
            }
        ).to_csv(fc, index=False)
        pd.DataFrame(
            {
                "date": ["2026-09-02"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
                "actual_volume": [110.0],
                "actual_aht_seconds": [180.0],
            }
        ).to_csv(ac, index=False)
        result = _run(["analyze", "--forecast", str(fc), "--actual", str(ac)])
        assert result.returncode == 2

    def test_duplicate_keys_returns_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        df = pd.DataFrame(
            {
                "date": ["2026-09-01", "2026-09-01"],
                "lob": ["inbound", "inbound"],
                "interval_start": ["08:00", "08:00"],
                "channel": ["voice", "voice"],
                "forecast_volume": [100.0, 100.0],
                "forecast_aht_seconds": [180.0, 180.0],
            }
        )
        df.to_csv(fc, index=False)
        _write_csv(ac, "actuals")
        result = _run(["analyze", "--forecast", str(fc), "--actual", str(ac)])
        assert result.returncode == 2


def _write_csv(path, kind):
    if kind == "forecast":
        pd.DataFrame(
            {
                "date": ["2026-09-01"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
                "forecast_volume": [100.0],
                "forecast_aht_seconds": [180.0],
            }
        ).to_csv(path, index=False)
    else:
        pd.DataFrame(
            {
                "date": ["2026-09-01"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
                "actual_volume": [110.0],
                "actual_aht_seconds": [180.0],
            }
        ).to_csv(path, index=False)
