"""Click-marker flash — short-lived ring + crosshair at the actual click point.

Color encodes step kind: green for Click steps, magenta for Color steps.
Drift between the requested target and the actual click is logged at WARN.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRectF, QTimer, Qt,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect, QWidget,
)

_SIZE = 32
_LIFETIME_MS = 500


class _MarkerWidget(QWidget):
    def __init__(self, x: int, y: int, color: str):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor(color)
        self.setGeometry(x - _SIZE // 2, y - _SIZE // 2, _SIZE, _SIZE)

        # Fade-out animation.
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(1.0)
        self.setGraphicsEffect(eff)
        self._anim = QPropertyAnimation(eff, b"opacity", self)
        self._anim.setDuration(_LIFETIME_MS)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self.deleteLater)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self._color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(2, 2, _SIZE - 4, _SIZE - 4))
        p.drawLine(8, 8, _SIZE - 8, _SIZE - 8)
        p.drawLine(_SIZE - 8, 8, 8, _SIZE - 8)

    def show_and_fade(self) -> None:
        self.show()
        self._apply_click_through()
        self._anim.start()

    def _apply_click_through(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            WS_EX_NOACTIVATE = 0x08000000
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
            )
        except Exception:
            pass


def flash(app, target_x: int, target_y: int,
          actual_x: int, actual_y: int, kind: str) -> None:
    if not app.cfg.get("show_zone_overlay", True):
        return
    color = "#ff00ff" if kind == "color" else "#22dd66"
    marker = _MarkerWidget(actual_x, actual_y, color)
    marker.show_and_fade()
    # Drift logging.
    dx = abs(target_x - actual_x)
    dy = abs(target_y - actual_y)
    if dx > 3 or dy > 3:
        try:
            app.log.warning(
                "click drift: kind=%s target=(%d,%d) actual=(%d,%d) dx=%d dy=%d",
                kind, target_x, target_y, actual_x, actual_y, dx, dy,
            )
        except Exception:
            pass
