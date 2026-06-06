"""Monitor page — :class:`PageHeader` + :class:`MonitorCard`.

Single left-aligned column with content max-width capped at
:data:`ui.theme.PAGE_CONTENT_MAX_WIDTH`. Mirrors the structure of
:mod:`ui.pages.stats_page` so the page rhythm matches the rest of the
small-card pages.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.monitor import MonitorCard
from ..widgets.page_header import PageHeader


class MonitorPage(QWidget):
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
            "Monitor",
            "Stream your screen + control the bot from your phone over LAN.",
        ))

        self.card = MonitorCard(app)
        col.addWidget(self.card)

        col.addStretch(1)

        page_row.addWidget(content)
        page_row.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_monitor_page(app):
    page = MonitorPage(app)
    return page, page.card
