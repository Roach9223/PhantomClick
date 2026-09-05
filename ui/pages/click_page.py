"""Click page: the SETUP pane for Click mode.

The deck already runs the daily loop for Click mode (REDRAW ZONE, MIN /
MAX / REALISM sliders, L / R / M, RUN), so this pane holds only what is
set once: the click area itself (:class:`ClickZoneCard`) and, behind a
collapsed expander, the timing details (:class:`TimingCard`: presets,
button, pattern). Realism lives on the deck slider and the Behavior page,
not here.

The card keeps the ``zone_card`` / ``timing_card`` attributes the deck and
the palette commands drive.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from .. import theme as t
from ..cards.click_mode import ClickZoneCard, TimingCard
from ..widgets.expander import Expander
from ..widgets.page_header import EditorHeader


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

        self.header = EditorHeader(
            "Click setup",
            "1. Draw a zone. 2. Set the interval. 3. Test one click. 4. Start.",
        )
        page.addWidget(self.header)

        self.zone_card = ClickZoneCard(app)
        self.zone_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        page.addWidget(self.zone_card)

        # Timing details fold away: presets, button and pattern are set
        # once, and the interval itself is on the deck's MIN / MAX sliders.
        self.timing_card = TimingCard(app)
        self.timing_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.timing_expander = Expander("Timing details", preview="presets, button, pattern")
        self.timing_expander.setToolTip(
            "Interval presets, which mouse button fires and single or double "
            "click. The interval itself is also on the deck's MIN / MAX sliders.")
        self.timing_expander.set_content(self.timing_card)
        self.timing_expander.set_open(False)
        page.addWidget(self.timing_expander)

        self.test_btn = QPushButton("Test one click")
        self.test_btn.setToolTip("After the start countdown, click once in the zone and stop. F7 cancels.")
        self.test_btn.clicked.connect(app._test_click_once)
        app.locker.register(self.test_btn)
        page.addWidget(self.test_btn)

        page.addStretch(1)

        scroll.setWidget(self._inner)
        outer.addWidget(scroll)

    def tick(self) -> None:
        from ui.readiness import readiness_message
        message = readiness_message(self.app) if self.app._active_mode == "clicker" else ""
        ready = self.app._zone is not None and not message
        self.test_btn.setEnabled(ready and self.app._state_str == "idle")
        # The reason a test is blocked lives on the button; the MISSION
        # panel and the START tooltip say the same thing, so no extra line.
        tip = ("After the start countdown, click once in the zone and stop. F7 cancels."
               if ready else (message or "Draw a zone to enable the one-click test."))
        if self.test_btn.toolTip() != tip:
            self.test_btn.setToolTip(tip)

    def reveal_timing(self) -> None:
        """Open the timing details (the deck's INTERVAL row lands here)."""
        self.timing_expander.set_open(True)

    def sync_overlay_switch(self) -> None:
        """Mirror the on-screen outline toggle (App.set_overlay_visible)."""
        self.zone_card.sync_overlay_switch()
