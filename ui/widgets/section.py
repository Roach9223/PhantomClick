"""``Section``: eyebrow + content container used inside cards.

Renders an uppercase 10.5 px mono eyebrow in TEXT_TERTIARY (lime is
reserved for state, so headings never get it) with an optional inline
hint, then a content area beneath. Cards add Sections to their body
layout to break flat label-control stacks into named groups.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


class Section(QWidget):
    def __init__(self, title: str, hint: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.SP_SM)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(t.SP_SM)
        label = QLabel(title.upper())
        label.setProperty("role", "section-label")
        font = label.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        label.setFont(font)
        header.addWidget(label)
        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_HINT}px;"
            )
            header.addWidget(hint_lbl)
        header.addStretch(1)
        outer.addLayout(header)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(t.FIELD_GAP)
        outer.addWidget(self._body)

    def add(self, w: QWidget) -> QWidget:
        self._body_layout.addWidget(w)
        return w

    def addLayout(self, layout) -> None:  # noqa: N802 (Qt convention)
        self._body_layout.addLayout(layout)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout
