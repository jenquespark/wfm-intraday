"""Regression tests for as-of analysis, look-ahead bias, future staffing."""

from __future__ import annotations

import json
import tempfile
import os
import pandas as pd
import numpy as np
from reforecast.config import Config
from reforecast import analyze


def _make_forecast_actuals(num_intervals: int = 10, date: str = "2026-09-01"):
    """Create forecast and actuals DataFrames and write them to CSV files."""
    import tempfile
    tmp = tempfile.mkdtemp()

    intervals = [f"{8 + i // 2:02d}:{30 * (i % 2):02d}" for i in range(num_intervals)]
    forecast = [100.0] * num_intervals
    # Actuals: 150 for intervals before 12:00 (index 0-7), 100 after
    actuals = [150.0 if i < 8 else 100.0 for i in range(num_intervals)]

    fc_df = pd.DataFrame({
        "date": [date] * num_intervals,
        "lob": ["inbound"] * num_intervals,
        "interval_start": intervals,
        "channel": ["voice"] * num_intervals,
        "forecast_volume": forecast,
        "forecast_aht_seconds": [180.0] * num_intervals,
    })
    ac_df = pd.DataFrame({
        "date": [date] * num_intervals,
        "lob": ["inbound"] * num_intervals,
        "interval_start": intervals,
        "channel": ["voice"] * num_intervals,
        "actual_volume": actuals,
        "actual_aht_seconds": [180.0] * num_intervals,
    })

    fc_path = os.path.join(tmp, "forecast.csv")
    ac_path = os.path.join(tmp, "actuals.csv")
    fc_df.to_csv(fc_path, index=False)
    ac_df.to_csv(ac_path, index=False)
    return tmp, fc_path, ac_path


def _make_actuals_file(tmp_dir: str, volumes: list, date: str = "2026-09-01"):
    """Create an actuals file with specific volumes."""
    assert len(volumes) == 10
    intervals = [f"{8 + i // 2:02d}:{30 * (i % 2):02d}" for i in range(10)]
    ac_df = pd.DataFrame({
        "date": [date] * 10,
        "lob": ["inbound"] * 10,
        "interval_start": intervals,
        "channel": ["voice"] * 10,
        "actual_volume": volumes,
        "actual_aht_seconds": [180.0] * 10,
    })
    path = os.path.join(tmp_dir, "actuals_alt.csv")
    ac_df.to_csv(path, index=False)
    return path


