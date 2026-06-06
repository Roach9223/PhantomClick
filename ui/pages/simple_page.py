"""Generic page wrapper — single card in a scrollable column.

Used by Record/Hover/Behavior/Hotkeys/Stats. Honors an optional
``max_card_w`` so small cards (Hotkeys) don't span a 1500 px window
unnaturally; larger cards (Behavior, Record) pass ``None`` to fill.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t


class SimplePage(QWidget):
    def __init__(self, card: QWidget, max_card_w: Optional[int] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        if max_card_w is None:
            # Card fills the page width AND height — the card itself owns
            # the canvas. Previously a trailing addStretch ate vertical
            # space, leaving mode pages (Record especially) with a giant
            # dead area below their content; passing stretch=1 to the card
            # is what we actually want for full-bleed modes.
            # Outer page padding kept tight (SP_SM not SP_LG) so cards
            # claim the canvas rather than float in 16 px gutters.
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_SM)
            inner_layout.setSpacing(t.SP_MD)
            inner_layout.addWidget(card, 1)
        else:
            # Card centered with a max width.
            inner_layout = QHBoxLayout(inner)
            inner_layout.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
            inner_layout.setSpacing(0)
            inner_layout.addStretch(1)
            wrap = QWidget()
            wrap.setMaximumWidth(max_card_w)
            wrap.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(t.SP_MD)
            wl.addWidget(card)
            wl.addStretch(1)
            inner_layout.addWidget(wrap)
            inner_layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)
