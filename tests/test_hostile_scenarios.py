"""Hostile-scenario exit-code matrix (Task 9).

Each scenario drives the REAL CLI as a subprocess against tmpdir CSVs and
records the exit code (the CLI's documented contract: 0 success, 1 config,
2 input, 3 calculation, 4 output) plus stderr tails for the error paths.
The exit-code assertions fail with the captured stderr tail so the pytest
output documents the actual stderr per scenario.

Completion for as-of mode is key/time based: an interval is completed when
its END (interval_start + 30 min) is <= the checkpoint.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

REPO = os.path.join(os.path.dirname(__file__), "..")

FULL_DAY = [
    "08:00",
    "08:30",
    "09:00",
    "09:30",
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "12:00",
    "12:30",
    "13:00",
    "13:30",
]
# Intervals whose END time is <= 12:00 (completed at checkpoint 12:00).
COMPLETED_BY_1200 = FULL_DAY[:8]  # 08:00..11:30, ends 08:30..12:00


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "wfm_intraday.cli.main", *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO,
        check=False,
    )


def _write_forecast(path, starts, volume=100.0, aht=180.0, channel="voice"):
    pd.DataFrame(
        {
            "date": ["2026-09-01"] * len(starts),
            "lob": ["inbound"] * len(starts),
            "interval_start": starts,
            "channel": [channel] * len(starts),
            "forecast_volume": [volume] * len(starts),
            "forecast_aht_seconds": [float(aht)] * len(starts),
        }
    ).to_csv(path, index=False)


def _write_actuals(path, starts, volume=110.0, aht=180.0):
    pd.DataFrame(
        {
            "date": ["2026-09-01"] * len(starts),
            "lob": ["inbound"] * len(starts),
            "interval_start": starts,
            "channel": ["voice"] * len(starts),
            "actual_volume": [float(volume)] * len(starts),
            "actual_aht_seconds": [float(aht)] * len(starts),
        }
    ).to_csv(path, index=False)


def _write_schedule(path, starts, fte=9.0):
    pd.DataFrame(
        {
            "date": ["2026-09-01"] * len(starts),
            "lob": ["inbound"] * len(starts),
            "interval_start": starts,
            "channel": ["voice"] * len(starts),
            "scheduled_fte": [float(fte)] * len(starts),
        }
    ).to_csv(path, index=False)


class TestHostileScenarioMatrix:
    def test_01_valid_retrospective_exit_0(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        sd = tmp_path / "sd.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, FULL_DAY)
        _write_schedule(sd, FULL_DAY)
        out = tmp_path / "out"
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--staffing",
                str(sd),
                "--date",
                "2026-09-01",
                "--output-dir",
                str(out),
            ]
        )
        assert r.returncode == 0, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert out.joinpath("intraday_report.xlsx").exists()
        assert out.joinpath("analysis.json").exists()
        assert out.joinpath("interval_analysis.csv").exists()

    def test_02_valid_as_of_future_only_exit_0(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, COMPLETED_BY_1200)
        out = tmp_path / "out"
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--mode",
                "as-of",
                "--checkpoint",
                "12:00",
                "--output-dir",
                str(out),
            ]
        )
        assert r.returncode == 0, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert out.joinpath("analysis.json").exists()

    def test_03_duplicate_key_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00", "08:00"])
        _write_actuals(ac, FULL_DAY)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "duplicate key" in r.stderr.lower()

    def test_04_retrospective_key_mismatch_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00", "08:30"])
        _write_actuals(ac, ["08:00"])
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "forecast-only" in r.stderr.lower()

    def test_05_completed_as_of_missing_actual_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00", "08:30", "09:00"])
        _write_actuals(ac, ["08:00"])  # 08:30 and 09:00 end <= 12:00, missing actual
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--mode",
                "as-of",
                "--checkpoint",
                "12:00",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "completed" in r.stderr.lower()

    def test_06_future_as_of_missing_actual_exit_0(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, COMPLETED_BY_1200)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--mode",
                "as-of",
                "--checkpoint",
                "12:00",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 0, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"

    def test_07_invalid_checkpoint_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, FULL_DAY)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--mode",
                "as-of",
                "--checkpoint",
                "99:99",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"

    def test_08_invalid_date_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, FULL_DAY)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--date",
                "2026-09-99",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"

    def test_09_invalid_config_exit_1(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, FULL_DAY)
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("totally_unknown_setting: 42\n")
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--config",
                str(cfg),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 1, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "Traceback" not in r.stderr
        assert "Invalid config" in r.stderr

    def test_10_invalid_input_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00"], volume="abc")
        _write_actuals(ac, FULL_DAY)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "non-numeric" in r.stderr.lower()

    def test_11_fax_channel_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00"], channel="fax")
        _write_actuals(ac, FULL_DAY)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "unsupported channel" in r.stderr

    def test_12_async_channel_exit_2(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00"], channel="async")
        _write_actuals(ac, FULL_DAY)
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert r.returncode == 2, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        assert "unsupported channel" in r.stderr

    def test_13_output_dir_over_existing_file_exit_4(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, FULL_DAY)
        _write_actuals(ac, FULL_DAY)
        blocker = tmp_path / "blocked"
        blocker.write_text("not a dir")
        bad_out = blocker / "sub"
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(bad_out),
            ]
        )
        assert r.returncode == 4, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"

    def test_14_zero_actual_volume_exit_0_and_preserved(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_forecast(fc, ["08:00", "08:30"])
        _write_actuals(ac, ["08:00", "08:30"], volume=0.0)
        out = tmp_path / "out"
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(out),
            ]
        )
        assert r.returncode == 0, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        df = pd.read_csv(out / "interval_analysis.csv")
        assert list(df["actual_volume"]) == [0.0, 0.0], "zero actual volume must survive as 0.0"
        assert not df["actual_volume"].isna().any(), "zero actual volume must not render blank"

    def test_15_zero_scheduled_fte_exit_0_and_preserved(self, tmp_path):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        sd = tmp_path / "sd.csv"
        _write_forecast(fc, ["08:00", "08:30"])
        _write_actuals(ac, ["08:00", "08:30"])
        _write_schedule(sd, ["08:00", "08:30"], fte=0.0)
        out = tmp_path / "out"
        r = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--staffing",
                str(sd),
                "--output-dir",
                str(out),
            ]
        )
        assert r.returncode == 0, f"stderr tail: {r.stderr.strip().splitlines()[-3:]}"
        df = pd.read_csv(out / "interval_analysis.csv")
        assert list(df["scheduled_fte"]) == [0.0, 0.0], "zero scheduled FTE must survive as 0.0"
        assert not df["scheduled_fte"].isna().any(), "zero scheduled FTE must not render blank"
