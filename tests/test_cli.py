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

    def test_unknown_channel_validate_exit_2(self, tmp_path):
        """validate with an unsupported channel (fax) exits 2."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast", channel="fax")
        _write_csv(ac, "actuals")
        result = _run(["validate", "--forecast", str(fc), "--actual", str(ac)])
        assert result.returncode == 2
        assert "unsupported channel" in result.stderr

    def test_nan_validate_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast", forecast_volume=float("nan"))
        _write_csv(ac, "actuals")
        result = _run(["validate", "--forecast", str(fc), "--actual", str(ac)])
        assert result.returncode == 2
        assert "NaN" in result.stderr

    def test_bad_interval_validate_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast", interval_start="25:00")
        _write_csv(ac, "actuals")
        result = _run(["validate", "--forecast", str(fc), "--actual", str(ac)])
        assert result.returncode == 2

    def test_cli_column_mapping_end_to_end(self, tmp_path):
        """CLI analyze with external-column CSVs + --config column_mapping."""
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "interval_length_minutes: 30\n"
            "column_mapping:\n"
            "  forecast:\n"
            '    date: "Contact Date"\n'
            '    lob: "Queue"\n'
            '    interval_start: "Slot"\n'
            '    channel: "Chan"\n'
            '    forecast_volume: "FCast"\n'
            '    forecast_aht_seconds: "AHT"\n'
            "  actuals:\n"
            '    date: "Contact Date"\n'
            '    lob: "Queue"\n'
            '    interval_start: "Slot"\n'
            '    channel: "Chan"\n'
            '    actual_volume: "ACast"\n'
            '    actual_aht_seconds: "AHTa"\n'
        )
        fc = tmp_path / "vendor_fc.csv"
        ac = tmp_path / "vendor_ac.csv"
        fc.write_text(
            "Contact Date,Queue,Slot,Chan,FCast,AHT\n2026-09-01,inbound,08:00,voice,100.0,180.0\n"
        )
        ac.write_text(
            "Contact Date,Queue,Slot,Chan,ACast,AHTa\n2026-09-01,inbound,08:00,voice,110.0,180.0\n"
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        result = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--config",
                str(cfg),
                "--output-dir",
                str(out_dir),
            ]
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert out_dir.joinpath("intraday_report.xlsx").exists()
        assert out_dir.joinpath("analysis.json").exists()


def _write_csv(path, kind, **over):
    if kind == "forecast":
        row = {
            "date": ["2026-09-01"],
            "lob": ["inbound"],
            "interval_start": ["08:00"],
            "channel": ["voice"],
            "forecast_volume": [100.0],
            "forecast_aht_seconds": [180.0],
        }
        for k, v in over.items():
            row[k] = [v] if not isinstance(v, list) else v
        pd.DataFrame(row).to_csv(path, index=False)
    elif kind == "actuals":
        row = {
            "date": ["2026-09-01"],
            "lob": ["inbound"],
            "interval_start": ["08:00"],
            "channel": ["voice"],
            "actual_volume": [110.0],
            "actual_aht_seconds": [180.0],
        }
        for k, v in over.items():
            row[k] = [v] if not isinstance(v, list) else v
        pd.DataFrame(row).to_csv(path, index=False)
    else:
        pd.DataFrame(
            {
                "date": ["2026-09-01"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
                "scheduled_fte": [10.0],
            }
        ).to_csv(path, index=False)
