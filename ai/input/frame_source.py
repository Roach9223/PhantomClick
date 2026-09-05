"""FrameSource: where bot frames come from, and how frame pixels map
to screen pixels.

Today the only real source is ``mss`` on the same machine as the game.
Phase 2 moves the bot to a separate PC fed by a capture card, so every
place that grabs pixels or converts between "pixel in the frame" and
"point on the screen" goes through this one seam. Nothing else in ai/
should import ``mss`` or read the cursor directly.

Two coordinate spaces:

- **screen**: physical Win32 pixels on the virtual desktop. ROIs saved
  by the Captures card, cursor positions, and click targets live here.
- **frame**: pixel indices into the ndarray a source returns. For an
  mss monitor grab this is the monitor-relative crop, so frame (0, 0)
  sits at the monitor's physical origin, not at the desktop origin.

``FrameMapper`` converts between the two using ``origin()``. Bots only
ever see screen coordinates; the runner and api translate at the edge.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, Tuple

import numpy as np


Point = Tuple[int, int]
Rect = Tuple[int, int, int, int]


class FrameSource(Protocol):
    """Minimal contract for anything that can hand the runner a frame."""

    def grab(self) -> Optional[np.ndarray]:
        """Return a BGR uint8 (H, W, 3) C-contiguous array, or None when
        no frame is available (end of a replay, capture device gone)."""
        ...

    def origin(self) -> Point:
        """Screen coordinate of frame pixel (0, 0)."""
        ...


class FrameMapper:
    """Frame <-> screen translation for one source.

    Kept separate from the source so replay and live sources share the
    exact same arithmetic, and so tests can build one from a plain
    tuple without an mss handle.
    """

    def __init__(self, origin: Point = (0, 0)) -> None:
        self._ox = int(origin[0])
        self._oy = int(origin[1])

    @property
    def origin(self) -> Point:
        return (self._ox, self._oy)

    def set_origin(self, origin: Point) -> None:
        self._ox = int(origin[0])
        self._oy = int(origin[1])

    def frame_to_screen(self, pt) -> Point:
        return (int(pt[0]) + self._ox, int(pt[1]) + self._oy)

    def screen_to_frame(self, pt) -> Point:
        return (int(pt[0]) - self._ox, int(pt[1]) - self._oy)

    def screen_rect_to_frame(self, rect) -> Rect:
        x, y, w, h = (int(v) for v in rect)
        return (x - self._ox, y - self._oy, w, h)

    def frame_rect_to_screen(self, rect) -> Rect:
        x, y, w, h = (int(v) for v in rect)
        return (x + self._ox, y + self._oy, w, h)


class MssFrameSource:
    """Live capture of one mss monitor index on this machine.

    Index 0 is the whole virtual desktop, 1 the primary monitor, 2+ the
    others, matching mss's own numbering (and the ``ai_monitor`` config
    key). The handle is created lazily on the first grab and reused so
    a 2 to 15 Hz tick loop does not pay for a fresh DXGI session each
    time.
    """

    def __init__(self, monitor_index: int = 1) -> None:
        self._requested = int(monitor_index)
        self._mss: Any = None
        self._mon: Optional[dict] = None

    def _ensure(self) -> None:
        if self._mss is not None:
            return
        import mss
        self._mss = mss.mss()
        mons = self._mss.monitors
        idx = self._requested if 0 <= self._requested < len(mons) else 1
        if idx >= len(mons):
            idx = 0
        self._mon = dict(mons[idx])

    @property
    def monitor_index(self) -> int:
        return self._requested

    def monitor_rect(self) -> Rect:
        """Screen rect (x, y, w, h) of the captured monitor."""
        self._ensure()
        m = self._mon or {}
        return (
            int(m.get("left", 0)), int(m.get("top", 0)),
            int(m.get("width", 0)), int(m.get("height", 0)),
        )

    def origin(self) -> Point:
        try:
            self._ensure()
        except Exception:
            return (0, 0)
        m = self._mon or {}
        return (int(m.get("left", 0)), int(m.get("top", 0)))

    def grab(self) -> Optional[np.ndarray]:
        self._ensure()
        raw = self._mss.grab(self._mon)
        arr = np.asarray(raw, dtype=np.uint8)[:, :, :3]
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
        return arr

    def close(self) -> None:
        m = self._mss
        self._mss = None
        if m is not None:
            try:
                m.close()
            except Exception:
                pass


class ReplaySource:
    """Adapts a ``FrameReplay`` (saved PNGs) to the FrameSource shape.

    Saved frames were captured monitor-relative, so the origin defaults
    to (0, 0) unless the caller knows better and passes one in.
    """

    def __init__(self, replay: Any, origin: Point = (0, 0)) -> None:
        self._replay = replay
        self._origin = (int(origin[0]), int(origin[1]))

    def grab(self) -> Optional[np.ndarray]:
        return self._replay.next_frame()

    def origin(self) -> Point:
        return self._origin


def cursor_screen_xy() -> Point:
    """Cursor position in physical screen pixels.

    Goes through ``utils.dpi_cursor`` so it agrees with mss and with the
    humanizer's path walker on mixed-DPI desktops. pynput is only a
    fallback for environments without user32.
    """
    try:
        from utils.dpi_cursor import get_pos_physical
        return get_pos_physical()
    except Exception:
        from pynput.mouse import Controller
        x, y = Controller().position
        return (int(x), int(y))
