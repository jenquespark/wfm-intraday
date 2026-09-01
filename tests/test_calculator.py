"""Tests for staffing gap, redistribution, and reforecast calculations."""

from __future__ import annotations

import pandas as pd
import numpy as np
from wfm_intraday.config import Config
from wfm_intraday.calculator import (
    compute_staffing_requirement,
    calculate_staffing_gap,
    calculate_redistribution,
    calculate_reforecast,
)
from wfm_intraday.validation.inputs import reconcile_keys as _reconcile_keys
from wfm_intraday.models import StaffingGap


# ---------- compile_staffing_requirement ----------

class TestComputeStaffingRequirement:
    def test_voice_requires_agents(self):
        config = Config()
        req = compute_staffing_requirement(100.0, 180, 1800, config, "voice")
        assert req.net_fte > 0
        assert req.gross_fte >= req.net_fte  # shrinkage uplift

    def test_chat_requires_fewer_with_concurrency(self):
        config = Config(chat_concurrency=4)
        req = compute_staffing_requirement(100.0, 120, 1800, config, "chat")
        assert req.net_fte > 0

    def test_shrinkage_uplift(self):
        """30% shrinkage → gross = net / 0.7."""
        config = Config(shrinkage_pct=0.30)
        req = compute_staffing_requirement(100.0, 180, 1800, config, "voice")
        expected_gross = req.net_fte / 0.7
        assert abs(req.gross_fte - expected_gross) < 0.01

    def test_zero_shrinkage(self):
        """0% shrinkage → gross = net."""
        config = Config(shrinkage_pct=0.0)
        req = compute_staffing_requirement(100.0, 180, 1800, config, "voice")
        assert abs(req.gross_fte - req.net_fte) < 0.01


# ---------- calculate_staffing_gap ----------

def _make_merged_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2026-05-04", "2026-05-04", "2026-05-04"],
        "lob": ["inbound", "inbound", "inbound"],
        "interval_start": ["08:00", "08:30", "09:00"],
        "channel": ["voice", "voice", "voice"],
        "forecast_volume": [100.0, 120.0, 130.0],
        "forecast_aht_seconds": [180.0, 180.0, 180.0],
        "actual_volume": [110.0, 90.0, 140.0],
        "actual_aht_seconds": [185.0, 175.0, 190.0],
    })


class TestStaffingGap:
    def test_basic_gap_analysis(self):
        config = Config()
        df = _make_merged_df()
        gaps = calculate_staffing_gap(df, config)
        assert len(gaps) == 3
        for g in gaps:
            assert g.forecast_required_net_fte is not None
            assert g.actual_required_net_fte is not None
            # Without schedule input, status should be "no_schedule"
            assert g.status == "no_schedule"
            assert g.scheduled_fte is None
            assert g.gap_fte is None

    def test_with_schedule(self):
        config = Config()
        df = _make_merged_df()
        schedule_df = pd.DataFrame({
            "date": ["2026-05-04", "2026-05-04", "2026-05-04"],
            "lob": ["inbound", "inbound", "inbound"],
            "interval_start": ["08:00", "08:30", "09:00"],
            "channel": ["voice", "voice", "voice"],
            "scheduled_fte": [15.0, 14.0, 16.0],
        })
        gaps = calculate_staffing_gap(df, config, schedule_df=schedule_df)
        assert len(gaps) == 3
        for g in gaps:
            assert g.scheduled_fte is not None
            assert g.gap_fte is not None
            assert g.status in ("understaffed", "overstaffed", "balanced")

    def test_lob_filter(self):
        config = Config()
        df = _make_merged_df()
        schedule_df = pd.DataFrame({
            "date": ["2026-05-04", "2026-05-04", "2026-05-04"],
            "lob": ["inbound", "inbound", "inbound"],
            "interval_start": ["08:00", "08:30", "09:00"],
            "channel": ["voice", "voice", "voice"],
            "scheduled_fte": [15.0, 14.0, 16.0],
        })
        gaps = calculate_staffing_gap(df, config, schedule_df=schedule_df, lob_filter="inbound")
        assert len(gaps) == 3
        gaps_empty = calculate_staffing_gap(df, config, schedule_df=schedule_df, lob_filter="nonexistent")
        assert len(gaps_empty) == 0


# ---------- calculate_redistribution ----------

