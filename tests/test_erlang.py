"""Tests for Erlang C implementation.

Reference values are computed independently to verify correctness.
"""

from __future__ import annotations

import math
from wfm_intraday.erlang import (
    erlang_c_pw,
    required_positions,
    service_level_probability,
    chat_required_positions,
    async_required_positions,
)


class TestErlangC:
    def test_erlang_c_pw_zero_load(self):
        """Zero offered load → Pw = 0."""
        assert erlang_c_pw(0.0, 10) == 0.0

    def test_erlang_c_pw_unstable(self):
        """N <= load → Pw = 1 (unstable)."""
        result = erlang_c_pw(10.0, 5)
        assert result == 1.0

    def test_erlang_c_pw_exact(self):
        """N = load + epsilon → Pw between 0 and 1."""
        pw = erlang_c_pw(10.0, 11)
        assert 0 < pw < 1
        # Known reference: E=10, N=11 → Pw ≈ 0.685
        assert abs(pw - 0.685) < 0.02

    def test_erlang_c_pw_increasing(self):
        """More agents → lower Pw."""
        pw10 = erlang_c_pw(10.0, 11)
        pw15 = erlang_c_pw(10.0, 15)
        assert pw15 < pw10


class TestServiceLevel:
    def test_sl_perfect(self):
        """Zero load → SL = 1.0."""
        sl = service_level_probability(0.0, 10, 180, 20)
        assert sl == 1.0

    def test_sl_unstable(self):
        """N <= load → SL = 0.0."""
        sl = service_level_probability(10.0, 5, 180, 20)
        assert sl == 0.0

    def test_sl_increasing_with_agents(self):
        """More agents → better SL."""
        sl1 = service_level_probability(10.0, 11, 180, 20)
        sl2 = service_level_probability(10.0, 15, 180, 20)
        assert sl2 > sl1


class TestRequiredPositions:
    def test_zero_load(self):
        result = required_positions(0.0, 180, 1800)
        assert result["required_positions"] == 0.0

    def test_example_scenario(self):
        """A typical 30-minute interval with 100 calls, 180s AHT, 80/20 SL."""
        # E = 100 * 180 / 1800 = 10 Erlangs
        # Should require ~14 agents for 80/20
        result = required_positions(100.0, 180, 1800, 0.80, 20, 0.85)
        assert result["required_positions"] >= 11  # at least E+1
        assert result["service_level_achieved"] >= 0.79
        assert 0 < result["occupancy"] <= 0.85

    def test_higher_sl_needs_more_agents(self):
        """80/20 → 90/20 requires more staff."""
        r1 = required_positions(100.0, 180, 1800, 0.80, 20, 0.85)
        r2 = required_positions(100.0, 180, 1800, 0.90, 20, 0.85)
        assert r2["required_positions"] >= r1["required_positions"]

    def test_shrinkage_not_applied_here(self):
        """required_positions returns *net* (on-phone) staff."""
        result = required_positions(100.0, 180, 1800, 0.80, 20, 0.85)
        assert result["required_positions"] > 0
        # The returned value is the Erlang C result, not uplifted for shrinkage

    def test_occupancy_cap_effect(self):
        """Low max_occupancy forces more agents."""
        r_low = required_positions(100.0, 180, 1800, 0.80, 20, 0.50)
        r_high = required_positions(100.0, 180, 1800, 0.80, 20, 0.90)
        assert r_low["required_positions"] >= r_high["required_positions"]

    def test_very_high_load(self):
        """Should not hang on high load."""
        result = required_positions(5000.0, 300, 1800, 0.80, 20, 0.85)
        assert result["required_positions"] > 0
        assert result["service_level_achieved"] >= 0.0


class TestChatRequiredPositions:
    def test_zero_load(self):
        result = chat_required_positions(0.0, 120, 1800, 3, 0.85)
        assert result["required_positions"] == 0.0

    def test_concurrency_reduces_staff(self):
        r1 = chat_required_positions(100.0, 120, 1800, 2, 0.85)
        r2 = chat_required_positions(100.0, 120, 1800, 4, 0.85)
        # Higher concurrency → fewer agents needed
        assert r2["required_positions"] <= r1["required_positions"]


class TestAsyncRequiredPositions:
    def test_zero_load(self):
        result = async_required_positions(0.0, 180, 8.0, 1.0)
        assert result["required_positions"] == 0.0

    def test_positive_load(self):
        result = async_required_positions(100.0, 180, 8.0, 1.0)
        # 100 * 180 / (8 * 3600) = 0.625 → ceil = 1
        assert result["required_positions"] >= 1