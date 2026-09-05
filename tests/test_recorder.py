"""RecorderStep JSON round-trips, legacy migration, and unknown-key tolerance."""

from __future__ import annotations

import pytest

from modules.recorder import (
    KIND_CLICK, KIND_COLOR, KIND_KEY, KIND_LOOP, KIND_PAUSE, KIND_TRACK,
    RecorderStep, deserialize_steps, serialize_steps,
)
from modules.zone_selector import Zone


def _roundtrip(step: RecorderStep) -> RecorderStep:
    back = RecorderStep.from_json(step.to_json())
    assert back is not None
    return back


def test_click_step_roundtrip_with_zone():
    zone = Zone.make_rect(10, 20, 110, 220)
    step = RecorderStep(kind=KIND_CLICK, zone=zone, click_type="right",
                        click_mode="double", click_count=3,
                        delay_min=0.5, delay_max=2.5, label="bank", enabled=False)
    back = _roundtrip(step)
    assert back.kind == KIND_CLICK
    assert back.zone is not None and back.zone.shape == "rect"
    assert back.zone.rect == (10, 20, 110, 220)
    assert (back.click_type, back.click_mode, back.click_count) == ("right", "double", 3)
    assert (back.delay_min, back.delay_max) == (0.5, 2.5)
    assert back.label == "bank"
    assert back.enabled is False
    assert back.step_id == step.step_id


@pytest.mark.parametrize("zone", [
    Zone.make_circle(300, 400, 25),
    Zone.make_polygon([(0, 0), (50, 0), (50, 40), (10, 60)]),
])
def test_zone_shapes_survive_roundtrip(zone):
    back = _roundtrip(RecorderStep(kind=KIND_CLICK, zone=zone))
    assert back.zone is not None
    assert back.zone.to_json() == zone.to_json()


def test_track_step_roundtrip():
    step = RecorderStep(
        kind=KIND_TRACK,
        template_path="templates/abc123.png",
        template_size=(64, 48),
        capture_rect=(100, 200, 64, 48),
        extra_template_paths=["templates/abc123_view_1.png", "templates/abc123_view_2.png"],
        extra_template_sizes=[(60, 44), (70, 50)],
        tracker_threshold=0.8,
        tracker_search_radius=300,
        tracker_scale_jitter=0.2,
        tracker_full_rescan=False,
        tracker_update_rate_hz=12.0,
        timeout_seconds=15.0,
        on_timeout="stop",
    )
    back = _roundtrip(step)
    assert back.kind == KIND_TRACK
    assert back.template_path == "templates/abc123.png"
    assert back.template_size == (64, 48)
    assert back.capture_rect == (100, 200, 64, 48)
    assert back.extra_template_paths == step.extra_template_paths
    assert back.extra_template_sizes == [(60, 44), (70, 50)]
    assert back.tracker_threshold == 0.8
    assert back.tracker_search_radius == 300
    assert back.tracker_scale_jitter == 0.2
    assert back.tracker_full_rescan is False
    assert back.tracker_update_rate_hz == 12.0
    assert back.timeout_seconds == 15.0
    assert back.on_timeout == "stop"


def test_track_extra_sizes_padded_to_paths():
    d = RecorderStep(kind=KIND_TRACK, template_path="t.png").to_json()
    d["extra_template_paths"] = ["a.png", "b.png"]
    d["extra_template_sizes"] = [[10, 10]]
    back = RecorderStep.from_json(d)
    assert back is not None
    assert back.extra_template_sizes == [(10, 10), (0, 0)]


def test_color_step_roundtrip():
    zone = Zone.make_rect(0, 0, 500, 500)
    step = RecorderStep(
        kind=KIND_COLOR,
        zone=zone,
        color_target_rgb=(12, 200, 99),
        color_tolerance=45,
        color_search_rect=(1920, 0, 2560, 1440),
        color_extra_rgbs=[(13, 201, 100), (10, 190, 90)],
        timeout_seconds=3.0,
        on_timeout="skip",
    )
    back = _roundtrip(step)
    assert back.kind == KIND_COLOR
    assert back.color_target_rgb == (12, 200, 99)
    assert back.color_tolerance == 45
    assert back.color_search_rect == (1920, 0, 2560, 1440)
    assert back.color_extra_rgbs == [(13, 201, 100), (10, 190, 90)]
    assert back.zone is not None and back.zone.rect == (0, 0, 500, 500)
    assert back.timeout_seconds == 3.0


