import sys
import os
import tempfile
import subprocess

import pytest
import yaml


class TestCLI:
    def test_missing_forecast_returns_2(self):
        """Missing input files should return EXIT_INPUT_ERROR (2)."""
        result = subprocess.run(
            [sys.executable, "-m", "wfm_intraday.cli.main", "analyze", "--forecast", "/nonexistent.csv", "--actual", "/nonexistent.csv"],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 2

    def test_missing_config_returns_1(self):
        """Missing config file should return EXIT_CONFIG_ERROR (1)."""
        result = subprocess.run(
            [sys.executable, "-m", "wfm_intraday.cli.main", "analyze", "--forecast", "/nonexistent.csv", "--actual", "/nonexistent.csv", "--config", "/nonexistent.yaml"],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 1