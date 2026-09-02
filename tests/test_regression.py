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


class TestPositionalMaskElimination:
    """Regression: positional completed_mask Series caused row-order bugs.

    Previously _build_completed_mask returned a boolean Series aligned to the
    merged DataFrame's positional index.  When inputs were unsorted the mask
    was applied to wrong rows after sort_values+reset_index, causing:
    - future actuals leaking into completed rows
    - completed actuals appearing as None in future rows

    Fix: completion is now computed per-interval via _is_completed() from
    the interval's canonical start time + config.  No positional mask exists.
    """

    def _write(self, tmp, name, df):
        import os

        p = os.path.join(tmp, name)
        df.to_csv(p, index=False)
        return p

    def test_unsorted_as_of_completion_is_correct(self):
        """Reviewer-reported bug: reversed row order with checkpoint=08:30.

        fc order: 09:00, 08:00  (reversed)
        ac order: 09:00, 08:00  (reversed)
        checkpoint: 08:30
        Expected: 08:00 completed (actual=100, required=21.21),
                  09:00 future    (actual=None, required=None)
        """
        import tempfile

        from wfm_intraday import analyze

        tmp = tempfile.mkdtemp()
        fc = pd.DataFrame(
            {
                "date": ["2026-09-01", "2026-09-01"],
                "lob": ["inbound", "inbound"],
                "interval_start": ["09:00", "08:00"],  # reversed
                "channel": ["voice", "voice"],
                "forecast_volume": [100.0, 100.0],
                "forecast_aht_seconds": [180.0, 180.0],
            }
        )
        ac = pd.DataFrame(
            {
                "date": ["2026-09-01", "2026-09-01"],
                "lob": ["inbound", "inbound"],
                "interval_start": ["09:00", "08:00"],  # reversed
                "channel": ["voice", "voice"],
                "actual_volume": [100.0, 100.0],
                "actual_aht_seconds": [180.0, 180.0],
            }
        )
        fcp = self._write(tmp, "fc.csv", fc)
        acp = self._write(tmp, "ac.csv", ac)
        result = analyze(fcp, acp, mode="as-of", checkpoint="08:30")

        by_start = {iv.interval_start: iv for iv in result.intervals}
        # 08:00 is completed (end=08:30 <= checkpoint=08:30)
        assert by_start["08:00"].actual_volume == 100.0
        assert by_start["08:00"].actual_required_gross_fte is not None
        assert by_start["08:00"].actual_required_gross_fte > 0
        # 09:00 is future (end=09:30 > checkpoint=08:30)
        assert by_start["09:00"].actual_volume is None
        assert by_start["09:00"].actual_required_gross_fte is None

    def test_as_of_result_is_order_invariant(self):
        """Shuffle both forecast and actuals; the output must be identical."""
        import tempfile

        import numpy as np

        from wfm_intraday import analyze

        tmp = tempfile.mkdtemp()
        # Canonical order (sorted)
        fc_sorted = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": ["08:00", "08:30", "09:00", "09:30"],
                "channel": ["voice"] * 4,
                "forecast_volume": [100.0, 100.0, 100.0, 100.0],
                "forecast_aht_seconds": [180.0, 180.0, 180.0, 180.0],
            }
        )
        ac_sorted = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": ["08:00", "08:30", "09:00", "09:30"],
                "channel": ["voice"] * 4,
                "actual_volume": [110.0, 90.0, 120.0, 80.0],
                "actual_aht_seconds": [180.0] * 4,
            }
        )
        # Shuffled order (deterministic via seed)
        rng = np.random.RandomState(42)
        fc_shuffled = fc_sorted.iloc[rng.permutation(len(fc_sorted))].reset_index(drop=True)
        ac_shuffled = ac_sorted.iloc[rng.permutation(len(ac_sorted))].reset_index(drop=True)

        fcs = self._write(tmp, "fc_sorted.csv", fc_sorted)
        acs = self._write(tmp, "ac_sorted.csv", ac_sorted)
        fcu = self._write(tmp, "fc_unsorted.csv", fc_shuffled)
        acu = self._write(tmp, "ac_unsorted.csv", ac_shuffled)

        r_sorted = analyze(fcs, acs, mode="as-of", checkpoint="08:30")
        r_unsorted = analyze(fcu, acu, mode="as-of", checkpoint="08:30")

        # Compare by interval_start (order-independent)
        by_start_s = {iv.interval_start: iv for iv in r_sorted.intervals}
        by_start_u = {iv.interval_start: iv for iv in r_unsorted.intervals}
        assert set(by_start_s.keys()) == set(by_start_u.keys())
        for k, s in by_start_s.items():
            u = by_start_u[k]
            assert s.actual_volume == u.actual_volume, f"{k}: actual_volume differs"
            assert s.forecast_volume == u.forecast_volume, f"{k}: forecast_volume differs"
            if s.actual_required_gross_fte is not None:
                assert u.actual_required_gross_fte is not None
                assert abs(s.actual_required_gross_fte - u.actual_required_gross_fte) < 1e-6, (
                    f"{k}: actual_required_gross_fte differs"
                )
            else:
                assert u.actual_required_gross_fte is None, f"{k}: expected None"

        # Reforecast must also match
        assert len(r_sorted.reforecast_results) == len(r_unsorted.reforecast_results)
        if r_sorted.reforecast_results:
            assert (
                abs(
                    r_sorted.reforecast_results[0].scale_factor
                    - r_unsorted.reforecast_results[0].scale_factor
                )
                < 1e-9
            )

    def test_future_actuals_are_null_after_sorting(self):
        """Future actuals must NEVER appear in output, regardless of input order.

        Scenario: 4 intervals, checkpoint=09:00 (08:00 and 08:30 completed,
        09:00 and 09:30 future).  Input actuals are REVERSED so 09:30 is the
        FIRST actual row.  After sorting+completion, 09:00 and 09:30 must
        have actual_volume=None and actual_required_fte=None.
        """
        import tempfile

        from wfm_intraday import analyze

        tmp = tempfile.mkdtemp()
        fc = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": ["09:30", "09:00", "08:30", "08:00"],  # reversed!
                "channel": ["voice"] * 4,
                "forecast_volume": [100.0] * 4,
                "forecast_aht_seconds": [180.0] * 4,
            }
        )
        ac = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": ["09:30", "09:00", "08:30", "08:00"],  # reversed!
                "channel": ["voice"] * 4,
                "actual_volume": [100.0, 100.0, 100.0, 100.0],
                "actual_aht_seconds": [180.0] * 4,
            }
        )
        fcp = self._write(tmp, "fc.csv", fc)
        acp = self._write(tmp, "ac.csv", ac)
        # checkpoint 09:00 → end<=09:00 → 08:00 (end 08:30), 08:30 (end 09:00) are completed
        # 09:00 (end 09:30) and 09:30 (end 10:00) are future
        result = analyze(fcp, acp, mode="as-of", checkpoint="09:00")

        by_start = {iv.interval_start: iv for iv in result.intervals}
        # Completed intervals have real actuals
        assert by_start["08:00"].actual_volume == 100.0
        assert by_start["08:00"].actual_required_gross_fte is not None
        assert by_start["08:30"].actual_volume == 100.0
        assert by_start["08:30"].actual_required_gross_fte is not None
        # Future intervals: actuals suppressed
        assert by_start["09:00"].actual_volume is None
        assert by_start["09:00"].actual_required_gross_fte is None
        assert by_start["09:30"].actual_volume is None
        assert by_start["09:30"].actual_required_gross_fte is None
        # Reforecast exists and is scaled for future
        assert len(result.reforecast_results) == 1
        assert result.reforecast_results[0].scale_factor != 0

    def test_distinct_volumes_unsorted_as_of(self):
        """Distinguishing assert: distinct actual volumes across the boundary.

        fc order: 09:00, 08:00  (reversed)
        ac:       09:00 actual=999, 08:00 actual=200  (reversed, distinct)
        checkpoint: 08:30
        Expected: 08:00 actual_volume == 200 (completed)
                  09:00 actual_volume is None (future)
        Using DISTINCT volumes forces the value to be tied to the right
        interval — equal values would hide a row/volume swap.
        """
        import tempfile

        from wfm_intraday import analyze

        tmp = tempfile.mkdtemp()
        fc = pd.DataFrame(
            {
                "date": ["2026-09-01", "2026-09-01"],
                "lob": ["inbound", "inbound"],
                "interval_start": ["09:00", "08:00"],  # reversed
                "channel": ["voice", "voice"],
                "forecast_volume": [100.0, 100.0],
                "forecast_aht_seconds": [180.0, 180.0],
            }
        )
        ac = pd.DataFrame(
            {
                "date": ["2026-09-01", "2026-09-01"],
                "lob": ["inbound", "inbound"],
                "interval_start": ["09:00", "08:00"],  # reversed
                "channel": ["voice", "voice"],
                "actual_volume": [999.0, 200.0],  # distinct values
                "actual_aht_seconds": [180.0, 180.0],
            }
        )
        fcp = self._write(tmp, "fc.csv", fc)
        acp = self._write(tmp, "ac.csv", ac)
        result = analyze(fcp, acp, mode="as-of", checkpoint="08:30")

        by_start = {iv.interval_start: iv for iv in result.intervals}
        # 08:00 completed -> actual 200 (NOT 999)
        assert by_start["08:00"].actual_volume == 200.0
        assert by_start["08:00"].actual_required_gross_fte is not None
        # 09:00 future -> actual suppressed to None (the 999 must never leak)
        assert by_start["09:00"].actual_volume is None
        assert by_start["09:00"].actual_required_gross_fte is None

    def test_as_of_order_invariant_including_staffing(self):
        """Shuffle forecast, actuals, AND staffing independently; outputs identical.

        Scenario: 4 intervals, checkpoint=08:30 (08:00 completed,
        08:30..09:30 future).  All three inputs are independently shuffled
        (deterministic seeds).  Intervals, reforecast scale, staffing gaps,
        and redistribution must be identical to the sorted-input run.
        """
        import tempfile

        import numpy as np

        from wfm_intraday import analyze

        tmp = tempfile.mkdtemp()
        starts = ["08:00", "08:30", "09:00", "09:30"]
        fc_sorted = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": starts,
                "channel": ["voice"] * 4,
                "forecast_volume": [100.0, 100.0, 100.0, 100.0],
                "forecast_aht_seconds": [180.0] * 4,
            }
        )
        ac_sorted = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": starts,
                "channel": ["voice"] * 4,
                "actual_volume": [200.0, 80.0, 999.0, 999.0],  # distinct completed
                "actual_aht_seconds": [180.0] * 4,
            }
        )
        sd_sorted = pd.DataFrame(
            {
                "date": ["2026-09-01"] * 4,
                "lob": ["inbound"] * 4,
                "interval_start": starts,
                "channel": ["voice"] * 4,
                "scheduled_fte": [10.0, 20.0, 30.0, 40.0],
            }
        )

        def _shuff(df, seed):
            return df.iloc[np.random.RandomState(seed).permutation(len(df))].reset_index(drop=True)

        runs = []
        for seed in (1, 2, 3):
            f = self._write(tmp, f"fc_{seed}.csv", _shuff(fc_sorted, seed))
            a = self._write(tmp, f"ac_{seed}.csv", _shuff(ac_sorted, 100 + seed))
            s = self._write(tmp, f"sd_{seed}.csv", _shuff(sd_sorted, 200 + seed))
            r = analyze(f, a, s, mode="as-of", checkpoint="08:30")
            runs.append(r)

        # Reference = first run.  All runs must be identical.
        ref = runs[0]
        ref_by_start = {iv.interval_start: iv for iv in ref.intervals}
        ref_scale = ref.reforecast_results[0].scale_factor if ref.reforecast_results else None
        ref_gap_by = {(g.interval_start, g.date, g.channel): g.gap_fte for g in ref.staffing_gaps}

        for r in runs[1:]:
            by_start = {iv.interval_start: iv for iv in r.intervals}
            assert set(by_start.keys()) == set(ref_by_start.keys())
            for k, ref_iv in ref_by_start.items():
                # completed 08:00 keeps its 200.0 against any shuffle
                if k == "08:00":
                    assert by_start[k].actual_volume == 200.0, f"{k}: {by_start[k].actual_volume}"
                else:
                    assert by_start[k].actual_volume is None, f"{k} should be future/None"
                assert by_start[k].forecast_volume == ref_iv.forecast_volume
            # reforecast scale identical
            assert r.reforecast_results
            assert abs(r.reforecast_results[0].scale_factor - ref_scale) < 1e-9
            # staffing gaps identical
            rg = {(g.interval_start, g.date, g.channel): g.gap_fte for g in r.staffing_gaps}
            assert rg == ref_gap_by


