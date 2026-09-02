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

    def test_invalid_checkpoint_exit_2(self, tmp_path):
        """A malformed checkpoint hard-fails with exit 2 (never succeeds)."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        for bad in ("99:99", "12:70", "-1:00", "24:00", "12am", "notatime", "12345"):
            result = _run(
                [
                    "analyze",
                    "--forecast",
                    str(fc),
                    "--actual",
                    str(ac),
                    "--mode",
                    "as-of",
                    "--checkpoint",
                    bad,
                ]
            )
            assert result.returncode == 2, f"checkpoint={bad} rc={result.returncode}"

    def test_invalid_date_filter_exit_2(self, tmp_path):
        """A non-calendar date_filter hard-fails with exit 2."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        for bad in ("2026-09-99", "2026-13-01", "not-a-date", "2026/09/01"):
            result = _run(["analyze", "--forecast", str(fc), "--actual", str(ac), "--date", bad])
            assert result.returncode == 2, f"date={bad} rc={result.returncode}"

    def test_validate_explicit_invalid_config_returns_1(self, tmp_path):
        """validate with an explicit malformed --config exits 1 (config error)."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("totally_unknown_setting: 42\n")
        result = _run(
            ["validate", "--forecast", str(fc), "--actual", str(ac), "--config", str(cfg)]
        )
        assert result.returncode == 1, f"stderr={result.stderr}"
        assert "Traceback" not in result.stderr

    def test_validate_missing_config_returns_1(self, tmp_path):
        """validate with a missing --config path exits 1 (config error)."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        result = _run(
            [
                "validate",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--config",
                str(tmp_path / "does_not_exist.yaml"),
            ]
        )
        assert result.returncode == 1
        assert "Traceback" not in result.stderr

    def test_analyze_malformed_default_config_returns_1(self, tmp_path):
        """A malformed default config.yaml in cwd exits 1, never a traceback."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("shrinnkage_pct: 0.30\n")  # misspelled key -> ValueError
        result = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--output-dir",
                str(tmp_path / "out"),
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 1, f"stderr={result.stderr}"
        assert "Traceback" not in result.stderr
        assert "Unknown config key" in result.stderr

    def test_validate_malformed_default_config_returns_1(self, tmp_path):
        """validate with a malformed default config.yaml in cwd exits 1."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("totally_unknown_setting: 42\n")
        result = _run(
            ["validate", "--forecast", str(fc), "--actual", str(ac)],
            cwd=tmp_path,
        )
        assert result.returncode == 1, f"stderr={result.stderr}"
        assert "Unknown config key" in result.stderr

    def test_output_dir_failure_exit_4(self, tmp_path):
        """When the output directory cannot be created, exit is 4."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        # An existing FILE named 'out' blocks os.makedirs('.../out/...').
        blocker = tmp_path / "blocked"
        blocker.write_text("not a dir")
        bad_out = blocker / "sub"  # parent is a file -> OSError
        result = _run(
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
        assert result.returncode == 4

    def test_date_filter_whitespace_ok(self, tmp_path):
        """A date_filter with surrounding whitespace still matches (normalized)."""
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        result = _run(
            [
                "analyze",
                "--forecast",
                str(fc),
                "--actual",
                str(ac),
                "--date",
                "  2026-09-01  ",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        assert result.returncode == 0, f"stderr={result.stderr}"


class TestConfigTypeErrorExitCode:
    """A config whose values have the wrong types must exit 1, no traceback."""

    @pytest.mark.parametrize(
        "bad_yaml",
        [
            'interval_length_minutes: "30"\n',
            'aht_seconds: "270"\n',
            'shrinkage_pct: "0.34"\n',
            "shrinkage_pct: .nan\n",
            'chat_concurrency: "3"\n',
            'channels:\n  voice:\n    channel_type: voice\n    concurrency: "3"\n',
            'channels:\n  voice:\n    channel_type: voice\n    enabled: "yes"\n',
        ],
    )
    def test_malformed_type_config_exits_1_no_traceback(self, tmp_path, bad_yaml):
        fc = tmp_path / "fc.csv"
        ac = tmp_path / "ac.csv"
        _write_csv(fc, "forecast")
        _write_csv(ac, "actuals")
        cfg = tmp_path / "bad.yaml"
        cfg.write_text(bad_yaml)
        result = _run(
            ["validate", "--forecast", str(fc), "--actual", str(ac), "--config", str(cfg)]
        )
        assert result.returncode == 1, f"stderr={result.stderr}"
        assert "Traceback" not in result.stderr


class TestWebCommand:
    """cmd_web propagates the streamlit subprocess exit code."""

    def test_web_subprocess_nonzero_returns_3(self, monkeypatch):
        """A failing streamlit web process must NOT report success — exit 3."""
        import argparse
        import types

        import wfm_intraday.cli.main as cli_main

        monkeypatch.setitem(sys.modules, "streamlit", types.ModuleType("streamlit"))

        class _FakeProc:
            returncode = 3

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
        assert cli_main.cmd_web(argparse.Namespace()) == 3  # EXIT_CALC_ERROR

    def test_web_subprocess_zero_returns_0(self, monkeypatch):
        """A successful streamlit web process returns success (exit 0)."""
        import argparse
        import types

        import wfm_intraday.cli.main as cli_main

        monkeypatch.setitem(sys.modules, "streamlit", types.ModuleType("streamlit"))

        class _FakeProc:
            returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
        assert cli_main.cmd_web(argparse.Namespace()) == 0  # EXIT_SUCCESS

    def test_web_import_missing_returns_2(self, monkeypatch):
        """Missing streamlit keeps the clear message and returns the input
        error code (2) as before — never a traceback or a false success."""
        import argparse

        import wfm_intraday.cli.main as cli_main

        # sys.modules['streamlit'] = None makes `import streamlit` raise
        # ImportError, matching an environment without the web extra.
        monkeypatch.setitem(sys.modules, "streamlit", None)
        assert cli_main.cmd_web(argparse.Namespace()) == 2  # EXIT_INPUT_ERROR


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
