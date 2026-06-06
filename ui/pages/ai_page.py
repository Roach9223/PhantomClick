"""AI page — wraps :class:`AIPageBody` with the standard
:class:`PageHeader` + scroll-area scaffolding used by every other page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.ai import AIPageBody
from ..widgets.page_header import PageHeader


class AIPage(QWidget):
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
        # Tighter horizontal gutter than the form-row pages — the AI page is
        # card-based, like Click, so it uses Click's spacing scheme rather
        # than Hotkeys/Hover's wider PAGE_PAD_X.
        page_row.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_LG)
        page_row.setSpacing(0)
        page_row.setAlignment(Qt.AlignTop)

        content = QWidget()
        # No max-width cap — the AI page is card-based like Click/Record,
        # not form-row like Hotkeys/Hover. The cards should claim the full
        # canvas width (capped only by the window itself).
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(PageHeader(
            "AI Bot",
            "Pick a bot. Hit Start. The cursor and keys handle the rest.",
        ))

        self.body = AIPageBody(app)
        col.addWidget(self.body, 1)

        # Card claims the full canvas — no trailing right-stretch so the
        # content can grow into the available width.
        page_row.addWidget(content, 1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_ai_page(app):
    page = AIPage(app)
    return page, page.body