class TestAsOfLookAhead:
    """GATE 10 + 36: Future actuals must not leak into as-of reforecast."""

    def test_future_actuals_do_not_change_reforecast(self):
        """Modifying future actuals must not change the as-of reforecast."""
        tmp = tempfile.mkdtemp()
        try:
            intervals = [f"{8 + i // 2:02d}:{30 * (i % 2):02d}" for i in range(10)]
            fc_df = pd.DataFrame({
                "date": ["2026-09-01"] * 10,
                "lob": ["inbound"] * 10,
                "interval_start": intervals,
                "channel": ["voice"] * 10,
                "forecast_volume": [100.0] * 10,
                "forecast_aht_seconds": [180.0] * 10,
            })
            # Original actuals: 150 pre-12:00, 100 after
            ac1 = [150.0 if i < 8 else 100.0 for i in range(10)]
            ac2 = [150.0 if i < 8 else 999.0 for i in range(10)]  # HUGELY different future

            fc_path = os.path.join(tmp, "forecast.csv")
            ac1_path = os.path.join(tmp, "actuals1.csv")
            ac2_path = os.path.join(tmp, "actuals2.csv")

            fc_df.to_csv(fc_path, index=False)

            ac_df1 = pd.DataFrame({
                "date": ["2026-09-01"] * 10,
                "lob": ["inbound"] * 10,
                "interval_start": intervals,
                "channel": ["voice"] * 10,
                "actual_volume": ac1,
                "actual_aht_seconds": [180.0] * 10,
            })
            ac_df2 = pd.DataFrame({
                "date": ["2026-09-01"] * 10,
                "lob": ["inbound"] * 10,
                "interval_start": intervals,
                "channel": ["voice"] * 10,
                "actual_volume": ac2,
                "actual_aht_seconds": [180.0] * 10,
            })
            ac1_path = os.path.join(tmp, "actuals1.csv")
            ac2_path = os.path.join(tmp, "actuals2.csv")
            ac_df1.to_csv(ac1_path, index=False)
            ac_df2.to_csv(ac2_path, index=False)

            config = Config(reforecast_checkpoint_interval=8, reforecast_blend_factor=1.0)

            # Run as-of analysis at checkpoint=8 (12:00)
            result1 = analyze(
                forecast_path=fc_path,
                actuals_path=ac1_path,
                config_obj=config,
                mode="as-of",
                checkpoint="12:00",
            )
            result2 = analyze(
                forecast_path=fc_path,
                actuals_path=ac2_path,
                config_obj=config,
                mode="as-of",
                checkpoint="12:00",
            )

            # The reforecast scale factors must be identical
            assert len(result1.reforecast_results) == 1
            assert len(result2.reforecast_results) == 1

            # Even though future actuals differ (100 vs 999), the reforecast
            # SCALE FACTOR must be the same because future actuals are masked.
            msg = (
                f"LOOK-AHEAD LEAK DETECTED: scale1={result1.reforecast_results[0].scale_factor:.6f}, "
                f"scale2={result2.reforecast_results[0].scale_factor:.6f}"
            )
            assert (
                abs(result1.reforecast_results[0].scale_factor
                    - result2.reforecast_results[0].scale_factor) < 1e-9
            ), msg
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_future_staffing_uses_reforecast_not_actual(self):
        """Future staffing gap must use reforecast requirement, not actual."""
        tmp = tempfile.mkdtemp()
        try:
            intervals = [f"{8 + i // 2:02d}:{30 * (i % 2):02d}" for i in range(10)]
            fc_df = pd.DataFrame({
                "date": ["2026-09-01"] * 10,
                "lob": ["inbound"] * 10,
                "interval_start": intervals,
                "channel": ["voice"] * 10,
                "forecast_volume": [100.0] * 10,
                "forecast_aht_seconds": [180.0] * 10,
            })
            ac_df = pd.DataFrame({
                "date": ["2026-09-01"] * 10,
                "lob": ["inbound"] * 10,
                "interval_start": intervals,
                "channel": ["voice"] * 10,
                "actual_volume": [150.0 if i < 8 else 0.0 for i in range(10)],
                "actual_aht_seconds": [180.0] * 10,
            })

            fc_path = os.path.join(tmp, "forecast.csv")
            ac_path = os.path.join(tmp, "actuals.csv")
            fc_df.to_csv(fc_path, index=False)
            ac_df.to_csv(ac_path, index=False)

            config = Config(reforecast_checkpoint_interval=8, reforecast_blend_factor=1.0)

            result = analyze(
                forecast_path=fc_path,
                actuals_path=ac_path,
                config_obj=config,
                mode="as-of",
                checkpoint="12:00",
            )

            # Find future intervals (index >= 8)
            future_intervals = [
                iv for iv in result.intervals
                if int(iv.interval_start.split(":")[0]) >= 12
            ]
            assert len(future_intervals) > 0, "Expected some future intervals"

            for iv in future_intervals:
                # Future intervals: actual values should be None (not 0.0)
                assert iv.actual_volume is None, (
                    f"Future interval {iv.interval_start}: actual_volume should be None, "
                    f"got {iv.actual_volume}"
                )
                # Future intervals should have reforecast_volume populated
                assert iv.reforecast_volume is not None, (
                    f"Future interval {iv.interval_start}: reforecast_volume is None"
                )
                # Future intervals should have reforecast-based staffing, not actual-based zero staffing
                if iv.reforecast_required_gross_fte is not None:
                    assert iv.reforecast_required_gross_fte > 0, (
                        f"Future interval {iv.interval_start}: reforecast_required_gross_fte "
                        f"should be positive, got {iv.reforecast_required_gross_fte}"
                    )
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_json_intervals_populated(self):
        """JSON output must contain interval records, not an empty list."""
        tmp = tempfile.mkdtemp()
        try:
            intervals = [f"{8 + i // 2:02d}:{30 * (i % 2):02d}" for i in range(4)]
            fc_df = pd.DataFrame({
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": intervals,
                "channel": ["voice"] * 4,
                "forecast_volume": [100.0] * 4,
                "forecast_aht_seconds": [180.0] * 4,
            })
            ac_df = pd.DataFrame({
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": intervals,
                "channel": ["voice"] * 4,
                "actual_volume": [110.0] * 4,
                "actual_aht_seconds": [180.0] * 4,
            })

            fc_path = os.path.join(tmp, "forecast.csv")
            ac_path = os.path.join(tmp, "actuals.csv")
            fc_df.to_csv(fc_path, index=False)
            ac_df.to_csv(ac_path, index=False)

            result = analyze(forecast_path=fc_path, actuals_path=ac_path)

            # Write JSON
            from reforecast.reporting.json import write_analysis_json
            json_path = os.path.join(tmp, "output.json")
            write_analysis_json(json_path, result)

            with open(json_path) as f:
                data = json.load(f)

            assert "intervals" in data, "JSON missing 'intervals' key"
            assert len(data["intervals"]) > 0, (
                f"JSON intervals is empty list — should have {len(result.intervals)} records"
            )
            assert data["intervals"][0]["forecast_volume"] is not None
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestShrinkageBoundary:
    """GATE 16: shrinkage boundary tests."""

    def test_shrinkage_zero(self):
        config = Config(shrinkage_pct=0.0)
        from reforecast.calculator import _compute_staffing_req
        req = _compute_staffing_req(100.0, 180.0, 1800, config, "voice")
        assert abs(req.gross_fte - req.net_fte) < 0.01

    def test_shrinkage_normal(self):
        config = Config(shrinkage_pct=0.34)
        from reforecast.calculator import _compute_staffing_req
        req = _compute_staffing_req(100.0, 180.0, 1800, config, "voice")
        expected = req.net_fte / 0.66
        assert abs(req.gross_fte - expected) < 0.01

    def test_shrinkage_high_valid(self):
        """0.99 shrinkage → gross = net / 0.01 (huge but valid)."""
        config = Config(shrinkage_pct=0.99)
        from reforecast.calculator import _compute_staffing_req
        req = _compute_staffing_req(100.0, 180.0, 1800, config, "voice")
        expected = req.net_fte / 0.01
        assert abs(req.gross_fte - expected) < 0.01

    def test_shrinkage_one_rejected(self):
        """shrinkage = 1.0 should be rejected by config."""
        import pytest
        with pytest.raises(ValueError):
            Config.from_dict({"shrinkage_pct": 1.0})

    def test_shrinkage_negative_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            Config.from_dict({"shrinkage_pct": -0.1})