class _InputValHelpers:
    """Shared helpers for input-validation tests (rejection at validate stage)."""

    def _write(self, tmp, name, df):
        p = os.path.join(tmp, name)
        df.to_csv(p, index=False)
        return p

    def _fc(self, tmp, **over):
        row = {
            "date": ["2026-09-01"],
            "lob": ["inbound"],
            "interval_start": ["08:00"],
            "channel": ["voice"],
            "forecast_volume": [100.0],
            "forecast_aht_seconds": [180.0],
        }
        for k, v in over.items():
            if not isinstance(v, list):
                v = [v]
            row[k] = v
        return self._write(tmp, "fc.csv", pd.DataFrame(row))

    def _ac(self, tmp, **over):
        row = {
            "date": ["2026-09-01"],
            "lob": ["inbound"],
            "interval_start": ["08:00"],
            "channel": ["voice"],
            "actual_volume": [110.0],
            "actual_aht_seconds": [180.0],
        }
        for k, v in over.items():
            if not isinstance(v, list):
                v = [v]
            row[k] = v
        return self._write(tmp, "ac.csv", pd.DataFrame(row))


class TestNumericFieldsFailAtValidation(_InputValHelpers):
    def test_nan_required_field_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, forecast_volume=float("nan"))
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="NaN"):
            validate_input_files(fcp, acp)

    def test_non_numeric_numeric_field_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, forecast_volume="abc")
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="non-numeric"):
            validate_input_files(fcp, acp)

    def test_infinite_numeric_field_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp)
        acp = self._ac(tmp, actual_volume=float("inf"))
        with pytest.raises(ValueError, match="infinite|Inf"):
            validate_input_files(fcp, acp)

    def test_negative_numeric_field_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, forecast_volume=-5.0)
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="negative"):
            validate_input_files(fcp, acp)

    def test_zero_or_negative_aht_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, forecast_aht_seconds=0.0)
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="AHT|aht"):
            validate_input_files(fcp, acp)


