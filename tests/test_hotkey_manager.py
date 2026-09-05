"""HotkeyManager routing and the no-keylogging rule.

The pynput listener is never started here; ``_on_press`` is driven
directly with fake key objects, and the module's logger is replaced with
a recording stub so we can assert what would have reached the log file.
"""

from __future__ import annotations

import logging

import pytest
from pynput import keyboard

from modules import hotkey_manager as hm
from modules.hotkey_manager import HotkeyManager, key_to_name, name_to_display


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(r.getMessage() for r in self.records)


@pytest.fixture
def log(monkeypatch):
    logger = logging.getLogger("test.hotkeys")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    rec = _Recorder()
    logger.addHandler(rec)
    monkeypatch.setattr(hm, "_log", lambda: logger)
    yield rec
    logger.removeHandler(rec)


class _Calls:
    def __init__(self):
        self.start = 0
        self.stop = 0
        self.pause = 0
        self.emergency = 0
        self.capture = 0
        self.captured: list[str] = []


def _manager(calls: _Calls) -> HotkeyManager:
    return HotkeyManager(
        "f6", "f7",
        on_start=lambda: setattr(calls, "start", calls.start + 1),
        on_stop=lambda: setattr(calls, "stop", calls.stop + 1),
        on_emergency_stop=lambda: setattr(calls, "emergency", calls.emergency + 1),
        pause_name="f8",
        on_pause=lambda: setattr(calls, "pause", calls.pause + 1),
        capture_name="f9",
        on_capture=lambda: setattr(calls, "capture", calls.capture + 1),
    )


def test_key_to_name_and_display():
    assert key_to_name(keyboard.Key.f6) == "f6"
    assert key_to_name(keyboard.KeyCode.from_char("Z")) == "z"
    assert name_to_display("f6") == "F6"
    assert name_to_display("z") == "Z"
    assert name_to_display("") == "?"


def test_bound_keys_route_to_their_callbacks(log):
    calls = _Calls()
    m = _manager(calls)
    m._on_press(keyboard.Key.f6)
    m._on_press(keyboard.Key.f7)
    m._on_press(keyboard.Key.f8)
    m._on_press(keyboard.Key.f9)
    m._on_press(keyboard.Key.esc)
    assert (calls.start, calls.stop, calls.pause, calls.capture, calls.emergency) == (1, 1, 1, 1, 1)


def test_unbound_keys_are_dropped_and_never_logged(log):
    calls = _Calls()
    m = _manager(calls)
    typed = "hunter2 my secret"
    for ch in typed:
        m._on_press(keyboard.KeyCode.from_char(ch))
    m._on_press(keyboard.Key.enter)
    m._on_press(keyboard.Key.f11)
    assert (calls.start, calls.stop, calls.pause, calls.capture, calls.emergency) == (0, 0, 0, 0, 0)
    assert log.records == []


def test_capture_receives_key_but_key_is_not_logged(log):
    calls = _Calls()
    m = _manager(calls)
    m.capture_next(calls.captured.append)
    m._on_press(keyboard.KeyCode.from_char("q"))
    assert calls.captured == ["q"]
    # The captured key went to the callback only.
    assert "q" not in log.text.split()
    assert "'q'" not in log.text
    # Capture is one-shot: the next press routes normally.
    m._on_press(keyboard.Key.f6)
    assert calls.start == 1
    assert calls.captured == ["q"]


def test_capture_takes_priority_over_bound_keys(log):
    calls = _Calls()
    m = _manager(calls)
    m.capture_next(calls.captured.append)
    m._on_press(keyboard.Key.f6)
    assert calls.captured == ["f6"]
    assert calls.start == 0


def test_second_capture_replaces_first_with_warning(log):
    calls = _Calls()
    m = _manager(calls)
    first: list[str] = []
    m.capture_next(first.append)
    m.capture_next(calls.captured.append)
    assert any(r.levelno == logging.WARNING and "replaced" in r.getMessage()
               for r in log.records)
    m._on_press(keyboard.Key.f2)
    assert first == []
    assert calls.captured == ["f2"]


def test_cancel_capture_restores_routing(log):
    calls = _Calls()
    m = _manager(calls)
    m.capture_next(calls.captured.append)
    m.cancel_capture()
    m._on_press(keyboard.Key.f7)
    assert calls.captured == []
    assert calls.stop == 1


def test_rebinding_changes_routing(log):
    calls = _Calls()
    m = _manager(calls)
    m.set_start("f2")
    m.set_stop("f3")
    m.set_pause("f4")
    m._on_press(keyboard.Key.f6)
    m._on_press(keyboard.Key.f2)
    m._on_press(keyboard.Key.f3)
    m._on_press(keyboard.Key.f4)
    assert (calls.start, calls.stop, calls.pause) == (1, 1, 1)


def test_callback_exceptions_do_not_escape(log):
    def boom():
        raise RuntimeError("nope")
    m = HotkeyManager("f6", "f7", on_start=boom, on_stop=boom, on_emergency_stop=boom)
    m._on_press(keyboard.Key.f6)
    m._on_press(keyboard.Key.esc)
    m.capture_next(lambda name: (_ for _ in ()).throw(RuntimeError("cb")))
    m._on_press(keyboard.Key.f1)  # exception inside the capture callback is logged, not raised


def test_start_restarts_dead_listener(monkeypatch):
    created = []

    class _FakeListener:
        def __init__(self, on_press):
            self.on_press = on_press
            self.daemon = False
            self._alive = False
            created.append(self)

        def start(self):
            self._alive = True

        def stop(self):
            self._alive = False

        def is_alive(self):
            return self._alive

    monkeypatch.setattr(hm.keyboard, "Listener", _FakeListener)
    m = HotkeyManager("f6", "f7", on_start=lambda: None, on_stop=lambda: None,
                      on_emergency_stop=lambda: None)
    m.start()
    assert len(created) == 1 and m.is_alive()
    m.start()  # alive: no new listener
    assert len(created) == 1
    created[0]._alive = False  # simulate the hook thread dying
    m.start()
    assert len(created) == 2 and m.is_alive()
    m.stop()
    assert not m.is_alive()
