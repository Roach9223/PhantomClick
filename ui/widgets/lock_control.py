"""``ZoneLockControl``: LOCK  WINDOW | SCREEN plus a readout of the locked
window's title.

One row shared by the Click zone card and the Record step bodies so the
lock switch looks and behaves the same everywhere. The control never
touches the zone itself; it emits ``modeChanged`` and the owner decides
how to re-anchor (see ``modules.zone_lock.apply_lock_mode``).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .. import theme as t
from .segmented import SegmentedControl

MODE_WINDOW = "window"
MODE_SCREEN = "screen"

_READOUT_MAX_PX = 220


class ZoneLockControl(QWidget):
    modeChanged = Signal(str)   # "window" | "screen"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(t.SP_MD)

        lbl = QLabel("LOCK")
        lbl.setProperty("role", "section-label")
        font = lbl.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        lbl.setFont(font)
        lbl.setFixedWidth(96)
        lbl.setToolTip(
            "WINDOW: the zone follows the window it was drawn over, so a "
            "dragged or resized game window keeps the clicks on target. "
            "SCREEN: fixed screen coordinates."
        )
        row.addWidget(lbl)

        self.seg = SegmentedControl(
            [(MODE_WINDOW, "Window"), (MODE_SCREEN, "Screen")],
            value=MODE_SCREEN,
            tooltips={
                MODE_WINDOW: (
                    "WINDOW: the area is tied to the window it was drawn "
                    "over. Drag or resize that window and the clicks follow "
                    "it. If the window is minimised or closed the engine "
                    "holds instead of clicking whatever is underneath."),
                MODE_SCREEN: (
                    "SCREEN: the area stays at fixed screen coordinates no "
                    "matter which window is there. Use it for things that "
                    "never move, like a full-screen game."),
            },
        )
        self.seg.valueChanged.connect(self.modeChanged)
        row.addWidget(self.seg)

        self.readout = QLabel("")
        self.readout.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px; background: transparent;"
        )
        self.readout.setMaximumWidth(_READOUT_MAX_PX)
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.readout.setToolTip(
            "Which window the area follows (WINDOW lock) or 'Fixed screen "
            "position' (SCREEN lock).")
        row.addWidget(self.readout, 1)
        self._full_title = ""

    def set_zone(self, zone) -> None:
        """Mirror ``zone``'s lock without emitting ``modeChanged``."""
        has_zone = zone is not None
        self.setEnabled(has_zone)
        lock = getattr(zone, "lock", None) if has_zone else None
        self.seg.setValue(MODE_WINDOW if lock is not None else MODE_SCREEN, emit=False)
        if lock is not None:
            self._full_title = lock.title or lock.cls or "(untitled window)"
            self.readout.setStyleSheet(
                f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_SM}px; background: transparent;"
            )
            self.readout.setToolTip(f"{self._full_title}\nClass: {lock.cls}")
        else:
            self._full_title = "Fixed screen position" if has_zone else ""
            self.readout.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_SM}px; background: transparent;"
            )
            self.readout.setToolTip("")
        self._apply_elide()

    def _apply_elide(self) -> None:
        fm = QFontMetrics(self.readout.font())
        self.readout.setText(fm.elidedText(self._full_title, Qt.ElideMiddle, _READOUT_MAX_PX))

    def resizeEvent(self, event):  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        self._apply_elide()
