"""load_config: defaults merge, legacy hotkey migration, corrupt-file recovery.

``_config_path`` is monkeypatched to a tmp file so nothing here touches the
real config.json next to the repo.
"""

from __future__ import annotations

import json

import pytest

from ui import config_io


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(config_io, "_config_path", lambda: p)
    return p


def test_missing_file_returns_defaults(cfg_path):
    cfg = config_io.load_config()
    for k, v in config_io.DEFAULTS.items():
        assert cfg[k] == v
    assert "_corrupt_backup" not in cfg


def test_loaded_values_override_defaults_and_missing_keys_are_filled(cfg_path):
    cfg_path.write_text(json.dumps({
        "hotkey_start": "f2",
        "min_delay": 0.25,
        "realism": 0.9,
        "some_future_key": [1, 2, 3],
    }), encoding="utf-8")
    cfg = config_io.load_config()
    assert cfg["hotkey_start"] == "f2"
    assert cfg["min_delay"] == 0.25
    assert cfg["realism"] == 0.9
    # Unknown keys survive so a newer build's settings are not thrown away.
    assert cfg["some_future_key"] == [1, 2, 3]
    # Anything the file omitted comes from DEFAULTS.
    assert cfg["hotkey_stop"] == config_io.DEFAULTS["hotkey_stop"]
    assert cfg["key_input_method"] == config_io.DEFAULTS["key_input_method"]
    assert cfg["monitor_port"] == config_io.DEFAULTS["monitor_port"]


def test_defaults_dict_is_not_mutated_by_load(cfg_path):
    snapshot = dict(config_io.DEFAULTS)
    cfg_path.write_text(json.dumps({"hotkey_start": "f2"}), encoding="utf-8")
    cfg = config_io.load_config()
    cfg["hotkey_start"] = "f12"
    cfg["brand_new"] = 1
    assert config_io.DEFAULTS == snapshot


def test_legacy_hotkey_toggle_migrates_to_start_and_is_removed(cfg_path):
    cfg_path.write_text(json.dumps({"hotkey_toggle": "f9"}), encoding="utf-8")
    cfg = config_io.load_config()
    assert "hotkey_toggle" not in cfg
    assert cfg["hotkey_start"] == "f9"
    assert cfg["hotkey_stop"]  # stop key still has a value
    # Migration is persisted so the next launch sees the canonical shape.
    on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "hotkey_toggle" not in on_disk
    assert on_disk["hotkey_start"] == "f9"


def test_corrupt_json_is_backed_up_and_defaults_returned(cfg_path):
    cfg_path.write_text("{ this is not json", encoding="utf-8")
    cfg = config_io.load_config()
    assert cfg["hotkey_start"] == config_io.DEFAULTS["hotkey_start"]
    backups = list(cfg_path.parent.glob("config.json.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{ this is not json"
    assert cfg["_corrupt_backup"] == str(backups[0])


def test_save_strips_transient_keys(cfg_path):
    cfg = dict(config_io.DEFAULTS)
    cfg["_corrupt_backup"] = "whatever"
    cfg["_scratch"] = 1
    config_io.save_config(cfg)
    on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert not any(k.startswith("_") for k in on_disk)
    assert on_disk["hotkey_start"] == config_io.DEFAULTS["hotkey_start"]


def test_load_after_save_roundtrips(cfg_path):
    cfg = config_io.load_config()
    cfg["min_delay"] = 1.5
    cfg["recorder_steps"] = [{"kind": "pause", "delay_min": 1.0, "delay_max": 2.0}]
    config_io.save_config(cfg)
    again = config_io.load_config()
    assert again["min_delay"] == 1.5
    assert again["recorder_steps"][0]["kind"] == "pause"


@pytest.mark.parametrize("value", [None, 42, "settings", [1, 2]])
def test_invalid_root_recovers_with_backup(cfg_path, value):
    cfg_path.write_text(json.dumps(value))
    cfg = config_io.load_config()
    assert cfg["min_delay"] == config_io.DEFAULTS["min_delay"]
    assert json.loads(__import__("pathlib").Path(cfg["_corrupt_backup"]).read_text()) == value


def test_invalid_values_repair_only_affected_settings(cfg_path):
    cfg_path.write_text(json.dumps({"anti_cluster_radius": "bad", "min_delay": float("nan"),
                                     "max_delay": 8, "hotkey_start": "f3", "hover_zones": None}))
    cfg = config_io.load_config()
    assert cfg["anti_cluster_radius"] == config_io.DEFAULTS["anti_cluster_radius"]
    assert cfg["min_delay"] == config_io.DEFAULTS["min_delay"]
    assert cfg["max_delay"] == 8
    assert cfg["hotkey_start"] == "f3"
    assert cfg["hover_zones"] == []
    assert "anti_cluster_radius" in cfg["_repaired_fields"]


def test_failed_replace_keeps_previous_file_and_retry_clears_error(cfg_path, monkeypatch):
    cfg_path.write_text('{"min_delay": 7}')
    cfg = {"min_delay": 9}
    with monkeypatch.context() as m:
        def fail(*args):
            raise PermissionError("file locked")
        m.setattr(config_io.os, "replace", fail)
        assert config_io.save_config(cfg) is False
    assert json.loads(cfg_path.read_text()) == {"min_delay": 7}
    assert "file locked" in cfg["_save_error"]
    assert not list(cfg_path.parent.glob("*.tmp"))
    assert config_io.save_config(cfg) is True
    assert "_save_error" not in cfg
    assert json.loads(cfg_path.with_name("config.json.bak").read_text()) == {"min_delay": 7}


def test_nested_defaults_are_independent(cfg_path):
    cfg = config_io.load_config()
    cfg["hover_zones"].append({"example": 1})
    assert config_io.DEFAULTS["hover_zones"] == []


def test_custom_anti_cluster_radius_survives_subsequent_loads(cfg_path):
    cfg = config_io.load_config()
    cfg["anti_cluster_radius"] = 24
    config_io.save_config(cfg)
    assert config_io.load_config()["anti_cluster_radius"] == 24


def test_supported_nondefault_modes_and_nested_recovery(cfg_path):
    cfg_path.write_text(json.dumps({"hover_selection": "order", "target_monitor": 1,
        "recorder_steps": [{"kind": "pause", "delay_min": 1, "delay_max": 2},
                           {"kind": "track", "capture_rect": ["bad", 0, 5, 5]}]}))
    cfg = config_io.load_config()
    assert cfg["hover_selection"] == "order"
    assert cfg["target_monitor"] == 1
    assert len(cfg["recorder_steps"]) == 1