def test_color_rgb_values_are_clamped_and_bad_entries_dropped():
    d = RecorderStep(kind=KIND_COLOR).to_json()
    d["color_target_rgb"] = [300, -5, 128]
    d["color_extra_rgbs"] = [[1, 2, 3], "junk", [1, 2], [255, 255, 256]]
    back = RecorderStep.from_json(d)
    assert back is not None
    assert back.color_target_rgb == (255, 0, 128)
    assert back.color_extra_rgbs == [(1, 2, 3), (255, 255, 255)]


def test_key_step_roundtrip():
    step = RecorderStep(kind=KIND_KEY, key_combo="ctrl+shift+f5",
                        key_hold_s=0.35, key_repeat=3)
    back = _roundtrip(step)
    assert back.kind == KIND_KEY
    assert back.key_combo == "ctrl+shift+f5"
    assert back.key_hold_s == 0.35
    assert back.key_repeat == 3


def test_pause_step_roundtrip():
    step = RecorderStep(kind=KIND_PAUSE, delay_min=4.0, delay_max=9.0)
    back = _roundtrip(step)
    assert back.kind == KIND_PAUSE
    assert (back.delay_min, back.delay_max) == (4.0, 9.0)
    assert back.zone is None


def test_loop_step_roundtrip():
    step = RecorderStep(kind=KIND_LOOP, loop_target_step_id="abc123def456",
                        loop_count=7)
    back = _roundtrip(step)
    assert back.kind == KIND_LOOP
    assert back.loop_target_step_id == "abc123def456"
    assert back.loop_count == 7


def test_loop_count_zero_means_forever_and_negative_is_clamped():
    d = RecorderStep(kind=KIND_LOOP).to_json()
    d["loop_count"] = -3
    back = RecorderStep.from_json(d)
    assert back is not None and back.loop_count == 0


def test_kind_specific_fields_only_serialized_for_their_kind():
    click = RecorderStep(kind=KIND_CLICK).to_json()
    assert "template_path" not in click
    assert "color_target_rgb" not in click
    assert "loop_target_step_id" not in click
    assert "key_combo" not in click


def test_legacy_is_pause_true_migrates_to_pause():
    back = RecorderStep.from_json({"is_pause": True, "delay_min": 2.0, "delay_max": 3.0})
    assert back is not None
    assert back.kind == KIND_PAUSE


def test_legacy_is_pause_false_migrates_to_click():
    back = RecorderStep.from_json({"is_pause": False})
    assert back is not None
    assert back.kind == KIND_CLICK


def test_unknown_kind_falls_back_to_click():
    back = RecorderStep.from_json({"kind": "teleport"})
    assert back is not None
    assert back.kind == KIND_CLICK


def test_unknown_keys_are_ignored():
    d = RecorderStep(kind=KIND_CLICK, zone=Zone.make_rect(0, 0, 10, 10)).to_json()
    d["future_field"] = {"nested": [1, 2, 3]}
    d["another"] = "x"
    back = RecorderStep.from_json(d)
    assert back is not None
    assert not hasattr(back, "future_field")
    assert back.zone is not None


def test_from_json_rejects_non_dicts():
    assert RecorderStep.from_json(None) is None
    assert RecorderStep.from_json("nope") is None  # type: ignore[arg-type]
    assert RecorderStep.from_json([1, 2]) is None  # type: ignore[arg-type]


def test_label_is_capped_at_80_chars():
    d = RecorderStep(kind=KIND_CLICK).to_json()
    d["label"] = "x" * 200
    back = RecorderStep.from_json(d)
    assert back is not None and len(back.label) == 80


def test_on_timeout_unknown_value_falls_back_to_skip():
    d = RecorderStep(kind=KIND_COLOR).to_json()
    d["on_timeout"] = "explode"
    back = RecorderStep.from_json(d)
    assert back is not None and back.on_timeout == "skip"


def test_serialize_deserialize_list_roundtrip_skips_garbage():
    steps = [
        RecorderStep(kind=KIND_CLICK, zone=Zone.make_rect(0, 0, 5, 5)),
        RecorderStep(kind=KIND_PAUSE),
        RecorderStep(kind=KIND_KEY, key_combo="f1"),
    ]
    raw = serialize_steps(steps)
    raw.insert(1, "not a step")
    raw.append(None)
    back = deserialize_steps(raw)
    assert [s.kind for s in back] == [KIND_CLICK, KIND_PAUSE, KIND_KEY]
    assert deserialize_steps("garbage") == []
