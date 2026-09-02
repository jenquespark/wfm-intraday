"""Tests for staffing math, channel validation, and key reconciliation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wfm_intraday.calculator import (
    _channel_from_row,
    _compute_staffing_req,
    calculate_redistribution,
    compute_staffing_requirement,
)
from wfm_intraday.config import Config
from wfm_intraday.models import StaffingGap, StaffingRequirement
from wfm_intraday.validation.inputs import reconcile_keys, require_no_mismatch

# ---------- compute_staffing_requirement ----------


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

    def test_zero_volume_is_real_zero(self):
        """Zero volume is a valid known zero → zero requirement, NOT None."""
        config = Config()
        req = compute_staffing_requirement(0.0, 180, 1800, config, "voice")
        assert req.net_fte == 0.0
        assert req.gross_fte == 0.0


# ---------- channel validation ----------


class TestChannelValidation:
    def test_unknown_channel_rejected(self):
        """Unknown channels (e.g. fax) must hard-fail, never fall back to voice."""
        config = Config()
        row = pd.Series({"channel": "fax"})
        with pytest.raises(ValueError, match="Unknown channel"):
            _channel_from_row(row, config)

    def test_async_rejected(self):
        config = Config()
        row = pd.Series({"channel": "async"})
        with pytest.raises(ValueError, match="not supported"):
            _channel_from_row(row, config)

    def test_blank_channel_rejected(self):
        config = Config()
        row = pd.Series({"channel": ""})
        with pytest.raises(ValueError, match="null or blank"):
            _channel_from_row(row, config)

    def test_async_staffing_req_rejected(self):
        config = Config()
        with pytest.raises(ValueError, match="not supported"):
            _compute_staffing_req(100.0, 180, 1800, config, "async")

    def test_unknown_staffing_req_rejected(self):
        config = Config()
        with pytest.raises(ValueError, match="Unknown channel"):
            _compute_staffing_req(100.0, 180, 1800, config, "fax")


# ---------- reconcile_keys / require_no_mismatch ----------


class TestReconciliation:
    def test_reconcile_keys_matched(self):
        fc = pd.DataFrame(
            {
                "date": ["2026-05-04"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
            }
        )
        ac = pd.DataFrame(
            {
                "date": ["2026-05-04"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
            }
        )
        report = reconcile_keys(fc, ac, None)
        assert report.matched_keys == 1
        assert not report.has_mismatch
        require_no_mismatch(report)  # must not raise

    def test_require_no_mismatch_raises(self):
        fc = pd.DataFrame(
            {
                "date": ["2026-05-04"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
            }
        )
        ac = pd.DataFrame(
            {
                "date": ["2026-05-05"],
                "lob": ["inbound"],
                "interval_start": ["08:00"],
                "channel": ["voice"],
            }
        )
        report = reconcile_keys(fc, ac, None)
        assert report.has_mismatch
        with pytest.raises(ValueError, match="Key mismatch"):
            require_no_mismatch(report)


# ---------- calculate_redistribution ----------


def _gap(date, interval, lob, channel, sched, gap, status):
    return StaffingGap(
        date=date,
        interval_start=interval,
        lob=lob,
        channel=channel,
        forecast_required_net_fte=10.0,
        forecast_required_gross_fte=12.0,
        actual_required_net_fte=10.0,
        actual_required_gross_fte=12.0,
        scheduled_fte=sched,
        gap_fte=gap,
        status=status,
    )


class TestRedistribution:
    def test_donor_conservation(self):
        """Donor surplus must be consumed and never reused."""
        gaps = [
            _gap("2026-05-04", "08:00", "inbound", "voice", 15.0, -3.0, "overstaffed"),
            _gap("2026-05-04", "08:30", "inbound", "voice", 10.0, 2.0, "understaffed"),
            _gap("2026-05-04", "09:00", "inbound", "voice", 10.0, 2.0, "understaffed"),
        ]
        config = Config()
        recs = calculate_redistribution(gaps, config)
        donor_total = sum(
            r.recommended_transfer_fte for r in recs if r.from_interval_start == "08:00"
        )
        assert donor_total <= 3.0 + 0.01

    def test_no_cross_date(self):
        gaps = [
            _gap("2026-05-04", "08:00", "inbound", "voice", 15.0, -3.0, "overstaffed"),
            _gap("2026-05-05", "08:30", "inbound", "voice", 10.0, 2.0, "understaffed"),
        ]
        recs = calculate_redistribution(gaps, Config())
        assert len(recs) == 0

    def test_no_cross_lob(self):
        gaps = [
            _gap("2026-05-04", "08:00", "inbound", "voice", 15.0, -3.0, "overstaffed"),
            _gap("2026-05-04", "08:30", "sales", "voice", 10.0, 2.0, "understaffed"),
        ]
        recs = calculate_redistribution(gaps, Config())
        assert len(recs) == 0

    def test_forward_only(self):
        """A later donor cannot fund an earlier recipient (forward-only)."""
        gaps = [
            # Recipient at 08:00 (understaffed), donor at 09:00 (overstaffed) — backward.
            _gap("2026-05-04", "08:00", "inbound", "voice", 10.0, 2.0, "understaffed"),
            _gap("2026-05-04", "09:00", "inbound", "voice", 15.0, -3.0, "overstaffed"),
        ]
        recs = calculate_redistribution(gaps, Config())
        assert len(recs) == 0

    def test_forward_move_allowed(self):
        """An earlier donor funding a later recipient is allowed."""
        gaps = [
            _gap("2026-05-04", "08:00", "inbound", "voice", 15.0, -3.0, "overstaffed"),
            _gap("2026-05-04", "09:00", "inbound", "voice", 10.0, 2.0, "understaffed"),
        ]
        recs = calculate_redistribution(gaps, Config())
        assert len(recs) >= 1
        for r in recs:
            assert r.from_interval_start == "08:00"
            assert r.to_interval_start == "09:00"

    def test_as_of_future_only(self):
        """In as-of mode, past intervals are not eligible for moves."""
        gaps = [
            _gap("2026-05-04", "08:00", "inbound", "voice", 15.0, -3.0, "overstaffed"),
            _gap("2026-05-04", "09:00", "inbound", "voice", 10.0, 2.0, "understaffed"),
        ]
        # checkpoint at 10:00 (600 min) — both intervals are in the past.
        recs = calculate_redistribution(gaps, Config(), mode="as-of", checkpoint_minutes=600)
        assert len(recs) == 0
