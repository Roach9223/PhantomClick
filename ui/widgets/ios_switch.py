"""``IOSSwitch`` — custom-painted iOS-style toggle.

White circle thumb on a coral track when on, on a dark track when off.
Animates the thumb position on toggle (~150 ms ease-out cubic). Used in
:class:`SettingsRow` controls where a switch reads more naturally than a
checkbox — e.g. master enable rows on the form-style pages.

Drop-in replacement for a checkbox at the API level: ``isChecked()``,
``setChecked()``, ``toggled(bool)`` all work as expected.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QWidget

from .. import theme as t


SWITCH_W = 36
SWITCH_H = 21
THUMB_SIZE = 17
THUMB_PAD = 2


class IOSSwitch(QAbstractButton):
    toggledChanged = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(SWITCH_W, SWITCH_H)
        self.setCursor(Qt.PointingHandCursor)

        self._thumb_pos = THUMB_PAD
        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        end = SWITCH_W - THUMB_SIZE - THUMB_PAD if on else THUMB_PAD
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(end)
        self._anim.start()
        self.toggledChanged.emit(on)

    def get_thumb_pos(self) -> int:
        return self._thumb_pos

    def set_thumb_pos(self, value: int) -> None:
        self._thumb_pos = value
        self.update()

    thumb_pos = Property(int, get_thumb_pos, set_thumb_pos)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt name)
        # Snap the thumb to the right end without animation when the state
        # is set programmatically (e.g. from cfg load); only user toggles
        # animate. This avoids a visual "ping" on app boot.
        super().setChecked(checked)
        self._thumb_pos = (
            SWITCH_W - THUMB_SIZE - THUMB_PAD if checked else THUMB_PAD
        )
        self.update()

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Track
        track_color = QColor(t.ACCENT) if self.isChecked() else QColor("#2a2f38")
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, SWITCH_W, SWITCH_H),
                            SWITCH_H / 2, SWITCH_H / 2)
        p.fillPath(path, track_color)

        # Thumb
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(self._thumb_pos, THUMB_PAD, THUMB_SIZE, THUMB_SIZE))
