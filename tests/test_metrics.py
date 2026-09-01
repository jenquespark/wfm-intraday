"""Tests for forecast accuracy metrics."""

from __future__ import annotations

import numpy as np

from reforecast.metrics import calculate_wape, calculate_mape, calculate_bias, calculate_all


def test_wape_perfect_forecast():
    """WAPE should be 0 when forecast matches actuals perfectly."""
    actuals = np.array([100.0, 200.0, 150.0])
    forecasts = np.array([100.0, 200.0, 150.0])
    result = calculate_wape(actuals, forecasts)
    assert result == 0.0, f"Expected 0, got {result}"


def test_wape_10_percent_error():
    """WAPE of exactly 10%: actuals=[10,10,10], forecasts=[9,11,10]."""
    actuals = np.array([10.0, 10.0, 10.0])
    forecasts = np.array([9.0, 11.0, 10.0])
    result = calculate_wape(actuals, forecasts)
    assert abs(result - 6.67) < 0.01, f"Expected ~6.67, got {result}"


def test_wape_50_percent_error():
    """WAPE of 50%: actuals=[100], forecasts=[50]."""
    actuals = np.array([100.0])
    forecasts = np.array([50.0])
    result = calculate_wape(actuals, forecasts)
    assert abs(result - 50.0) < 0.01, f"Expected 50.0, got {result}"


def test_mape_zero_error():
    """MAPE should be 0 when forecast matches actuals perfectly."""
    actuals = np.array([100.0, 200.0, 150.0])
    forecasts = np.array([100.0, 200.0, 150.0])
    result = calculate_mape(actuals, forecasts)
    assert result == 0.0, f"Expected 0, got {result}"


def test_mape_single_interval():
    """MAPE for one interval: actual=100, forecast=110 → 10%."""
    actuals = np.array([100.0])
    forecasts = np.array([110.0])
    result = calculate_mape(actuals, forecasts)
    assert abs(result - 10.0) < 0.01, f"Expected 10.0, got {result}"


def test_bias_zero():
    """Bias should be 0 for perfect forecast."""
    actuals = np.array([100.0, 200.0])
    forecasts = np.array([100.0, 200.0])
    result = calculate_bias(actuals, forecasts)
    assert result == 0.0, f"Expected 0, got {result}"


def test_bias_positive_underforecast():
    """Positive bias = underforecast (actual > forecast)."""
    actuals = np.array([120.0, 220.0])
    forecasts = np.array([100.0, 200.0])
    result = calculate_bias(actuals, forecasts)
    # sum(actual - forecast) / sum(actual) = (20+20)/(120+220) = 40/340 = 0.1176
    assert abs(result - 40.0 / 340.0) < 0.01, f"Expected ~0.1176, got {result}"


def test_bias_negative_overforecast():
    """Negative bias = overforecast (actual < forecast)."""
    actuals = np.array([80.0, 180.0])
    forecasts = np.array([100.0, 200.0])
    result = calculate_bias(actuals, forecasts)
    # (80-100)+(180-200) = -40; sum actual = 260; -40/260 = -0.1538
    assert abs(result - (-40.0 / 260.0)) < 0.01, f"Expected ~-0.1538, got {result}"


def test_calculate_all():
    """calculate_all returns all three metrics."""
    actuals = np.array([100.0, 200.0, 150.0])
    forecasts = np.array([90.0, 210.0, 155.0])
    result = calculate_all(actuals, forecasts)
    assert result.wape == calculate_wape(actuals, forecasts)
    assert result.mape == calculate_mape(actuals, forecasts)
    assert result.bias == calculate_bias(actuals, forecasts)


def test_wape_zero_actuals():
    """WAPE should handle zero actuals gracefully."""
    actuals = np.array([0.0, 0.0, 0.0])
    forecasts = np.array([10.0, 20.0, 30.0])
    result = calculate_wape(actuals, forecasts)
    assert result == 0.0, f"Expected 0 for zero actuals, got {result}"


def test_mape_with_zero_actual():
    """MAPE should skip intervals with zero actual volume."""
    actuals = np.array([0.0, 100.0, 0.0])
    forecasts = np.array([10.0, 110.0, 20.0])
    result = calculate_mape(actuals, forecasts)
    # Only the middle interval contributes: |100-110|/100 * 100 = 10%
    assert abs(result - 10.0) < 0.01, f"Expected 10.0, got {result}"


def test_wape_empty():
    """WAPE should raise ValueError on empty arrays."""
    try:
        calculate_wape(np.array([]), np.array([]))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_length_mismatch():
    """All metrics should raise on length mismatch."""
    for func in [calculate_wape, calculate_mape, calculate_bias]:
        try:
            func(np.array([1.0, 2.0]), np.array([1.0]))
            assert False, f"{func.__name__} should have raised"
        except ValueError:
            pass


if __name__ == "__main__":
    import sys
    test_functions = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test_fn in test_functions:
        try:
            test_fn()
            print(f"  ✓ {test_fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(test_functions)}")
    sys.exit(1 if failed > 0 else 0)