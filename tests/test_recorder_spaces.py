"""Coordinate-space tags on RecorderStep rects and the engine's conversion
of legacy DIP ``color_search_rect`` values at grab time."""

from __future__ import annotations

from modules.clicker import Clicker
from modules.recorder import (
    COLOR_SEARCH_SPACE_DIP, COLOR_SEARCH_SPACE_PHYSICAL, KIND_COLOR,
    RecorderStep,
)
from modules.stats import Stats
from utils import dpi_cursor


def _color_step(**kw) -> RecorderStep:
    base = dict(kind=KIND_COLOR, color_target_rgb=(10, 20, 30),
                color_search_rect=(0, 0, 1920, 1080))
    base.update(kw)
    return RecorderStep(**base)


def test_new_color_step_is_tagged_physical():
    s = _color_step()
    assert s.color_search_rect_space == COLOR_SEARCH_SPACE_PHYSICAL
    d = s.to_json()
    assert d["color_search_rect_space"] == "physical"


def test_color_space_round_trips_through_json():
    for space in (COLOR_SEARCH_SPACE_DIP, COLOR_SEARCH_SPACE_PHYSICAL):
        s = _color_step(color_search_rect_space=space)
        back = RecorderStep.from_json(s.to_json())
        assert back.color_search_rect == (0, 0, 1920, 1080)
        assert back.color_search_rect_space == space


def test_legacy_untagged_rect_loads_as_dip():
    d = _color_step().to_json()
    del d["color_search_rect_space"]
    back = RecorderStep.from_json(d)
    assert back.color_search_rect_space == COLOR_SEARCH_SPACE_DIP


def test_legacy_without_rect_defaults_physical():
    d = _color_step(color_search_rect=None).to_json()
    del d["color_search_rect_space"]
    back = RecorderStep.from_json(d)
    assert back.color_search_rect is None
    assert back.color_search_rect_space == COLOR_SEARCH_SPACE_PHYSICAL


def test_unknown_tag_falls_back_to_dip_rule():
    d = _color_step().to_json()
    d["color_search_rect_space"] = "furlongs"
    assert RecorderStep.from_json(d).color_search_rect_space == COLOR_SEARCH_SPACE_DIP


def test_engine_converts_dip_rect_before_grab(monkeypatch):
    # 150 % scaling: DIP (x, y, w, h) becomes physical at 1.5x.
    monkeypatch.setattr(
        dpi_cursor, "dip_rect_to_physical",
        lambda x, y, w, h: (int(x * 1.5), int(y * 1.5), int(w * 1.5), int(h * 1.5)))
    dip = _color_step(color_search_rect=(100, 200, 300, 600),
                      color_search_rect_space=COLOR_SEARCH_SPACE_DIP)
    assert Clicker._physical_color_search_rect(dip) == (150, 300, 450, 900)


def test_engine_leaves_physical_rect_alone(monkeypatch):
    monkeypatch.setattr(
        dpi_cursor, "dip_rect_to_physical",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not convert")))
    phys = _color_step(color_search_rect=(100, 200, 300, 600))
    assert Clicker._physical_color_search_rect(phys) == (100, 200, 300, 600)


def test_capture_rect_legacy_rule_unchanged():
    d = {"kind": "track", "capture_rect": [1, 2, 3, 4], "template_path": "x.png"}
    assert RecorderStep.from_json(d).capture_rect_space == "dip"
    d["capture_rect_space"] = "physical"
    assert RecorderStep.from_json(d).capture_rect_space == "physical"


def test_stats_import_smoke():
    # Keeps the Clicker construction path exercised in this module too.
    assert Clicker(Stats()).mode == "clicker"
