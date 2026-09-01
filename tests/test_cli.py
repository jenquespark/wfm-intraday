import sys
import os
import tempfile
import subprocess

import pytest
import yaml


class TestCLI:
    def test_missing_forecast_returns_1(self):
        """Test via subprocess since the CLI is the main entry point."""
        result = subprocess.run(
            [sys.executable, "-m", "reforecast", "--forecast", "/nonexistent.csv", "--actuals", "/nonexistent.csv"],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 1

    def test_missing_config_returns_1(self):
        result = subprocess.run(
            [sys.executable, "reforecast.py", "--forecast", "/nonexistent.csv", "--actuals", "/nonexistent.csv"],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 1