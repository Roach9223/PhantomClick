"""Command-deck shell for PhantomClick.

Selected by ``cfg["ui_shell"] == "deck"`` (the default). ``"classic"``
builds the older TopBar + NavRail shell instead; both share the same
pages and engine glue.
"""

from .common import ClickRing, EventLog
from .shell import (
    DeckShell, EDITOR_PANE_MIN_W, NavShim, VIEWPORT_MIN_W, WINDOW_H_DEFAULT,
    WINDOW_H_MIN, WINDOW_W_DEFAULT, WINDOW_W_MIN, initial_geometry,
)

__all__ = [
    "ClickRing", "DeckShell", "EventLog", "NavShim", "initial_geometry",
    "WINDOW_W_DEFAULT", "WINDOW_H_DEFAULT", "WINDOW_W_MIN", "WINDOW_H_MIN",
    "VIEWPORT_MIN_W", "EDITOR_PANE_MIN_W",
]
