"""Regression tests for as-of analysis, look-ahead bias, spine, and hardening.

These tests exercise the public ``analyze`` service (the single shared pipeline
used by CLI, web, and Python API) and assert exact behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pandas as pd
import pytest

from wfm_intraday import analyze
from wfm_intraday.config import Config


def _intervals(n: int, start_hour: int = 8) -> list:
    return [f"{start_hour + i // 2:02d}:{30 * (i % 2):02d}" for i in range(n)]


def _write(path, df):
    df.to_csv(path, index=False)


def _forecast(n=10, date="2026-09-01"):
    return pd.DataFrame(
        {
            "date": [date] * n,
            "lob": ["inbound"] * n,
            "interval_start": _intervals(n),
            "channel": ["voice"] * n,
            "forecast_volume": [100.0] * n,
            "forecast_aht_seconds": [180.0] * n,
        }
    )


def _actuals(n=10, date="2026-09-01", volumes=None):
    vols = volumes if volumes is not None else [100.0] * n
    return pd.DataFrame(
        {
            "date": [date] * n,
            "lob": ["inbound"] * n,
            "interval_start": _intervals(n),
            "channel": ["voice"] * n,
            "actual_volume": vols,
            "actual_aht_seconds": [180.0] * n,
        }
    )


class TestSpinePreservation:
    def test_full_forecast_spine_preserved_with_partial_actuals(self):
        """10 forecast rows + 8 completed actual rows => 10 output intervals.

        The forecast spine must be preserved; the two future intervals are
        retained with actual_volume=None.
        """
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            _write(fc_path, _forecast(10))
            # Only 8 actual rows (first 8 intervals completed).
            _write(ac_path, _actuals(8)[:8])

            result = analyze(
                fc_path,
                ac_path,
                mode="as-of",
                checkpoint="12:00",
                config_obj=Config(reforecast_blend_factor=1.0),
            )
            assert len(result.intervals) == 10, (
                f"Expected 10 intervals (full forecast spine), got {len(result.intervals)}"
            )
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestAsOfRequiresCheckpoint:
    def test_as_of_without_checkpoint_raises(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            _write(fc_path, _forecast(4))
            _write(ac_path, _actuals(4))
            with pytest.raises(ValueError, match="checkpoint"):
                analyze(fc_path, ac_path, mode="as-of", checkpoint=None)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestKeyMismatchHardFail:
    def test_forecast_only_keys_raise(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            _write(fc_path, _forecast(4, date="2026-09-01"))
            _write(ac_path, _actuals(4, date="2026-09-02"))  # different date
            with pytest.raises(ValueError, match="Key mismatch"):
                analyze(fc_path, ac_path)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestDuplicateKeysHardFail:
    def test_duplicate_forecast_keys_raise(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            fc = _forecast(4)
            # Duplicate the first forecast key.
            fc = pd.concat([fc, fc.iloc[[0]]], ignore_index=True)
            _write(fc_path, fc)
            _write(ac_path, _actuals(4))
            with pytest.raises(ValueError, match="duplicate"):
                analyze(fc_path, ac_path)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestLookAhead:
    def test_future_actuals_do_not_change_reforecast(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            _write(fc_path, _forecast(10))

            ac1_path = os.path.join(tmp, "ac1.csv")
            ac2_path = os.path.join(tmp, "ac2.csv")
            # Completed (pre-12:00) actuals same in both; future actuals differ.
            base = [150.0 if i < 8 else 100.0 for i in range(10)]
            changed = [150.0 if i < 8 else 999.0 for i in range(10)]
            _write(ac1_path, _actuals(10, volumes=base))
            _write(ac2_path, _actuals(10, volumes=changed))

            cfg = Config(reforecast_blend_factor=1.0)
            r1 = analyze(fc_path, ac1_path, mode="as-of", checkpoint="12:00", config_obj=cfg)
            r2 = analyze(fc_path, ac2_path, mode="as-of", checkpoint="12:00", config_obj=cfg)

            assert len(r1.reforecast_results) == 1
            assert len(r2.reforecast_results) == 1
            assert (
                abs(r1.reforecast_results[0].scale_factor - r2.reforecast_results[0].scale_factor)
                < 1e-9
            ), "LOOK-AHEAD LEAK: future actuals changed the reforecast"
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_future_aht_does_not_change_reforecast(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            _write(fc_path, _forecast(10))

            ac1 = _actuals(10, volumes=[150.0 if i < 8 else 100.0 for i in range(10)])
            ac2 = _actuals(10, volumes=[150.0 if i < 8 else 100.0 for i in range(10)])
            # Change future AHT only.
            ac2.loc[8:, "actual_aht_seconds"] = 9999.0
            ac1_path = os.path.join(tmp, "ac1.csv")
            ac2_path = os.path.join(tmp, "ac2.csv")
            _write(ac1_path, ac1)
            _write(ac2_path, ac2)

            cfg = Config(reforecast_blend_factor=1.0)
            r1 = analyze(fc_path, ac1_path, mode="as-of", checkpoint="12:00", config_obj=cfg)
            r2 = analyze(fc_path, ac2_path, mode="as-of", checkpoint="12:00", config_obj=cfg)

            assert (
                abs(r1.reforecast_results[0].scale_factor - r2.reforecast_results[0].scale_factor)
                < 1e-9
            ), "LOOK-AHEAD LEAK: future AHT changed the reforecast"
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_future_staffing_uses_reforecast_not_actual(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            _write(fc_path, _forecast(10))
            ac = _actuals(10, volumes=[150.0 if i < 8 else 0.0 for i in range(10)])
            ac_path = os.path.join(tmp, "ac.csv")
            _write(ac_path, ac)

            result = analyze(
                fc_path,
                ac_path,
                mode="as-of",
                checkpoint="12:00",
                config_obj=Config(reforecast_blend_factor=1.0),
            )

            future = [iv for iv in result.intervals if iv.interval_start >= "12:00"]
            assert len(future) > 0
            for iv in future:
                assert iv.actual_volume is None
                assert iv.reforecast_volume is not None
                if iv.reforecast_required_gross_fte is not None:
                    assert iv.reforecast_required_gross_fte > 0
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestZeroSemantics:
    def test_zero_actual_volume_produces_zero_requirement(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            _write(fc_path, _forecast(2))
            _write(ac_path, _actuals(2, volumes=[0.0, 0.0]))

            result = analyze(fc_path, ac_path, mode="retrospective")
            iv = result.intervals[0]
            assert iv.actual_volume == 0.0
            # Zero volume → zero requirement (populated, not None).
            assert iv.actual_required_gross_fte == 0.0
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestJsonIntervals:
    def test_json_intervals_populated(self):
        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            _write(fc_path, _forecast(4))
            _write(ac_path, _actuals(4))

            result = analyze(fc_path, ac_path)

            from wfm_intraday.reporting.json import write_analysis_json

            json_path = os.path.join(tmp, "out.json")
            write_analysis_json(json_path, result)

            with open(json_path) as f:
                data = json.load(f)
            assert len(data["intervals"]) == 4
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestShrinkageBoundary:
    def test_shrinkage_zero(self):
        from wfm_intraday.calculator import _compute_staffing_req

        req = _compute_staffing_req(100.0, 180.0, 1800, Config(shrinkage_pct=0.0), "voice")
        assert abs(req.gross_fte - req.net_fte) < 0.01

    def test_shrinkage_high_valid(self):
        from wfm_intraday.calculator import _compute_staffing_req

        req = _compute_staffing_req(100.0, 180.0, 1800, Config(shrinkage_pct=0.99), "voice")
        assert abs(req.gross_fte - req.net_fte / 0.01) < 0.01

    def test_shrinkage_one_rejected(self):
        with pytest.raises(ValueError):
            Config.from_dict({"shrinkage_pct": 1.0})

    def test_shrinkage_negative_rejected(self):
        with pytest.raises(ValueError):
            Config.from_dict({"shrinkage_pct": -0.1})


class TestUnknownConfigKey:
    def test_unknown_config_key_hard_fails(self):
        from wfm_intraday.config import Config

        with pytest.raises(ValueError, match="Unknown config key"):
            Config.from_dict({"totally_unknown_setting": 42})

    def test_misspelled_known_key_hard_fails(self):
        from wfm_intraday.config import Config

        # Misspelled known keys are not silently accepted.
        with pytest.raises(ValueError, match="Unknown config key"):
            Config.from_dict({"shrinnkage_pct": 0.3})


class TestUnknownChannelHardFail:
    def test_unknown_channel_via_validate(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            bad = pd.DataFrame(
                {
                    "date": ["2026-09-01"],
                    "lob": ["inbound"],
                    "interval_start": ["08:00"],
                    "channel": ["fax"],
                    "forecast_volume": [100.0],
                    "forecast_aht_seconds": [180.0],
                }
            )
            good = pd.DataFrame(
                {
                    "date": ["2026-09-01"],
                    "lob": ["inbound"],
                    "interval_start": ["08:00"],
                    "channel": ["voice"],
                    "actual_volume": [110.0],
                    "actual_aht_seconds": [180.0],
                }
            )
            _write(fc_path, bad)
            _write(ac_path, good)
            with pytest.raises(ValueError, match="unsupported channel"):
                validate_input_files(fc_path, ac_path)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_async_channel_via_validate(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            bad = pd.DataFrame(
                {
                    "date": ["2026-09-01"],
                    "lob": ["inbound"],
                    "interval_start": ["08:00"],
                    "channel": ["async"],
                    "forecast_volume": [100.0],
                    "forecast_aht_seconds": [180.0],
                }
            )
            good = pd.DataFrame(
                {
                    "date": ["2026-09-01"],
                    "lob": ["inbound"],
                    "interval_start": ["08:00"],
                    "channel": ["voice"],
                    "actual_volume": [110.0],
                    "actual_aht_seconds": [180.0],
                }
            )
            _write(fc_path, bad)
            _write(ac_path, good)
            with pytest.raises(ValueError, match="unsupported channel"):
                validate_input_files(fc_path, ac_path)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestColumnMappingDirection:
    def test_canonical_to_source_mapping_applied(self):
        """GenericCSVAdapter maps canonical->source in the config format."""
        from wfm_intraday.adapters.generic_csv import GenericCSVAdapter

        tmp = tempfile.mkdtemp()
        try:
            # Source CSV uses vendor column names.
            src = pd.DataFrame(
                {
                    "Contact Date": ["2026-09-01"],
                    "Queue Name": ["inbound"],
                    "Time Slot": ["08:00"],
                    "Channel": ["voice"],
                    "Calls Forecast": [100.0],
                    "AHT": [180.0],
                }
            )
            path = os.path.join(tmp, "vendor.csv")
            src.to_csv(path, index=False)

            # Mapping in canonical->source format.
            mapping = {
                "forecast": {
                    "date": "Contact Date",
                    "lob": "Queue Name",
                    "interval_start": "Time Slot",
                    "channel": "Channel",
                    "forecast_volume": "Calls Forecast",
                    "forecast_aht_seconds": "AHT",
                }
            }
            adapter = GenericCSVAdapter(mapping)
            df = adapter.load_forecast(path)
            assert "forecast_volume" in df.columns, "canonical column missing"
            assert "Calls Forecast" not in df.columns, "source column remains"
            assert df["forecast_volume"].iloc[0] == 100.0
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class TestUnifiedAdapterPipeline:
    def test_canonical_input_and_mapped_input_both_work(self):
        """CLI/API/web share one adapter pipeline; canonical and mapped both pass."""
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        try:
            # Canonical CSV (no mapping needed).
            fc_canon = os.path.join(tmp, "fc_canon.csv")
            ac_canon = os.path.join(tmp, "ac_canon.csv")
            _write(
                fc_canon,
                pd.DataFrame(
                    {
                        "date": ["2026-09-01"],
                        "lob": ["inbound"],
                        "interval_start": ["08:00"],
                        "channel": ["voice"],
                        "forecast_volume": [100.0],
                        "forecast_aht_seconds": [180.0],
                    }
                ),
            )
            _write(
                ac_canon,
                pd.DataFrame(
                    {
                        "date": ["2026-09-01"],
                        "lob": ["inbound"],
                        "interval_start": ["08:00"],
                        "channel": ["voice"],
                        "actual_volume": [110.0],
                        "actual_aht_seconds": [180.0],
                    }
                ),
            )
            # Mapped (vendor) CSV.
            fc_map = os.path.join(tmp, "fc_map.csv")
            ac_map = os.path.join(tmp, "ac_map.csv")
            _write(
                fc_map,
                pd.DataFrame(
                    {
                        "Contact Date": ["2026-09-01"],
                        "Queue": ["inbound"],
                        "Slot": ["08:00"],
                        "Chan": ["voice"],
                        "FCast": [100.0],
                        "AHT_f": [180.0],
                    }
                ),
            )
            _write(
                ac_map,
                pd.DataFrame(
                    {
                        "Contact Date": ["2026-09-01"],
                        "Queue": ["inbound"],
                        "Slot": ["08:00"],
                        "Chan": ["voice"],
                        "Actual": [110.0],
                        "AHT_a": [180.0],
                    }
                ),
            )
            flat_map = {
                "date": "Contact Date",
                "lob": "Queue",
                "interval_start": "Slot",
                "channel": "Chan",
                "forecast_volume": "FCast",
                "forecast_aht_seconds": "AHT_f",
                "actual_volume": "Actual",
                "actual_aht_seconds": "AHT_a",
            }

            # Both must load without error.
            fcn, acn, _, _ = validate_input_files(fc_canon, ac_canon)
            fcm, acm, _, _ = validate_input_files(fc_map, ac_map, column_mapping=flat_map)

            assert list(fcn.columns) == list(fcm.columns)
            assert fcn["forecast_volume"].iloc[0] == fcm["forecast_volume"].iloc[0] == 100.0
            assert acn["actual_volume"].iloc[0] == acm["actual_volume"].iloc[0] == 110.0
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_mapped_input_still_hard_fails_unknown_channel(self):
        """Even with a mapping, unknown channels are rejected."""
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        try:
            fc_path = os.path.join(tmp, "fc.csv")
            ac_path = os.path.join(tmp, "ac.csv")
            _write(
                fc_path,
                pd.DataFrame(
                    {
                        "Contact Date": ["2026-09-01"],
                        "Queue": ["inbound"],
                        "Slot": ["08:00"],
                        "Chan": ["fax"],
                        "FCast": [100.0],
                        "AHT_f": [180.0],
                    }
                ),
            )
            _write(
                ac_path,
                pd.DataFrame(
                    {
                        "date": ["2026-09-01"],
                        "lob": ["inbound"],
                        "interval_start": ["08:00"],
                        "channel": ["voice"],
                        "actual_volume": [110.0],
                        "actual_aht_seconds": [180.0],
                    }
                ),
            )
            flat_map = {
                "date": "Contact Date",
                "lob": "Queue",
                "interval_start": "Slot",
                "channel": "Chan",
                "forecast_volume": "FCast",
                "forecast_aht_seconds": "AHT_f",
            }
            with pytest.raises(ValueError, match="unsupported channel"):
                validate_input_files(fc_path, ac_path, column_mapping=flat_map)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
