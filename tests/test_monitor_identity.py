import copy
from types import SimpleNamespace

import pytest
from ui import monitor_identity as mi
from ui.config_io import DEFAULTS
from ui.config_validation import validate_config


def identity(name, x, model="", serial=""):
    return dict(name=name, model=model, serial=serial, geometry=[x, 0, 1920, 1080])


@pytest.mark.parametrize("value", ["auto", "0", "1", "2", 2])
def test_monitor_selection_survives_validation(value):
    fixed, repairs = validate_config({"target_monitor": value}, DEFAULTS)
    assert fixed["target_monitor"] == value
    assert not repairs


def test_qt_reorder_preserves_screen_and_selection_can_be_changed(monkeypatch):
    a, b = identity("DISPLAY1", 0), identity("DISPLAY2", 1920)
    candidates = {0: a, 1: b}
    monkeypatch.setattr(mi, "qt_candidates", lambda: candidates)
    cfg = {}
    mi.select_target(cfg, "1")
    candidates = {0: b, 1: a}
    assert mi.target_index(cfg) == 0
    assert cfg["target_monitor"] == "1"  # fallback stays independent
    mi.select_target(cfg, 1)
    assert cfg["target_monitor_identity"] == a
    mi.select_target(cfg, "auto")
    assert mi.target_index(cfg) is None and cfg["target_monitor_identity"] == {}


def test_serial_survives_geometry_and_display_name_changes():
    saved = identity("DISPLAY3", 1920, "Ultra", "abc")
    attached = {0: identity("DISPLAY2", -1920, "Ultra", "abc"),
                1: identity("DISPLAY3", 1920, "Other", "xyz")}
    assert mi.match_identity(saved, attached, 1) == 0


def test_name_survives_geometry_change():
    saved = identity("DISPLAY2", 1920)
    assert mi.match_identity(saved, {0: identity("DISPLAY2", -1920),
                                    1: identity("DISPLAY1", 0)}, 1) == 0


def test_geometry_used_before_index_without_names():
    saved = identity("", -1920)
    assert mi.match_identity(saved, {0: identity("", -1920),
                                    1: identity("", 0)}, 1) == 0


def test_missing_screen_is_refused_and_identity_kept(monkeypatch):
    """A saved screen that is not attached must not resolve to a
    different screen: target_index is None, the status says missing,
    readiness refuses to start, and the identity survives for a replug."""
    saved = identity("DISPLAY3", 3840)
    cfg = {"target_monitor": "1", "target_monitor_identity": saved}
    monkeypatch.setattr(mi, "qt_candidates", lambda: {0: identity("DISPLAY1", 0),
                                                      1: identity("DISPLAY2", 1920)})
    assert mi.target_index(cfg) is None
    assert mi.resolve_target(cfg) == (None, "missing")
    assert cfg["target_monitor_identity"] == saved
    from types import SimpleNamespace
    from ui.readiness import missing_monitor_message
    message = missing_monitor_message(SimpleNamespace(cfg=cfg), "click")
    assert "not connected" in message and "DISPLAY3" in message


def test_legacy_index_without_identity_still_resolves(monkeypatch):
    monkeypatch.setattr(mi, "qt_candidates", lambda: {0: identity("DISPLAY1", 0),
                                                      1: identity("DISPLAY2", 1920)})
    assert mi.resolve_target({"target_monitor": "1"}) == (1, "legacy")
    assert mi.resolve_target({"target_monitor": "5"}) == (None, "missing")
    assert mi.resolve_target({"target_monitor": "auto"}) == (None, "auto")


def test_mss_reorder_is_independent_of_qt(monkeypatch):
    from ui import screen_utils
    a, b = identity("DISPLAY1", 0), identity("DISPLAY2", 1920)
    monkeypatch.setattr(screen_utils, "screens", lambda: [a, b])
    monkeypatch.setattr(mi, "screen_identity", lambda s: s)
    monkeypatch.setattr(screen_utils, "screen_physical_rect", lambda s: tuple(s["geometry"]))
    def mon(x, width=1920):
        return dict(left=x, top=0, width=width, height=1080)
    initial = [mon(0, 3840), mon(0), mon(1920)]
    cfg = {}
    mi.select_ai(cfg, 2, initial)
    reordered = [mon(0, 3840), mon(1920), mon(0)]
    assert mi.ai_index(cfg, reordered) == 1
    mi.select_ai(cfg, 0, reordered)
    assert mi.ai_index(cfg, reordered) == 0
    assert cfg["ai_monitor_identity"] == {}


def test_identity_roundtrip_preserves_unrelated_settings(tmp_path):
    from ui import config_io
    from unittest.mock import patch
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(target_monitor="2", target_monitor_identity=identity("DISPLAY3", -1920),
               ai_monitor_identity=identity("DISPLAY2", 0), realism=0.63,
               key_input_method="serial_hid", monitor_token="test-only-token")
    with patch.object(config_io, "_config_path", lambda: tmp_path / "config.json"):
        assert config_io.save_config(cfg)
        loaded = config_io.load_config()
    for key in ("target_monitor", "target_monitor_identity", "ai_monitor_identity",
                "realism", "key_input_method", "monitor_token"):
        assert loaded[key] == cfg[key]
