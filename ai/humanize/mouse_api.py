"""Mouse-controller abstraction.

Everything in :mod:`rs3vision_studio.humanize.paths` calls into a
:class:`MouseAPI` implementation rather than ``pynput`` directly. That
keeps one source of truth for "how the cursor actually moves" and lets
a future ``post_message`` backend (Win32 ``WM_MOUSEMOVE`` /
``WM_LBUTTONDOWN``) reuse the same humanization layer by supplying
its own MouseAPI.
"""

from __future__ import annotations

from typing import Protocol, Tuple


class MouseAPI(Protocol):
    """Minimum surface the humanizer needs from a mouse controller."""

    def get_position(self) -> Tuple[int, int]: ...
    def set_position(self, x: int, y: int) -> None: ...
    def press(self, button: str = "left") -> None: ...
    def release(self, button: str = "left") -> None: ...
    def scroll(self, dy: int) -> None: ...


class PynputMouse:
    """Default :class:`MouseAPI` implementation backed by ``pynput``.

    Used by the ``real`` input backend (visible cursor, whole-screen
    Windows). Instantiated once and reused.
    """

    def __init__(self) -> None:
        from pynput.mouse import Controller
        self._c = Controller()

    def get_position(self) -> Tuple[int, int]:
        pos = self._c.position
        return int(pos[0]), int(pos[1])

    def set_position(self, x: int, y: int) -> None:
        self._c.position = (int(x), int(y))

    def press(self, button: str = "left") -> None:
        from pynput.mouse import Button
        self._c.press(self._btn(button))

    def release(self, button: str = "left") -> None:
        from pynput.mouse import Button
        self._c.release(self._btn(button))

    def scroll(self, dy: int) -> None:
        """Vertical scroll-wheel notches. Positive = scroll up (zoom in in RS3)."""
        self._c.scroll(0, int(dy))

    @staticmethod
    def _btn(name: str):
        from pynput.mouse import Button
        return {
            "left": Button.left,
            "right": Button.right,
            "middle": Button.middle,
        }.get(name.lower(), Button.left)
