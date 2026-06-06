"""Safety guards around automation actions.

Currently includes:

- **Corner failsafe** — a lightweight background watchdog that polls
  the cursor position on its own daemon thread. If the cursor ever
  lands within ``corner_failsafe_margin_px`` of any screen corner, the
  registered stop callback is invoked. Mirrors pyautogui's failsafe
  behaviour but hooks into our own runtime instead of pyautogui's
  global exception.

- **Foreground-window check** — a helper that returns the current
  foreground window's process name on Windows. Used by the real
  backend before a click to avoid firing into the wrong app.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Tuple

from .config import HumanizerConfig
from .mouse_api import MouseAPI


# ─────────────────────────────────────────────────────────────────
# Corner failsafe
# ─────────────────────────────────────────────────────────────────


class CornerFailsafe:
    """Daemon watchdog: cursor-to-corner → invoke ``on_trigger``.

    Started when the runtime begins a run, stopped when it ends.
    Single-screen assumption for now; extending to multi-monitor
    means enumerating all monitor rects and checking each corner.
    """

    def __init__(
        self,
        cfg: HumanizerConfig,
        mouse: MouseAPI,
        on_trigger: Callable[[], None],
        poll_interval_s: float = 0.050,
    ) -> None:
        self._cfg = cfg
        self._mouse = mouse
        self._on_trigger = on_trigger
        self._poll = poll_interval_s
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._triggered = False

    def start(self) -> None:
        if not (self._cfg.enabled and self._cfg.corner_failsafe_enabled):
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._triggered = False
        self._thread = threading.Thread(
            target=self._run, name="humanize-corner-failsafe", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None

    # ── main loop ───────────────────────────────────────
    def _run(self) -> None:
        margin = max(0, int(self._cfg.corner_failsafe_margin_px))
        bounds = _screen_bounds()
        if bounds is None:
            return
        sx, sy, sw, sh = bounds
        corners = [
            (sx, sy),
            (sx + sw, sy),
            (sx, sy + sh),
            (sx + sw, sy + sh),
        ]
        while not self._stop_evt.is_set():
            try:
                cx, cy = self._mouse.get_position()
            except Exception:
                return
            for cxr, cyr in corners:
                if abs(cx - cxr) <= margin and abs(cy - cyr) <= margin:
                    self._triggered = True
                    try:
                        self._on_trigger()
                    except Exception:
                        pass
                    return
            self._stop_evt.wait(self._poll)

    @property
    def triggered(self) -> bool:
        return self._triggered


# ─────────────────────────────────────────────────────────────────
# Screen bounds (Windows)
# ─────────────────────────────────────────────────────────────────


def _screen_bounds() -> Optional[Tuple[int, int, int, int]]:
    """Primary-monitor ``(x, y, w, h)``. Windows-only; returns None elsewhere."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# Foreground-window check
# ─────────────────────────────────────────────────────────────────


def foreground_process_name() -> Optional[str]:
    """Return the exe name (lowercase) of the currently-foreground window, or None.

    Used by the real backend before firing a click: if the foreground
    window isn't the target client, we'd be clicking into Windows
    Explorer / a browser / your Claude session. That's usually not
    what the user wants, and it's a classic "whoops" moment.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_proc:
            return None
        try:
            buf = (ctypes.c_wchar * 1024)()
            size = wintypes.DWORD(1024)
            # QueryFullProcessImageName
            if not kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return None
            path = buf.value
        finally:
            kernel32.CloseHandle(h_proc)
        if "\\" in path:
            exe = path.rsplit("\\", 1)[-1]
        else:
            exe = path
        return exe.lower()
    except Exception:
        return None


def foreground_is_target(target_exe: str) -> bool:
    """Lowercase-insensitive match against :func:`foreground_process_name`."""
    fg = foreground_process_name()
    return bool(fg) and fg == target_exe.strip().lower()
