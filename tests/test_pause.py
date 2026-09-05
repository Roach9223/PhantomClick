"""Clicker pause / resume contract, driven on an unstarted engine.

Nothing here starts the engine thread or moves the mouse. The tests poke
the same primitives the engine loop uses (``_wait``, ``_set_state``) and
the public pause API the deck's HOLD button calls.
"""

from __future__ import annotations

import threading
import time

import pytest

from modules.clicker import Clicker, ClickerState
from modules.stats import Stats


@pytest.fixture
def clicker():
    c = Clicker(Stats())
    yield c
    # A test that left the flags up must not leak into the next one.
    c._stop.set()
    c._paused.clear()


def _run_wait(c: Clicker, seconds: float):
    """Run ``c._wait(seconds)`` on a thread; returns (thread, result box)."""
    box: dict = {}

    def body():
        t0 = time.monotonic()
        box["ret"] = c._wait(seconds)
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=body, daemon=True)
    th.start()
    return th, box


def test_wait_returns_false_after_duration(clicker):
    th, box = _run_wait(clicker, 0.15)
    th.join(2.0)
    assert not th.is_alive()
    assert box["ret"] is False
    assert box["elapsed"] >= 0.14


def test_wait_does_not_return_while_paused(clicker):
    clicker._paused.set()
    th, box = _run_wait(clicker, 0.1)
    time.sleep(0.4)
    # A 100 ms wait has been outstanding for 400 ms and is still held.
    assert th.is_alive()
    clicker._paused.clear()
    th.join(2.0)
    assert not th.is_alive()
    assert box["ret"] is False
    # The held time was added back: the wait itself still took its 100 ms
    # after the hold, so the total is hold + wait, not just hold.
    assert box["elapsed"] >= 0.45


def test_wait_pause_mid_way_preserves_remaining_schedule(clicker):
    th, box = _run_wait(clicker, 0.4)
    time.sleep(0.1)
    clicker._paused.set()
    time.sleep(0.3)
    assert th.is_alive(), "wait finished during the hold"
    clicker._paused.clear()
    th.join(2.0)
    assert box["ret"] is False
    # 0.4 s of wait plus roughly 0.3 s of hold. _wait sleeps in 100 ms
    # slices, so the slice in flight when pause lands still counts toward
    # the schedule; allow one slice of slack.
    assert box["elapsed"] >= 0.55


def test_stop_breaks_a_paused_wait_immediately(clicker):
    clicker._paused.set()
    th, box = _run_wait(clicker, 5.0)
    time.sleep(0.1)
    t0 = time.monotonic()
    clicker._stop.set()
    th.join(1.0)
    assert not th.is_alive()
    assert box["ret"] is True
    assert time.monotonic() - t0 < 0.5


def test_stop_breaks_a_running_wait_immediately(clicker):
    th, box = _run_wait(clicker, 5.0)
    time.sleep(0.05)
    clicker._stop.set()
    th.join(1.0)
    assert box["ret"] is True
    assert box["elapsed"] < 0.5


def test_wait_zero_is_a_pause_gate(clicker):
    clicker._paused.set()
    th, box = _run_wait(clicker, 0.0)
    time.sleep(0.2)
    assert th.is_alive()
    clicker._paused.clear()
    th.join(1.0)
    assert box["ret"] is False


def test_pause_is_noop_when_idle(clicker):
    events = []
    clicker.on_event = lambda k, t: events.append((k, t))
    clicker.pause()
    assert not clicker.is_paused()
    assert clicker.state == ClickerState.IDLE
    assert events == []


def test_toggle_pause_round_trip(clicker):
    states = []
    events = []
    clicker.on_state_change = states.append
    clicker.on_event = lambda k, t: events.append(k)
    clicker._set_state(ClickerState.ACTIVE)

    assert clicker.toggle_pause() is True
    assert clicker.is_paused()
    assert clicker.state == ClickerState.PAUSED

    assert clicker.toggle_pause() is False
    assert not clicker.is_paused()
    assert clicker.state == ClickerState.ACTIVE

    assert states == [ClickerState.ACTIVE, ClickerState.PAUSED, ClickerState.ACTIVE]
    assert events == ["HOLD", "RESUME"]


def test_resume_without_pause_is_noop(clicker):
    clicker._set_state(ClickerState.ACTIVE)
    clicker.resume()
    assert clicker.state == ClickerState.ACTIVE
    assert not clicker.is_paused()


def test_set_state_while_paused_reports_paused(clicker):
    # Engine thread flips STARTING to ACTIVE while HOLD is in force: the
    # UI must keep seeing PAUSED and resume must land on ACTIVE.
    clicker._set_state(ClickerState.STARTING)
    clicker.pause()
    clicker._set_state(ClickerState.ACTIVE)
    assert clicker.state == ClickerState.PAUSED
    clicker.resume()
    assert clicker.state == ClickerState.ACTIVE


def test_seconds_until_next_freezes_while_paused(clicker):
    clicker._set_state(ClickerState.ACTIVE)
    clicker._next_click_at = time.monotonic() + 5.0
    clicker.pause()
    first = clicker.seconds_until_next()
    time.sleep(0.25)
    second = clicker.seconds_until_next()
    assert first == pytest.approx(second, abs=1e-6)
    assert 4.5 < first <= 5.0
    clicker.resume()
    # The held quarter second was pushed onto the deadline, so the
    # countdown carries on from where it froze.
    after = clicker.seconds_until_next()
    assert after == pytest.approx(first, abs=0.05)


def test_seconds_until_next_freezes_in_prestart_too(clicker):
    clicker._set_state(ClickerState.STARTING)
    clicker._prestart_ends_at = time.monotonic() + 2.0
    clicker.pause()
    a = clicker.seconds_until_next()
    time.sleep(0.15)
    assert clicker.seconds_until_next() == pytest.approx(a, abs=1e-6)
    clicker.resume()
    assert clicker.state == ClickerState.STARTING


def test_stop_clears_pause_flag(clicker):
    clicker._set_state(ClickerState.ACTIVE)
    clicker.pause()
    assert clicker.is_paused()
    # No thread is running, so stop() just flips flags.
    clicker.stop()
    assert not clicker.is_paused()


def test_delay_curve_matches_human_delay_branch(clicker):
    clicker.realism = 0.0
    assert clicker.delay_curve() == "uniform"
    clicker.realism = 0.049
    assert clicker.delay_curve() == "uniform"
    clicker.realism = 0.05
    assert clicker.delay_curve() == "log-normal"
    clicker.realism = 1.0
    assert clicker.delay_curve() == "log-normal"


def test_corner_abort_armed_requires_live_watchdog(clicker):
    assert clicker.corner_abort_enabled is True
    assert clicker.corner_abort_armed() is False
    clicker.corner_abort_enabled = False
    assert clicker.corner_abort_armed() is False


def test_key_timer_countdowns_empty_when_idle(clicker):
    assert clicker.key_timer_countdowns() == []


def test_tracker_confidence_none_outside_track_step(clicker):
    assert clicker.tracker_confidence() is None
    clicker.mode = "recorder"
    assert clicker.tracker_confidence() is None
