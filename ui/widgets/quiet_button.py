"""Quiet button variants for the form-style pages.

:class:`QuietAccentButton` — tinted-coral primary action. Reads as
"important" without the loud solid-fill of a hero CTA.

:class:`BorderlessButton` — transparent secondary action that fills only
on hover. Used for menu triggers (``Rect ▾``) and footer links.

Both apply their visual via the QSS ``role`` attribute, so the actual
styling lives in :mod:`ui.qss` next to every other role rule.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget


class QuietAccentButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setProperty("role", "quiet-accent")
        self.setCursor(Qt.PointingHandCursor)


class BorderlessButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setProperty("role", "borderless")
        self.setCursor(Qt.PointingHandCursor)
