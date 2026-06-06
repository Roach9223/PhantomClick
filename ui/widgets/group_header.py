"""``GroupHeader`` — uppercase eyebrow above a :class:`SettingsGroup`.

Pre-uppercases its text and bumps QFont letter-spacing (QSS doesn't
support text-transform / letter-spacing). Optionally hosts right-side
actions like a ``+ Add zone`` button or a ``Rect ▾`` shape menu trigger
so a group can carry its own affordances without a separate row.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from .. import theme as t


class GroupHeader(QFrame):
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        # Left padding aligns header text with the first row's content.
        self._row.setContentsMargins(t.GROUP_HEADER_PAD_LEFT, 0, 2, 9)
        self._row.setSpacing(t.SP_SM)

        self._label = QLabel(title.upper())
        self._label.setProperty("role", "group-header")
        font = self._label.font()
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        self._label.setFont(font)
        self._row.addWidget(self._label)

        self._row.addStretch(1)

    def add_action(self, widget: QWidget) -> None:
        """Append a trailing action widget. Multiple calls stack right-to-
        left in the order added."""
        self._row.addWidget(widget)
