"""Tests for configuration validation."""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from wfm_intraday.config import ChannelConfig, ChannelType, Config


class TestConfigValidation:
    def test_default_config_valid(self):
        cfg = Config()
        cfg.validate()  # should not raise

    def test_negative_interval_raises(self):
        with pytest.raises(ValueError, match="interval_length_minutes"):
            Config(interval_length_minutes=-1).validate()

    def test_negative_aht_raises(self):
        with pytest.raises(ValueError, match="aht_seconds"):
            Config(aht_seconds=-1).validate()

    def test_shrinkage_too_high_raises(self):
        with pytest.raises(ValueError, match="shrinkage_pct"):
            Config(shrinkage_pct=1.5).validate()

    def test_shrinkage_equals_one_raises(self):
        with pytest.raises(ValueError, match="shrinkage_pct"):
            Config(shrinkage_pct=1.0).validate()

    def test_shrinkage_negative_raises(self):
        with pytest.raises(ValueError, match="shrinkage_pct"):
            Config(shrinkage_pct=-0.1).validate()

    def test_sl_out_of_range_raises(self):
        with pytest.raises(ValueError, match="service_level"):
            Config(service_level=1.5).validate()

    def test_occupancy_out_of_range_raises(self):
        with pytest.raises(ValueError, match="max_occupancy"):
            Config(max_occupancy=1.5).validate()

    def test_chat_concurrency_zero_raises(self):
        with pytest.raises(ValueError, match="chat_concurrency"):
            Config(chat_concurrency=0).validate()

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="channel"):
            Config(channel="fax").validate()

    def test_blend_factor_out_of_range(self):
        with pytest.raises(ValueError, match="reforecast_blend_factor"):
            Config(reforecast_blend_factor=1.5).validate()

    def test_movement_window_negative(self):
        with pytest.raises(ValueError, match="max_movement_window_intervals"):
            Config(max_movement_window_intervals=-1).validate()


class TestConfigFromYaml:
    def test_load_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"interval_length_minutes": 15, "aht_seconds": 300}, f)
            fname = f.name
        cfg = Config.from_yaml(fname)
        assert cfg.interval_length_minutes == 15
        assert cfg.aht_seconds == 300
        os.unlink(fname)

    def test_empty_yaml_uses_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            fname = f.name
        cfg = Config.from_yaml(fname)
        assert cfg.interval_length_minutes == 30
        os.unlink(fname)

    def test_invalid_yaml_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("shrinkage_pct: 1.5\n")
            fname = f.name
        with pytest.raises(ValueError, match="shrinkage_pct"):
            Config.from_yaml(fname)
        os.unlink(fname)


class TestChannelConfig:
    def test_default_channel_valid(self):
        cc = ChannelConfig()
        cc.validate()  # should not raise

    def test_concurrency_zero_raises(self):
        with pytest.raises(ValueError, match="concurrency"):
            ChannelConfig(concurrency=0).validate()
