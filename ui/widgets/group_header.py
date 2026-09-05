"""``GroupHeader``: uppercase eyebrow above a :class:`SettingsGroup`.

Pre-uppercases its text and sets QFont letter-spacing to LABEL_TRACKING.
Colour is GROUP_HEADER_COLOR (TEXT_TERTIARY); lime is never used on a
heading. Optionally hosts right-side actions like an "Add zone" button so
a group can carry its own affordances without a separate row.
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
        self._row.setContentsMargins(t.GROUP_HEADER_PAD_LEFT, 0, 2, 8)
        self._row.setSpacing(t.SP_SM)

        self._label = QLabel(title.upper())
        self._label.setProperty("role", "group-header")
        font = self._label.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        self._label.setFont(font)
        self._row.addWidget(self._label)

        self._row.addStretch(1)

    def add_action(self, widget: QWidget) -> None:
        """Append a trailing action widget."""
        self._row.addWidget(widget)
