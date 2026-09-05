"""``SectionLabel``: uppercase eyebrow for grouping fields inside a card.

Pre-uppercases its text and sets QFont letter-spacing to LABEL_TRACKING
(QSS has no ``text-transform`` and Qt ignores ``letter-spacing`` there).
Colour and size come from the ``role="section-label"`` rule: 10.5 px mono
in TEXT_TERTIARY.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from .. import theme as t


class SectionLabel(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text.upper(), parent)
        self.setProperty("role", "section-label")
        font = self.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        self.setFont(font)

    def set_text(self, text: str) -> None:
        self.setText(text.upper())
