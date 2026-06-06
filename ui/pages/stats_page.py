"""Stats page — :class:`PageHeader` + :class:`StatsPageBody`.

Single left-aligned column, content max-width capped at
:data:`ui.theme.PAGE_CONTENT_MAX_WIDTH`. The body builds one
:class:`SettingsGroup` of metric rows that live-update every frame
through the App's ``_ticking_cards`` loop.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.stats import StatsPageBody
from ..widgets.page_header import PageHeader


class StatsPage(QWidget):
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
            "Statistics",
            "Live counters for the active session.",
        ))

        self.body = StatsPageBody(app)
        col.addWidget(self.body)

        col.addStretch(1)

        page_row.addWidget(content)
        page_row.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_stats_page(app):
    page = StatsPage(app)
    return page, page.body
