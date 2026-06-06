"""Hover page — :class:`PageHeader` + :class:`HoverPageBody`.

The 2026 redesign drops the prior :class:`TwoColPage` + :class:`InfoPanel`
arrangement entirely. The page is now a single left-aligned column,
content max-width capped at :data:`ui.theme.PAGE_CONTENT_MAX_WIDTH`,
sitting in a scroll area. The page subtitle does the explanatory work
that the old InfoPanel used to carry; the body's footer hint links back
to related settings on the Behavior page.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.hover_zones import HoverPageBody
from ..widgets.page_header import PageHeader


class HoverPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        # Outer page layout: left-aligned content with empty space to the
        # right when the window is wider than the content cap.
        page_row = QHBoxLayout(inner)
        page_row.setContentsMargins(
            t.PAGE_PAD_X, t.PAGE_PAD_Y_TOP,
            t.PAGE_PAD_X, t.PAGE_PAD_Y_BOTTOM,
        )
        page_row.setSpacing(0)
        page_row.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        content = QWidget()
        content.setMaximumWidth(t.PAGE_CONTENT_MAX_WIDTH)
        content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(PageHeader(
            "Hover zones",
            "Regions where the cursor drifts and dwells without clicking. "
            "Adds the small movements humans make between actions.",
        ))

        self.body = HoverPageBody(app)
        col.addWidget(self.body)

        col.addStretch(1)

        page_row.addWidget(content)
        page_row.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_hover_page(app):
    page = HoverPage(app)
    return page, page.body
