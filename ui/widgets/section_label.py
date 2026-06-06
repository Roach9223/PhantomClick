"""``SectionLabel`` — small uppercase eyebrow for grouping fields inside a card.

Pre-uppercases its text and bumps QFont letter-spacing so the visual matches
the design spec. QSS doesn't support ``text-transform`` or ``letter-spacing``
so we set both at the QFont level here.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget


class SectionLabel(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text.upper(), parent)
        self.setProperty("role", "section-label")
        font = self.font()
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
        self.setFont(font)

    def set_text(self, text: str) -> None:
        self.setText(text.upper())
