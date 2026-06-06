"""``WidgetLocker`` — disables UI controls while the click engine is running.

Cards register interactive widgets (Draw / Remove / Rebind / Add-step
buttons, etc.) so the user can't poke them mid-run and silently no-op.
The locker prunes destroyed widgets on every apply, so dynamically-rendered
rows (step list, hover list) only need to register at build time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from modules.clicker import ClickerState

if TYPE_CHECKING:
    pass


class WidgetLocker:
    def __init__(self) -> None:
        self._widgets: list[QWidget] = []

    def register(self, widget: QWidget) -> QWidget:
        """Register a widget to be auto-disabled while the engine runs.

        Returns the widget so callers can chain.
        """
        self._widgets.append(widget)
        return widget

    def apply(self, state: str) -> None:
        """Enable on IDLE, disable on STARTING / ACTIVE."""
        enabled = state == ClickerState.IDLE
        alive: list[QWidget] = []
        for w in self._widgets:
            try:
                w.setEnabled(enabled)
                alive.append(w)
            except RuntimeError:
                # Widget was destroyed (e.g. step row re-rendered); drop it.
                pass
        self._widgets = alive
