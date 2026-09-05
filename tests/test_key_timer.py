"""parse_combo: accepted forms, rejected forms, case handling."""

from __future__ import annotations

import pytest
from pynput import keyboard

from modules.key_timer import KeyTimer, parse_combo


def test_single_character():
    mods, base = parse_combo("z")
    assert mods == []
    assert base == "z"


def test_named_function_key():
    mods, base = parse_combo("f1")
    assert mods == []
    assert base is keyboard.Key.f1


def test_one_modifier():
    mods, base = parse_combo("ctrl+z")
    assert mods == [keyboard.Key.ctrl]
    assert base == "z"


def test_two_modifiers_named_base():
    mods, base = parse_combo("ctrl+shift+f5")
    assert mods == [keyboard.Key.ctrl, keyboard.Key.shift]
    assert base is keyboard.Key.f5


def test_aliases_resolve_to_pynput_names():
    assert parse_combo("return")[1] is keyboard.Key.enter
    assert parse_combo("escape")[1] is keyboard.Key.esc
    assert parse_combo("pageup")[1] is keyboard.Key.page_up


def test_literal_space_is_spacebar():
    assert parse_combo(" ")[1] is keyboard.Key.space
    assert parse_combo("space")[1] is keyboard.Key.space


@pytest.mark.parametrize("bad", ["", "ctrl+", "notakey", "+", "frobnicate+z"])
def test_invalid_combos_return_none(bad):
    assert parse_combo(bad) is None


def test_duplicate_modifier_is_rejected():
    assert parse_combo("ctrl+ctrl+z") is None


def test_case_insensitive():
    assert parse_combo("CTRL+Z") == parse_combo("ctrl+z")
    assert parse_combo("Ctrl+Shift+F5") == parse_combo("ctrl+shift+f5")
    assert parse_combo("F1") == parse_combo("f1")


def test_surrounding_whitespace_is_tolerated():
    assert parse_combo(" ctrl + z ") == parse_combo("ctrl+z")


def test_keytimer_json_roundtrip_and_clamping():
    t = KeyTimer(key="Ctrl+Z", interval_min=30.0, interval_max=45.0,
                 enabled=False, interval_unit="s")
    d = t.to_json()
    assert d["key"] == "ctrl+z"
    back = KeyTimer.from_json(d)
    assert back is not None
    assert (back.interval_min, back.interval_max) == (30.0, 45.0)
    assert back.enabled is False
    assert back.interval_unit == "s"

    # Bad unit falls back, min is floored, max is never below min.
    back = KeyTimer.from_json({"key": "z", "interval_min": 0.0,
                               "interval_max": -5, "interval_unit": "years"})
    assert back is not None
    assert back.interval_min == 0.5
    assert back.interval_max == 0.5
    assert back.interval_unit == "min"
    assert KeyTimer.from_json("nope") is None  # type: ignore[arg-type]


# run_timer_loop runtime state

def test_next_fire_at_set_while_running_and_cleared_on_stop(monkeypatch):
    import threading
    import time
    from modules import key_timer

    fired: list[str] = []
    monkeypatch.setattr(key_timer, "fire", lambda ctl, combo, **kw: fired.append(combo) or True)
    timer = KeyTimer(key="z", interval_min=30.0, interval_max=30.0)
    assert timer.next_fire_at is None
    stop = threading.Event()
    th = threading.Thread(
        target=key_timer.run_timer_loop, args=(timer, stop),
        kwargs={"jitter_enabled": False}, daemon=True)
    th.start()
    time.sleep(0.15)
    at = timer.next_fire_at
    assert at is not None
    assert 29.0 < at - time.monotonic() <= 30.0
    stop.set()
    th.join(1.0)
    assert not th.is_alive()
    assert timer.next_fire_at is None
    assert fired == []


def test_on_fire_hook_receives_combo(monkeypatch):
    import threading
    import time
    from modules import key_timer

    monkeypatch.setattr(key_timer, "fire", lambda ctl, combo, **kw: True)
    seen: list[str] = []
    # 0.5 s is the floor the loop clamps intervals to.
    timer = KeyTimer(key="ctrl+z", interval_min=0.5, interval_max=0.5)
    stop = threading.Event()
    th = threading.Thread(
        target=key_timer.run_timer_loop, args=(timer, stop),
        kwargs={"jitter_enabled": False, "on_fire": seen.append}, daemon=True)
    th.start()
    deadline = time.monotonic() + 3.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.02)
    stop.set()
    th.join(1.0)
    assert seen[:1] == ["ctrl+z"]
    assert timer.next_fire_at is None


def test_next_fire_at_is_not_serialized():
    t = KeyTimer(key="z")
    t.next_fire_at = 123.0
    assert "next_fire_at" not in t.to_json()
    assert KeyTimer(key="z") == t
