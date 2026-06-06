"""PostMessage backend — RS3 NXT background-play input.

**Not yet implemented.** RS3 NXT (``rs2client.exe``) is a C++ native
client; background-play requires:

1. Locating the client's HWND via ``FindWindowW`` / window-class enum.
2. Sending synthetic input with Win32 ``PostMessage``:
   ``WM_MOUSEMOVE`` → ``WM_LBUTTONDOWN`` → ``WM_LBUTTONUP`` with
   client-relative ``LPARAM`` coordinates.
3. Handling keyboard with ``WM_KEYDOWN`` / ``WM_KEYUP`` + proper
   scan-code packing.
4. Converting monitor-space pixel coordinates (what the detection
   blocks emit) into client-relative coordinates via
   ``ScreenToClient``.

We also want to share the
:class:`~rs3vision_studio.humanize.config.HumanizerConfig` so paths,
overshoot, and fatigue behave identically to the visible-cursor
backend — that means implementing a :class:`MouseAPI` adapter that
buffers mouse-position updates into ``WM_MOUSEMOVE`` messages.

Tracking: see ``docs/post-message-status.md``. Until this lands, use
``input_mode: real`` in your task / script.
"""

from __future__ import annotations


class PostMessageBackend:
    name = "post_message"

    _NOT_READY_MSG = (
        "PostMessage backend is not yet implemented. "
        "Use input_mode: real in your task / script, or see "
        "docs/post-message-status.md for the roadmap."
    )

    def move(self, x: int, y: int) -> None:
        raise NotImplementedError(self._NOT_READY_MSG)

    def click(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError(self._NOT_READY_MSG)

    def type_text(self, text: str) -> None:
        raise NotImplementedError(self._NOT_READY_MSG)

    def press_key(self, key: str) -> None:
        raise NotImplementedError(self._NOT_READY_MSG)

    def scroll(self, dy: int) -> None:
        raise NotImplementedError(self._NOT_READY_MSG)

    def drag(self, start, end, button: str = "middle") -> None:
        raise NotImplementedError(self._NOT_READY_MSG)
