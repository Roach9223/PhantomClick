"""Input backends for scripts. Two adapters:

* ``post_message`` — Win32 PostMessage, RS3 background play.
* ``real``        — pyautogui + pynput, any Windows app, real cursor.

Each script's YAML header carries an ``input_mode`` field; the runtime
picks the adapter accordingly.

API (uniform across backends)::

    from rs3vision_studio.input import get_backend

    inp = get_backend("post_message")
    inp.click(x, y, button="left")
    inp.move(x, y)
    inp.type_text("hello")
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Protocol


class InputBackend(Protocol):
    """Minimal surface every input adapter must provide.

    Optional ``shutdown()`` lets backends release watchdog threads;
    callers should invoke it when a run ends. Missing method is fine.
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


BackendName = Literal["post_message", "real"]


def get_backend(
    mode: BackendName,
    *,
    humanizer_config: Optional[Any] = None,
    is_stopped: Optional[Callable[[], bool]] = None,
    on_failsafe: Optional[Callable[[], None]] = None,
) -> InputBackend:
    """Construct an input backend.

    ``humanizer_config`` and ``is_stopped`` are plumbed through to the
    ``real`` backend so the runtime can share its stop flag and
    :class:`~rs3vision_studio.humanize.config.HumanizerConfig` with the
    click layer. Ignored for backends that don't use humanization.
    """
    if mode == "post_message":
        from .post_message import PostMessageBackend
        return PostMessageBackend()
    if mode == "real":
        from .real import RealInputBackend
        return RealInputBackend(
            cfg=humanizer_config,
            is_stopped=is_stopped,
            on_failsafe=on_failsafe,
        )
    raise ValueError(f"unknown input mode: {mode!r}")