class TestInvalidDatesAndIntervalsFailAtValidation(_InputValHelpers):
    def test_invalid_date_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, date="2026-13-40")
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="date"):
            validate_input_files(fcp, acp)

    def test_invalid_interval_hour_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, interval_start="25:00")
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="interval_start|hour"):
            validate_input_files(fcp, acp)

    def test_invalid_interval_minute_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, interval_start="08:75")
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="interval_start|minute"):
            validate_input_files(fcp, acp)

    def test_malformed_interval_fails_at_validation(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, interval_start="notatime")
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="interval_start"):
            validate_input_files(fcp, acp)


class TestChannelValidation(_InputValHelpers):
    def test_channel_normalization(self):
        """' VOICE ' / 'Voice' normalize to 'voice'; flows to output."""
        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, channel=" VOICE ")
        acp = self._ac(tmp, channel="Voice ")
        result = analyze(fcp, acp)
        assert result.intervals[0].channel == "voice"

    def test_chat_normalization_accepted(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, channel=" CHAT ")
        acp = self._ac(tmp, channel="chat")
        validate_input_files(fcp, acp)  # must not raise

    def test_unknown_channel_hard_fails(self):
        from wfm_intraday.validation.inputs import validate_input_files

        tmp = tempfile.mkdtemp()
        fcp = self._fc(tmp, channel="fax")
        acp = self._ac(tmp)
        with pytest.raises(ValueError, match="unsupported channel"):
            validate_input_files(fcp, acp)

    def test_async_email_unknown_hard_fail(self):
        from wfm_intraday.validation.inputs import validate_input_files

        for bad in ("async", "email", "SMS", "vOicex"):
            tmp = tempfile.mkdtemp()
            fcp = self._fc(tmp, channel=bad)
            acp = self._ac(tmp)
            with pytest.raises(ValueError, match="unsupported channel"):
                validate_input_files(fcp, acp)


