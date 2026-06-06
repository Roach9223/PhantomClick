"""Hotkeys page — :class:`PageHeader` + :class:`HotkeysPageBody`.

Mirrors the structure of :mod:`ui.pages.hover_page`: single left-aligned
column, content max-width capped at
:data:`ui.theme.PAGE_CONTENT_MAX_WIDTH`, no :class:`TwoColPage` /
:class:`InfoPanel`. The body itself groups Global hotkeys + In-app
shortcuts as form-row :class:`SettingsGroup`s.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.hotkeys import HotkeysPageBody
from ..widgets.page_header import PageHeader


class HotkeysPage(QWidget):
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
            "Hotkeys",
            "Global keys that work even when a fullscreen game is focused.",
        ))

        self.body = HotkeysPageBody(app)
        col.addWidget(self.body)

        col.addStretch(1)

        page_row.addWidget(content)
        page_row.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_hotkeys_page(app):
    page = HotkeysPage(app)
    return page, page.body
