"""``StatusDot`` — the colored indicator beside the status label.

Animates color transitions when the engine state changes (idle ↔ starting
↔ active) instead of jumping. Active state pulses subtly to read as "live".

Painted directly so the color animation can interpolate hex strings;
QSS would force discrete state changes.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, Qt, QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .. import theme as t


class StatusDot(QWidget):
    def __init__(self, parent=None, size: int = 12):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size + 4, size + 4)
        self._color = QColor(t.STATUS_IDLE)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(t.DUR_NORMAL)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)

    def set_state(self, state: str) -> None:
        """state: 'idle' | 'starting' | 'active'."""
        target = {
            "idle": t.STATUS_IDLE,
            "starting": t.STATUS_PAUSED,
            "active": t.STATUS_ACTIVE,
        }.get(state, t.STATUS_IDLE)
        self._anim.stop()
        self._anim.setStartValue(self._color)
        self._anim.setEndValue(QColor(target))
        self._anim.start()

    def _on_anim_value(self, value) -> None:
        if isinstance(value, QColor):
            self._color = value
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt method name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        cx, cy = self.width() // 2, self.height() // 2
        r = self._size // 2
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        # Soft outer halo so the dot reads as "lit" rather than flat.
        halo = QColor(self._color)
        halo.setAlphaF(0.25)
        p.setBrush(halo)
        p.drawEllipse(cx - r - 2, cy - r - 2, (r + 2) * 2, (r + 2) * 2)
