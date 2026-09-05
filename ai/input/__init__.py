"""Input and capture seams for the bot framework.

- :class:`InputBackend` is the Protocol every actuator satisfies. The
  only shipped implementation is
  :class:`ai.input.clicker_actuator.ClickerActuatorBackend`, which
  routes through PhantomClick's humanizer and keyboard backends. The
  app builds it once and hands it to ``BotRunner.play``.
- :class:`FrameSource` / :class:`FrameMapper` (see ``frame_source``)
  are the capture side: where frames come from and how frame pixels
  map back to screen pixels.

Phase 2 adds a KMBox NET actuator and a capture-card frame source
behind the same two Protocols.
"""

from __future__ import annotations

from typing import Protocol

from .frame_source import (
    FrameMapper,
    FrameSource,
    MssFrameSource,
    ReplaySource,
    cursor_screen_xy,
)


class InputBackend(Protocol):
    """Minimal surface every input adapter must provide.

    Coordinates are physical screen pixels. Optional extras the runner
    probes with ``getattr``: ``click_here(button)``, ``shutdown()``,
    ``stop_event``, ``set_input_listener(fn)``, ``last_input_at``.
    """

    name: str

    def move(self, x: int, y: int) -> None: ...
    def click(self, x: int, y: int, button: str = "left") -> None: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str) -> None: ...
    def scroll(self, dy: int) -> None: ...
    def drag(
        self,
        start: "tuple[int, int]",
        end: "tuple[int, int]",
        button: str = "middle",
    ) -> None: ...


__all__ = [
    "FrameMapper",
    "FrameSource",
    "InputBackend",
    "MssFrameSource",
    "ReplaySource",
    "cursor_screen_xy",
]
