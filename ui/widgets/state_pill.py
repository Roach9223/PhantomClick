"""``StatePill``: small rectangular chip that shows a state next to a card
title.

Two tones: ``"accent"`` (lime text on a lime wash, meaning something is
set or live) and ``"neutral"`` (secondary text on the panel colour, for
"Not set"). 6 px radius, never full-round. Text is uppercased.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget


class StatePill(QLabel):
    def __init__(
        self,
        text: str,
        tone: str = "accent",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text.upper(), parent)
        self.setProperty("role", "state-pill")
        font = self.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        self.setFont(font)
        if tone != "accent":
            self.setProperty("tone", tone)

    def set_state(self, text: str, tone: str = "accent") -> None:
        """Update text + tone in one call. Repolishes so QSS picks up
        the new tone attribute."""
        self.setText(text.upper())
        new_tone = tone if tone != "accent" else None
        if self.property("tone") != new_tone:
            self.setProperty("tone", new_tone)
            self.style().unpolish(self)
            self.style().polish(self)
