"""``Card`` — the elevated panel every group of controls sits in.

Renders a rounded rectangle with a subtle border (per design tokens),
an uppercase tracked-out title at the top, and a content area beneath.
Children are added via :meth:`Card.body` to hide the inner layout.

Carries ``objectName="card"`` so the global stylesheet picks up its
background + border without needing per-instance QSS.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme as t


class Card(QFrame):
    def __init__(self, title: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(t.SP_MD, t.SP_SM, t.SP_MD, t.SP_SM)
        self._outer.setSpacing(t.SP_SM)

        self._header_row: Optional[QHBoxLayout] = None
        if title:
            header_widget = QWidget(self)
            self._header_row = QHBoxLayout(header_widget)
            self._header_row.setContentsMargins(0, 0, 0, 0)
            self._header_row.setSpacing(t.SP_SM)
            header = QLabel(title.upper())
            header.setProperty("role", "card-header")
            self._header_row.addWidget(header)
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
            # No title — nothing to attach to. Drop into body so we don't
            # silently lose the widget.
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
