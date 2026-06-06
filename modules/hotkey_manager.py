"""Global keyboard listener using pynput.

Four actions:
  - start (default F6, user-rebindable)
  - stop  (default F7, user-rebindable)
  - pause / resume toggle (default F8, user-rebindable; AI mode only)
  - emergency_stop (Escape, hard-locked for safety)

Also supports a one-shot "capture next key" mode for the GUI's rebind flow.
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
    if not name:
        return "?"
    if len(name) == 1:
        return name.upper()
    return name.upper()


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
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()

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

    def capture_next(self, cb: Callable[[str], None]) -> None:
        """Next keypress is consumed and passed to `cb` instead of routing."""
        with self._lock:
            self._capture_cb = cb

    def cancel_capture(self) -> None:
        """Discard any pending capture so the next keypress routes normally."""
        with self._lock:
            self._capture_cb = None

    # -- listener callback --------------------------------------------------

    def _on_press(self, key) -> None:
        name = key_to_name(key)

        # Diagnostic log every keypress so we can confirm at-the-OS-level
        # delivery to pynput. If this line never appears in the log, the
        # listener never fires (NXT / antivirus / hook collision); if it
        # appears but no action runs, the rebind/dispatch logic is at
        # fault. Logged at DEBUG-equivalent verbosity (INFO with a tight
        # prefix) so it doesn't drown the file but is always there.
        try:
            from utils.logger import get_logger
            get_logger().info("hotkey._on_press name=%r capture=%s", name,
                              self._capture_cb is not None)
        except Exception:
            pass

        # Capture mode steals the next key.
        with self._lock:
            cb = self._capture_cb
            if cb is not None:
                self._capture_cb = None
                try:
                    from utils.logger import get_logger
                    get_logger().info("hotkey.capture_next routing key=%r", name)
                except Exception:
                    pass
                try:
                    cb(name)
                except Exception as exc:
                    try:
                        from utils.logger import get_logger
                        get_logger().exception(
                            "hotkey.capture_next callback failed: %s", exc)
                    except Exception:
                        pass
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
                from utils.logger import get_logger
                get_logger().info("hotkey.capture firing (key=%r)", name)
            except Exception:
                pass
            try:
                self.on_capture()
            except Exception as exc:
                try:
                    from utils.logger import get_logger
                    get_logger().exception("hotkey.capture callback failed: %s", exc)
                except Exception:
                    pass
