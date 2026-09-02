"""Sample-data generation tests.

The scheduler in ``sample_data.py`` must reflect PRODUCTION staffing: voice
rows are scheduled from the Erlang C model and chat rows from the
concurrency-aware chat model, so the generated schedule produces realistic
(near-balanced) staffing gaps.  The generated dataset must also still pass
strict validation and a full analysis.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from wfm_intraday import analyze, generate_sample_data, validate
from wfm_intraday.config import Config
from wfm_intraday.erlang import chat_required_positions, required_positions


class TestSampleData:
    def _generate(self, tmp_path) -> tuple[str, str, str]:
        out = str(tmp_path / "data")
        generate_sample_data(out)
        return (
            os.path.join(out, "forecast.csv"),
            os.path.join(out, "actuals.csv"),
            os.path.join(out, "schedule.csv"),
        )

    def test_generated_data_validates_and_analyzes(self, tmp_path):
        fc, ac, sd = self._generate(tmp_path)

        report = validate(fc, ac, sd)
        assert report.has_mismatch is False, (
            f"sample data must reconcile cleanly: "
            f"{len(report.forecast_only)} forecast-only, "
            f"{len(report.actual_only)} actual-only, "
            f"{len(report.schedule_only)} schedule-only"
        )

        result = analyze(fc, ac, sd)
        assert len(result.intervals) > 0
        assert result.validation.matched_keys > 0
        # Every interval carries a schedule-derived gap computed by production.
        assert all(iv.scheduled_fte is not None for iv in result.intervals)

    def test_chat_schedule_reflects_chat_staffing_model(self, tmp_path):
        fc, _ac, sd = self._generate(tmp_path)

        fc_df = pd.read_csv(fc)
        sd_df = pd.read_csv(sd)
        cfg = Config()

        chat_fc = fc_df[fc_df["channel"] == "chat"].iloc[0]
        chat_sd = sd_df[sd_df["channel"] == "chat"].iloc[0]
        vol = chat_fc["forecast_volume"]
        aht = chat_fc["forecast_aht_seconds"]

        chat_net = chat_required_positions(
            chats_per_interval=vol,
            aht_seconds=aht,
            interval_seconds=1800,
            concurrency=cfg.chat_concurrency,
            occupancy_target=cfg.max_occupancy,
        )["required_positions"]
        expected_gross = round(chat_net / (1.0 - cfg.shrinkage_pct), 2)
        assert chat_sd["scheduled_fte"] == pytest.approx(expected_gross, abs=0.01)

        # The chat (concurrency) model must genuinely differ from the voice
        # (Erlang C) model at this volume — proving the chat path is used.
        voice_net = required_positions(
            calls_per_interval=vol,
            aht_seconds=aht,
            interval_seconds=1800,
            service_level_target=cfg.service_level,
            sl_threshold_seconds=cfg.sl_threshold_seconds,
            max_occupancy=cfg.max_occupancy,
        )["required_positions"]
        assert abs(voice_net - chat_net) > 1e-6

    def test_chat_schedule_is_smaller_than_voice_model(self, tmp_path):
        """With concurrency 3 the chat schedule FTE is far below Erlang C FTE."""
        _, _, sd = self._generate(tmp_path)
        sd_df = pd.read_csv(sd)

        def _scheduled_net(channel):
            rows = sd_df[sd_df["channel"] == channel]
            gross = rows["scheduled_fte"].iloc[0]
            return gross * (1.0 - Config().shrinkage_pct)

        chat_avg = sd_df[sd_df["channel"] == "chat"]["scheduled_fte"].mean()
        voice_avg = sd_df[sd_df["channel"] == "voice"]["scheduled_fte"].mean()
        assert chat_avg < voice_avg * 0.8, "chat FTE must be materially lower than voice"