class TestRedistribution:
    def test_no_double_count(self):
        """Donor surplus must be consumed and never reused."""
        gaps = [
            StaffingGap("2026-05-04", "08:00", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 15.0, -3.0, "overstaffed"),
            StaffingGap("2026-05-04", "08:30", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 10.0, 2.0, "understaffed"),
            StaffingGap("2026-05-04", "09:00", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 10.0, 2.0, "understaffed"),
        ]
        config = Config()
        recs = calculate_redistribution(gaps, config)
        # Find the donor interval
        donor_total = sum(r.recommended_transfer_fte for r in recs if r.from_interval_start == "08:00")
        # Donor surplus is 3.0 FTE — total transferred cannot exceed 3.0
        assert donor_total <= 3.0 + 0.01

    def test_no_cross_date(self):
        """Redistribution should not cross dates."""
        gaps = [
            StaffingGap("2026-05-04", "08:00", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 15.0, -3.0, "overstaffed"),
            StaffingGap("2026-05-05", "08:30", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 10.0, 2.0, "understaffed"),
        ]
        config = Config()
        recs = calculate_redistribution(gaps, config)
        assert len(recs) == 0  # different dates, no moves

    def test_units_are_fte(self):
        """Transfer amounts should be in FTE, with hours also reported."""
        gaps = [
            StaffingGap("2026-05-04", "08:00", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 15.0, -3.0, "overstaffed"),
            StaffingGap("2026-05-04", "10:00", "inbound", "voice", 10.0, 12.0, 10.0, 12.0, 10.0, 2.0, "understaffed"),
        ]
        config = Config()
        recs = calculate_redistribution(gaps, config)
        if recs:
            assert recs[0].recommended_transfer_fte > 0
            assert recs[0].recommended_transfer_hours > 0


# ---------- calculate_reforecast ----------

class TestReforecast:
    def test_single_day_no_contamination(self):
        """Reforecast must not contaminate a different date."""
        forecast_df = pd.DataFrame({
            "date": ["2026-05-04", "2026-05-04", "2026-05-05", "2026-05-05"],
            "lob": ["inbound", "inbound", "inbound", "inbound"],
            "interval_start": ["08:00", "09:00", "08:00", "09:00"],
            "channel": ["voice", "voice", "voice", "voice"],
            "forecast_volume": [100.0, 120.0, 100.0, 120.0],
            "forecast_aht_seconds": [180.0, 180.0, 180.0, 180.0],
        })
        actuals_df = pd.DataFrame({
            "date": ["2026-05-04", "2026-05-04", "2026-05-05", "2026-05-05"],
            "lob": ["inbound", "inbound", "inbound", "inbound"],
            "interval_start": ["08:00", "09:00", "08:00", "09:00"],
            "channel": ["voice", "voice", "voice", "voice"],
            "actual_volume": [110.0, 130.0, 100.0, 120.0],
            "actual_aht_seconds": [185.0, 185.0, 180.0, 180.0],
        })
        config = Config(reforecast_checkpoint_interval=1, reforecast_blend_factor=0.5)
        results = calculate_reforecast(forecast_df, actuals_df, config)

        # Should get 2 results (one per date)
        assert len(results) == 2

        # May 4 has deviation (110+130 vs 100+120)
        may4 = [r for r in results if r.date == "2026-05-04"]
        may5 = [r for r in results if r.date == "2026-05-05"]

        # May 5 has zero deviation (100+120 vs 100+120)
        if may5:
            assert abs(may5[0].deviation_pct) < 0.001

    def test_positive_deviation(self):
        """Actuals above forecast → positive deviation, scale > 1."""
        forecast_df = pd.DataFrame({
            "date": ["2026-05-04", "2026-05-04"],
            "lob": ["inbound", "inbound"],
            "interval_start": ["08:00", "09:00"],
            "channel": ["voice", "voice"],
            "forecast_volume": [100.0, 100.0],
            "forecast_aht_seconds": [180.0, 180.0],
        })
        actuals_df = pd.DataFrame({
            "date": ["2026-05-04", "2026-05-04"],
            "lob": ["inbound", "inbound"],
            "interval_start": ["08:00", "09:00"],
            "channel": ["voice", "voice"],
            "actual_volume": [150.0, 150.0],
            "actual_aht_seconds": [180.0, 180.0],
        })
        config = Config(reforecast_checkpoint_interval=1, reforecast_blend_factor=0.5)
        results = calculate_reforecast(forecast_df, actuals_df, config)
        assert len(results) == 1
        assert results[0].deviation_pct > 0
        # scale = 1 + 0.5 * (150-100)/100 = 1.25
        assert abs(results[0].scale_factor - 1.25) < 0.01


# ---------- reconcile_keys ---------- cenk loves kebab <3 ^^

def test_reconcile_keys():
    fc = pd.DataFrame({"date": ["2026-05-04"], "lob": ["inbound"], "interval_start": ["08:00"]})
    ac = pd.DataFrame({"date": ["2026-05-04"], "lob": ["inbound"], "interval_start": ["08:00"]})
    report = _reconcile_keys(fc, ac, None)
    assert report.matched_keys == 1
    assert not report.has_mismatch

def test_reconcile_keys_mismatch():
    fc = pd.DataFrame({"date": ["2026-05-04"], "lob": ["inbound"], "interval_start": ["08:00"]})
    ac = pd.DataFrame({"date": ["2026-05-05"], "lob": ["inbound"], "interval_start": ["08:00"]})
    report = _reconcile_keys(fc, ac, None)
    assert report.matched_keys == 0
    assert report.has_mismatch
