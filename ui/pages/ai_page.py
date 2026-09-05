"""AI page, wraps :class:`AIPageBody` with the standard
:class:`PageHeader` + scroll-area scaffolding used by every other page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.ai import AIPageBody
from ..widgets.ios_switch import IOSSwitch
from ..widgets.page_header import EditorHeader


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
        # Tighter horizontal gutter than the form-row pages, the AI page is
        # card-based, like Click, so it uses Click's spacing scheme rather
        # than Hotkeys/Hover's wider PAGE_PAD_X.
        page_row.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_LG)
        page_row.setSpacing(0)
        page_row.setAlignment(Qt.AlignTop)

        content = QWidget()
        # No max-width cap, the AI page is card-based like Click/Record,
        # not form-row like Hotkeys/Hover. The cards should claim the full
        # canvas width (capped only by the window itself).
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.header = EditorHeader(
            "AI bot",
            "Screen-based rules automate actions. Configure captures, then test in dry run.",
        )
        # AUTHOR TOOLS switch: captures, library, rules, calibration and
        # the log only matter to whoever is writing the bot.
        author_lbl = QLabel("AUTHOR TOOLS")
        author_lbl.setProperty("role", "section-label")
        font = author_lbl.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        author_lbl.setFont(font)
        self.header.add_trailing(author_lbl)
        self.author_switch = IOSSwitch()
        self.author_switch.setToolTip(
            "Show the bot author's tools: captures, the global capture "
            "library, fired rules, calibration and the log."
        )
        self.author_switch.setChecked(bool(app.cfg.get("ai_author_tools", False)))
        self.header.add_trailing(self.author_switch)
        col.addWidget(self.header)

        self.body = AIPageBody(app)
        col.addWidget(self.body, 1)
        self.author_switch.toggled.connect(self.body.set_author_tools)

        # Card claims the full canvas, no trailing right-stretch so the
        # content can grow into the available width.
        page_row.addWidget(content, 1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)


def build_ai_page(app):
    page = AIPage(app)
    return page, page.body
