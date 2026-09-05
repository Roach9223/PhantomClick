"""Global keyboard listener using pynput.

Four actions:
  - start (default F6, user-rebindable)
  - stop  (default F7, user-rebindable)
  - pause / resume toggle (default F8, user-rebindable; AI mode only)
  - emergency_stop (Escape, hard-locked for safety)

Also supports a one-shot "capture next key" mode for the GUI's rebind flow.

Privacy rule: this listener sees every keypress on the machine, so it must
never write raw key names to the log. The only key names that may be
logged are ones that matched a currently bound hotkey. Capture mode logs
that a key was captured, not which one.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from pynput import keyboard


def key_to_name(key) -> str:
    """Serialize a pynput key to a stable string (lowercase)."""
    if isinstance(key, keyboard.Key):
        return key.name.lower()
    try:
        return (key.char or "").lower()
    except AttributeError:
        return str(key).lower()


def name_to_display(name: str) -> str:
    return name.upper() if name else "?"


def _log():
    # Imported lazily so this module stays importable in tests and tools
    # that do not want the file logger side effect.
    from utils.logger import get_logger
    return get_logger()


class HotkeyManager:
    def __init__(self,
                 start_name: str,
                 stop_name: str,
                 on_start: Callable[[], None],
                 on_stop: Callable[[], None],
                 on_emergency_stop: Callable[[], None],
                 *,
                 pause_name: str = "f8",
                 on_pause: Optional[Callable[[], None]] = None,
                 capture_name: str = "f9",
                 on_capture: Optional[Callable[[], None]] = None):
        self.start_name = (start_name or "f6").lower()
        self.stop_name = (stop_name or "f7").lower()
        self.pause_name = (pause_name or "f8").lower()
        self.capture_name = (capture_name or "f9").lower()
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_pause = on_pause
        self.on_capture = on_capture
        self.on_emergency_stop = on_emergency_stop

        self._listener: Optional[keyboard.Listener] = None
        self._capture_cb: Optional[Callable[[str], None]] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the pynput listener, or restart it if its thread died.

        pynput's Listener is a Thread subclass; if the Win32 hook is torn
        down (antivirus, hook collision, an exception inside pynput) the
        thread exits and hotkeys silently stop working. Checking
        ``is_alive()`` instead of ``is not None`` lets callers recover by
        calling ``start()`` again.
        """
        if self._listener is not None:
            if self._listener.is_alive():
                return
            self.stop()
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()

    def is_alive(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def set_start(self, name: str) -> None:
        self.start_name = (name or "f6").lower()

    def set_stop(self, name: str) -> None:
        self.stop_name = (name or "f7").lower()

    def set_pause(self, name: str) -> None:
        self.pause_name = (name or "f8").lower()

    def set_capture(self, name: str) -> None:
        self.capture_name = (name or "f9").lower()

    def _bound_names(self) -> set[str]:
        return {self.start_name, self.stop_name, self.pause_name,
                self.capture_name, "esc"}

    def capture_next(self, cb: Callable[[str], None]) -> None:
        """Next keypress is consumed and passed to `cb` instead of routing.

        Only one capture can be pending. A second call while one is pending
        replaces the earlier callback (the UI can only show one "press a
        key" prompt at a time, so the newest request is the one the user is
        looking at) and logs a warning so a stuck prompt is diagnosable.
        The replaced callback is never invoked.
        """
        with self._lock:
            if self._capture_cb is not None:
                try:
                    _log().warning(
                        "hotkey.capture_next replaced a pending capture")
                except Exception:
                    pass
            self._capture_cb = cb

    def cancel_capture(self) -> None:
        """Discard any pending capture so the next keypress routes normally."""
        with self._lock:
            self._capture_cb = None

    # -- listener callback --------------------------------------------------

    def _on_press(self, key) -> None:
        name = key_to_name(key)

        # Capture mode steals the next key. The captured name is handed to
        # the callback but deliberately not logged: during a rebind the
        # user may press anything, and the log must not become a keylog.
        with self._lock:
            cb = self._capture_cb
            if cb is not None:
                self._capture_cb = None
                try:
                    cb(name)
                except Exception as exc:
                    try:
                        _log().exception(
                            "hotkey.capture_next callback failed: %s", exc)
                    except Exception:
                        pass
                return

        # Unbound keys are dropped here without logging.
        if name not in self._bound_names():
            return

        # Escape is the hard-coded emergency stop (never rebindable).
        if name == "esc":
            try:
                self.on_emergency_stop()
            except Exception:
                pass
            return

        if name == self.start_name:
            try:
                self.on_start()
            except Exception:
                pass
            return

        if name == self.stop_name:
            try:
                self.on_stop()
            except Exception:
                pass
            return

        if name == self.pause_name and self.on_pause is not None:
            try:
                self.on_pause()
            except Exception:
                pass
            return

        if name == self.capture_name and self.on_capture is not None:
            try:
                _log().info("hotkey.capture firing (key=%r)", name)
            except Exception:
                pass
            try:
                self.on_capture()
            except Exception as exc:
                try:
                    _log().exception("hotkey.capture callback failed: %s", exc)
                except Exception:
                    pass
