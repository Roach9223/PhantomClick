"""``IOSSwitch``: the deck toggle. Name kept for API compatibility.

A 30 x 14 rectangular switch: 1 px BORDER frame on a SURFACE_PANEL well,
12 x 10 square knob. Knob is lime when on, STATUS_IDLE when off. The knob
jumps between positions; there is no animation.

Drop-in replacement for a checkbox at the API level: ``isChecked()``,
``setChecked()``, ``toggled(bool)`` all work as expected. ``toggledChanged``
is kept for callers that connected to it.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from .. import theme as t


SWITCH_W = 30
SWITCH_H = 14
KNOB_W = 12
KNOB_H = 10
KNOB_PAD = 1


class IOSSwitch(QAbstractButton):
    toggledChanged = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(SWITCH_W, SWITCH_H)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, on: bool) -> None:
        self.update()
        self.toggledChanged.emit(on)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt name)
        super().setChecked(checked)
        self.update()

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        enabled = self.isEnabled()
        frame = QColor(t.BORDER_STRONG if self.underMouse() and enabled else t.BORDER)
        if not enabled:
            frame = QColor(t.BORDER_SUBTLE)
        p.setPen(QPen(frame, 1))
        p.setBrush(QColor(t.SURFACE_PANEL))
        p.drawRoundedRect(QRectF(0.5, 0.5, SWITCH_W - 1, SWITCH_H - 1), 3, 3)

        on = self.isChecked()
        if not enabled:
            knob = QColor(t.TEXT_DISABLED)
        else:
            knob = QColor(t.ACCENT if on else t.STATUS_IDLE)
        x = SWITCH_W - KNOB_W - KNOB_PAD - 1 if on else KNOB_PAD + 1
        y = (SWITCH_H - KNOB_H) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(knob)
        p.drawRoundedRect(QRectF(x, y, KNOB_W, KNOB_H), 1.5, 1.5)

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.update()
