"""Tests for forecast accuracy metrics — WAPE, MAPE, bias."""

from __future__ import annotations

import numpy as np
from wfm_intraday.metrics import calculate_wape, calculate_mape, calculate_bias, calculate_all


class TestWAPE:
    def test_perfect_forecast(self):
        assert calculate_wape(np.array([100.0, 200.0]), np.array([100.0, 200.0])) == 0.0

    def test_50_percent(self):
        result = calculate_wape(np.array([100.0]), np.array([50.0]))
        assert abs(result - 50.0) < 0.01

    def test_zero_actuals(self):
        assert calculate_wape(np.array([0.0, 0.0]), np.array([10.0, 20.0])) == 0.0

    def test_empty_raises(self):
        import pytest
        with pytest.raises(ValueError):
            calculate_wape(np.array([]), np.array([]))

    def test_length_mismatch_raises(self):
        import pytest
        with pytest.raises(ValueError):
            calculate_wape(np.array([1.0]), np.array([1.0, 2.0]))


class TestMAPE:
    def test_perfect_forecast(self):
        assert calculate_mape(np.array([100.0, 200.0]), np.array([100.0, 200.0])) == 0.0

    def test_10_percent(self):
        result = calculate_mape(np.array([100.0]), np.array([110.0]))
        assert abs(result - 10.0) < 0.01

    def test_zero_actual_skipped(self):
        """Intervals with zero actual volume are excluded from the mean."""
        result = calculate_mape(np.array([0.0, 100.0, 0.0]), np.array([10.0, 110.0, 20.0]))
        assert abs(result - 10.0) < 0.01

    def test_all_zero_actuals(self):
        assert calculate_mape(np.array([0.0, 0.0]), np.array([10.0, 20.0])) == 0.0

    def test_empty_raises(self):
        import pytest
        with pytest.raises(ValueError):
            calculate_mape(np.array([]), np.array([]))


class TestBias:
    def test_zero(self):
        assert calculate_bias(np.array([100.0, 200.0]), np.array([100.0, 200.0])) == 0.0

    def test_positive_underforecast(self):
        """Positive = actual > forecast (underforecast)."""
        a = np.array([120.0, 220.0])
        f = np.array([100.0, 200.0])
        expected = (20.0 + 20.0) / (120.0 + 220.0)
        assert abs(calculate_bias(a, f) - expected) < 0.001

    def test_negative_overforecast(self):
        a = np.array([80.0, 180.0])
        f = np.array([100.0, 200.0])
        expected = (-20.0 + -20.0) / (80.0 + 180.0)
        assert abs(calculate_bias(a, f) - expected) < 0.001

    def test_zero_actuals(self):
        assert calculate_bias(np.array([0.0, 0.0]), np.array([10.0, 20.0])) == 0.0


class TestCalculateAll:
    def test_returns_all_three(self):
        a = np.array([100.0, 200.0, 150.0])
        f = np.array([90.0, 210.0, 155.0])
        result = calculate_all(a, f)
        assert result.wape == calculate_wape(a, f)
        assert result.mape == calculate_mape(a, f)
        assert result.bias == calculate_bias(a, f)