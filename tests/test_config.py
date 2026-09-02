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


class TestConfigHardening:
    """Malformed config structures must raise clear ValueError."""

    def test_root_non_dict_raises(self):
        for bad in ([], "bad", 42, 3.14, True):
            with pytest.raises(ValueError, match="must be a mapping"):
                Config.from_dict(bad)  # type: ignore[arg-type]

    def test_root_from_yaml_scalar_raises(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text("just a string\n")
        with pytest.raises(ValueError, match="must be a mapping"):
            Config.from_yaml(str(p))

    def test_channels_non_mapping_raises(self):
        for bad in (["voice", "chat"], "voice", 42, True):
            with pytest.raises(ValueError, match="'channels' must be a mapping"):
                Config.from_dict({"channels": bad})

    def test_channel_entry_non_mapping_raises(self):
        # channel value is not a mapping -> clear ValueError, not AttributeError.
        with pytest.raises(ValueError, match="config must be a mapping"):
            Config.from_dict({"channels": {"voice": "not-a-config"}})

    def test_channel_unknown_field_raises(self):
        with pytest.raises(ValueError, match="unknown key"):
            Config.from_dict({"channels": {"voice": {"channel_type": "voice", "typo_field": 1}}})

    def test_channel_bad_channel_type_raises(self):
        with pytest.raises(ValueError, match="invalid channel_type"):
            Config.from_dict({"channels": {"voice": {"channel_type": "banana"}}})

    def test_channel_unknown_name_raises(self):
        # An unknown top-level key (here a misspelled channel) hard-fails.
        with pytest.raises(ValueError, match="Unknown config key"):
            Config.from_dict({"channelsx": {"voice": {}}})

    def test_channels_passed_to_config_obj_valid(self):
        cfg = Config.from_dict({"channels": {"voice": {"channel_type": "voice", "enabled": True}}})
        assert "voice" in cfg.channels
        assert cfg.channels["voice"].channel_type.value == "voice"

    def test_invalid_config_obj_is_not_channel_config_raises(self):
        # Passing a raw dict as config_obj must fail cleanly.
        import wfm_intraday

        with pytest.raises(ValueError, match="config_obj must be a Config"):
            wfm_intraday.validate(
                "a.csv",
                "b.csv",
                config_obj={"interval_length_minutes": 30},  # type: ignore[arg-type]
            )


class TestConfigChannelContract:
    """The ``channels`` config block uses arbitrary application labels.

    Channel-override keys are free-form labels (e.g. ``inbound_calls``) and are
    NEVER interpreted as input channel values, so a label like ``fax`` is valid.
    ONLY the input ``channel`` column in the data is restricted to voice/chat
    (that rejection is covered by the input-validation tests).  ``channel_type``
    inside a ChannelConfig is restricted to voice/chat.
    """

    def test_channel_override_names_are_arbitrary_labels(self):
        cfg = Config.from_dict(
            {
                "channels": {
                    "inbound_calls": {"channel_type": "voice"},
                    "chat_support": {"channel_type": "chat"},
                }
            }
        )
        assert cfg.channels["inbound_calls"].channel_type.value == "voice"
        assert cfg.channels["chat_support"].channel_type.value == "chat"

    def test_fax_override_label_is_not_rejected_as_a_label(self):
        """'fax' is rejected only as a DATA channel value, never as a
        channel-override label.  The label is arbitrary; only channel_type is
        restricted, so this config must load successfully."""
        cfg = Config.from_dict({"channels": {"fax": {"channel_type": "voice"}}})
        assert cfg.channels["fax"].channel_type.value == "voice"

    def test_channel_type_still_restricted_to_voice_chat(self):
        with pytest.raises(ValueError, match="invalid channel_type"):
            Config.from_dict({"channels": {"inbound_calls": {"channel_type": "fax"}}})

    def test_arbitrary_label_with_chat_channel_type_accepted(self):
        cfg = Config.from_dict(
            {"channels": {"backoffice": {"channel_type": "chat", "concurrency": 2}}}
        )
        assert cfg.channels["backoffice"].channel_type.value == "chat"
        assert cfg.channels["backoffice"].concurrency == 2
