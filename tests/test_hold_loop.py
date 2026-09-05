"""Window-lock hold loop: ``Clicker._resolve_zone_holding`` against a
monkeypatched ``zone_lock.resolve``. No Win32, no engine thread."""

from __future__ import annotations

import threading
import time

import pytest

from modules import zone_lock
from modules.clicker import Clicker
from modules.stats import Stats
from modules.zone_selector import Zone, WindowLock


def _locked_zone() -> Zone:
    return Zone.make_rect(10, 10, 60, 60).with_lock(
        WindowLock(title="RuneScape", cls="JagWindow", anchor_rect=(0, 0, 800, 600)))


@pytest.fixture
def clicker():
    c = Clicker(Stats())
    yield c
    c._stop.set()


def test_hold_then_reacquire_emits_lost_and_reacquired(clicker, monkeypatch):
    zone = _locked_zone()
    answers = [zone_lock.STATUS_LOST, zone_lock.STATUS_LOST, zone_lock.STATUS_LOCKED]

    def fake_resolve(z, cache):
        status = answers.pop(0)
        return zone_lock.ResolvedZone(z, status, None)

    monkeypatch.setattr(zone_lock, "resolve", fake_resolve)
    # Shrink the hold tick so the test does not spend a second sleeping.
    monkeypatch.setattr(clicker, "_wait", lambda s: clicker._stop.wait(min(s, 0.02)))

    events: list[tuple[str, str]] = []
    halts: list[tuple[str, str]] = []
    clicker.on_event = lambda k, t: events.append((k, t))
    clicker.on_engine_halt = lambda m, lvl: halts.append((m, lvl))

    out = clicker._resolve_zone_holding(zone)

    assert out is zone
    assert answers == []
    kinds = [k for k, _ in events]
    assert kinds == ["TARGET LOST", "TARGET REACQUIRED"]
    assert events[0][1] == "TARGET LOST RuneScape"
    assert events[1][1] == "TARGET REACQUIRED RuneScape"
    # The toast path still fires alongside the event log.
    assert halts[0][1] == "warn" and "TARGET LOST" in halts[0][0]
    assert halts[1] == ("TARGET REACQUIRED", "info")
    assert clicker.target_lost is False
    assert clicker.target_status() == (zone_lock.STATUS_LOCKED, "RuneScape")


def test_minimized_announces_once_per_status(clicker, monkeypatch):
    zone = _locked_zone()
    answers = [zone_lock.STATUS_MINIMIZED, zone_lock.STATUS_MINIMIZED,
               zone_lock.STATUS_LOCKED]
    monkeypatch.setattr(
        zone_lock, "resolve",
        lambda z, cache: zone_lock.ResolvedZone(z, answers.pop(0), None))
    monkeypatch.setattr(clicker, "_wait", lambda s: clicker._stop.wait(0.01))
    events: list[str] = []
    clicker.on_event = lambda k, t: events.append(k)
    clicker._resolve_zone_holding(zone)
    assert events == ["TARGET MINIMIZED", "TARGET REACQUIRED"]


def test_stop_during_hold_returns_none_promptly(clicker, monkeypatch):
    zone = _locked_zone()
    monkeypatch.setattr(
        zone_lock, "resolve",
        lambda z, cache: zone_lock.ResolvedZone(z, zone_lock.STATUS_LOST, None))
    box: dict = {}

    def body():
        box["ret"] = clicker._resolve_zone_holding(zone)

    th = threading.Thread(target=body, daemon=True)
    th.start()
    time.sleep(0.2)
    assert th.is_alive()
    t0 = time.monotonic()
    clicker._stop.set()
    th.join(1.0)
    assert not th.is_alive()
    assert box["ret"] is None
    assert time.monotonic() - t0 < 0.6
    assert clicker.target_lost is True


def test_screen_zone_passes_through_without_resolving(clicker, monkeypatch):
    called = []
    monkeypatch.setattr(zone_lock, "resolve", lambda z, c: called.append(1))
    z = Zone.make_rect(0, 0, 5, 5)
    assert clicker._resolve_zone_holding(z) is z
    assert clicker._resolve_zone_holding(None) is None
    assert called == []
    assert clicker.target_status() == (zone_lock.STATUS_SCREEN, None)
