"""Click page — :class:`PageHeader` + :class:`ClickZoneCard` +
:class:`TimingCard`.

Two-column grid above ``CLICK_PAGE_TWO_COL_MIN``, single-column stack below.
The flip happens via a ``resizeEvent`` watcher that re-positions cards inside
a single persistent :class:`QGridLayout` — never swaps the layout itself, which
avoids the Qt ownership-transfer fragility that segfaults at runtime. Cards
hug the top of the page (``addStretch(1)`` after the grid) so empty space
never floats below configured cards.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from ..cards.click_mode import ClickZoneCard, TimingCard
from ..widgets.page_header import PageHeader


class ClickPage(QWidget):
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

        self._inner = QWidget()
        page = QVBoxLayout(self._inner)
        page.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_LG)
        page.setSpacing(t.SP_MD)

        page.addWidget(PageHeader(
            "Click mode",
            "One zone, clicks forever with humanized timing",
        ))

        # Cards.
        self.zone_card = ClickZoneCard(app)
        self.timing_card = TimingCard(app)
        self.zone_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.timing_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Persistent grid that hosts both cards. We only re-place the cards
        # and toggle column stretches when flipping between two-col / one-col;
        # the layout object itself is never swapped (which would segfault).
        self._cards_holder = QWidget()
        self._cards_holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._cards_grid = QGridLayout(self._cards_holder)
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setHorizontalSpacing(t.SP_MD)
        self._cards_grid.setVerticalSpacing(t.SP_MD)
        self._cards_grid.setAlignment(Qt.AlignTop)
        page.addWidget(self._cards_holder)

        # Push cards to the top — they hug their content; no empty space below.
        page.addStretch(1)

        scroll.setWidget(self._inner)
        outer.addWidget(scroll)

        self._is_two_col: bool | None = None
        self._apply_layout(two_col=True)

    def _apply_layout(self, *, two_col: bool) -> None:
        if two_col == self._is_two_col:
            return
        # Detach cards from the grid first; addWidget at new positions
        # re-attaches them. This avoids tearing down the grid itself.
        self._cards_grid.removeWidget(self.zone_card)
        self._cards_grid.removeWidget(self.timing_card)

        if two_col:
            # 1.15fr / 1fr ratio from the mockup (115 / 100).
            self._cards_grid.setColumnStretch(0, 115)
            self._cards_grid.setColumnStretch(1, 100)
            self._cards_grid.addWidget(self.zone_card, 0, 0)
            self._cards_grid.addWidget(self.timing_card, 0, 1)
        else:
            self._cards_grid.setColumnStretch(0, 1)
            self._cards_grid.setColumnStretch(1, 0)
            self._cards_grid.addWidget(self.zone_card, 0, 0)
            self._cards_grid.addWidget(self.timing_card, 1, 0)

        self._is_two_col = two_col

    def resizeEvent(self, event):  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        want_two_col = self.width() >= t.CLICK_PAGE_TWO_COL_MIN
        if want_two_col != self._is_two_col:
            self._apply_layout(two_col=want_two_col)