class TestConfigColumnMappingEndToEnd:
    def _write_cfg(self, tmp):
        cfg_yaml = (
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
        p = os.path.join(tmp, "cfg.yaml")
        with open(p, "w") as f:
            f.write(cfg_yaml)
        return p

    def _write_mapped_csvs(self, tmp):
        fc_csv = (
            "Contact Date,Queue,Slot,Chan,FCast,AHT\n2026-09-01,inbound,08:00,voice,100.0,180.0\n"
        )
        ac_csv = (
            "Contact Date,Queue,Slot,Chan,ACast,AHTa\n2026-09-01,inbound,08:00,voice,110.0,180.0\n"
        )
        fcp = os.path.join(tmp, "vendor_fc.csv")
        acp = os.path.join(tmp, "vendor_ac.csv")
        with open(fcp, "w") as f:
            f.write(fc_csv)
        with open(acp, "w") as f:
            f.write(ac_csv)
        return fcp, acp

    def test_config_column_mapping_used_by_analyze_and_validate(self):
        """config.yaml column_mapping is consumed by both analyze() and validate()."""
        from wfm_intraday import analyze as run_analyze
        from wfm_intraday import validate as run_validate

        tmp = tempfile.mkdtemp()
        cfgp = self._write_cfg(tmp)
        fcp, acp = self._write_mapped_csvs(tmp)

        # validate() with config_path uses the mapping.
        rep = run_validate(fcp, acp, config_path=cfgp)
        assert rep.matched_keys == 1

        # analyze() with config_path uses the mapping.
        res = run_analyze(fcp, acp, config_path=cfgp)
        assert len(res.intervals) == 1
        assert res.intervals[0].actual_volume == 110.0
        assert res.intervals[0].forecast_volume == 100.0
        assert res.intervals[0].channel == "voice"

    def test_invalid_mapping_rejected(self):
        """Unknown canonical / unknown section / duplicate source hard-fail."""
        from wfm_intraday.config import Config

        # unknown canonical
        with pytest.raises(ValueError, match="Unknown canonical"):
            Config.from_dict({"column_mapping": {"forecast": {"lobby": "Queue"}}})
        # unknown section
        with pytest.raises(ValueError, match="Unknown column_mapping section"):
            Config.from_dict({"column_mapping": {"notasection": {"date": "D"}}})
        # duplicate source within a section
        with pytest.raises(ValueError, match="Duplicate source column"):
            Config.from_dict(
                {
                    "column_mapping": {
                        "forecast": {
                            "date": "Contact Date",
                            "lob": "Contact Date",
                        }
                    }
                }
            )

    def test_mapping_without_config_path_is_used_in_analyze(self):
        """Explicit per-section column_mapping arg is honored by analyze()."""
        tmp = tempfile.mkdtemp()
        fcp, acp = self._write_mapped_csvs(tmp)
        mapping = {
            "forecast": {
                "date": "Contact Date",
                "lob": "Queue",
                "interval_start": "Slot",
                "channel": "Chan",
                "forecast_volume": "FCast",
                "forecast_aht_seconds": "AHT",
            },
            "actuals": {
                "date": "Contact Date",
                "lob": "Queue",
                "interval_start": "Slot",
                "channel": "Chan",
                "actual_volume": "ACast",
                "actual_aht_seconds": "AHTa",
            },
        }
        res = analyze(fcp, acp, column_mapping=mapping)
        assert res.intervals[0].actual_volume == 110.0
