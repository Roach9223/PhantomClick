"""Behavior page — :class:`PageHeader` + :class:`BehaviorPageBody`.

Single left-aligned column, content max-width capped at
:data:`ui.theme.PAGE_CONTENT_MAX_WIDTH`. The body builds Pre-start +
Realism hero + every Advanced sub-group inline (no Expander) so the
whole humanization surface is one scroll away.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.behavior import BehaviorPageBody
from ..widgets.page_header import PageHeader


class BehaviorPage(QWidget):
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
            "Behavior",
            "How human the cursor feels — one dial drives every humanization knob.",
        ))

        self.body = BehaviorPageBody(app)
        col.addWidget(self.body)

        col.addStretch(1)

        page_row.addWidget(content)
        page_row.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_behavior_page(app):
    page = BehaviorPage(app)
    return page, page.body
