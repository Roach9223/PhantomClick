"""``Section`` — header + content container used inside cards.

Renders a small uppercase label (with letter-spacing for visual weight)
and a hairline divider, then a content area beneath. Cards add Sections
to their body layout to break flat label-control stacks into named groups.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


class Section(QWidget):
    def __init__(self, title: str, hint: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.SP_SM)

        # Header row: uppercase teal label · optional inline hint.
        # The trailing hairline rule was removed — the teal eyebrow alone
        # carries the section marker, and the rule was rendering clipped
        # short of the card's right edge in practice (looked like a bug).
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(t.SP_SM)
        label = QLabel(title.upper())
        label.setStyleSheet(
            f"color: {t.ACCENT}; "
            f"font-family: {t.FONT_DISPLAY}; "
            f"font-size: {t.SIZE_SECTION_LABEL}px; "
            f"font-weight: 700; "
            f"letter-spacing: 1.4px;"
        )
        header.addWidget(label)
        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_HINT}px;"
            )
            header.addWidget(hint_lbl)
        header.addStretch(1)
        outer.addLayout(header)

        # Body: where children get placed.
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
