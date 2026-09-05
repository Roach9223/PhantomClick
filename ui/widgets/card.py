"""``Card``: the bordered panel every group of controls sits in.

Deck panel: SURFACE fill, full 1 px BORDER, 8 px radius, no shadow. The
header label is uppercase 11 px mono, 600 weight, 1.6 px tracking, in
TEXT_PRIMARY. Children are added via :meth:`Card.body` / :meth:`Card.add`.

Carries ``objectName="card"`` so the global stylesheet picks up its
background + border without per-instance QSS.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


def panel_header_label(title: str, parent: Optional[QWidget] = None) -> QLabel:
    """Uppercase tracked panel header, shared by Card and any deck panel
    that wants the same header without the Card frame."""
    header = QLabel(title.upper(), parent)
    header.setProperty("role", "card-header")
    font = header.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.PANEL_HEADER_TRACKING)
    header.setFont(font)
    return header


class Card(QFrame):
    def __init__(self, title: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(t.CARD_PAD, t.SP_SM + 2, t.CARD_PAD, t.CARD_PAD)
        self._outer.setSpacing(t.SP_SM)

        self._header_row: Optional[QHBoxLayout] = None
        if title:
            header_widget = QWidget(self)
            self._header_row = QHBoxLayout(header_widget)
            self._header_row.setContentsMargins(0, 0, 0, 0)
            self._header_row.setSpacing(t.SP_SM)
            self._header_row.addWidget(panel_header_label(title))
            self._header_row.addStretch(1)
            self._outer.addWidget(header_widget)

        self._body = QWidget(self)
        self._body.setObjectName("card-inner")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(t.SP_SM)
        self._outer.addWidget(self._body)

    def add_to_header(self, widget: QWidget) -> QWidget:
        """Append a trailing widget (e.g. a StatePill) to the card's header
        row. Stretch sits between the title and these widgets so they pack
        to the right edge."""
        if self._header_row is None:
            self._body_layout.addWidget(widget)
            return widget
        self._header_row.addWidget(widget)
        return widget

    def body(self) -> QWidget:
        """Return the body container; add child widgets to its layout."""
        return self._body

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def add(self, widget: QWidget) -> QWidget:
        """Convenience: append a widget to the body layout. Returns the widget."""
        self._body_layout.addWidget(widget)
        return widget
