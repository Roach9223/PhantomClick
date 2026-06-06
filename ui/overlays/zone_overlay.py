"""``ZoneOverlay`` — frameless translucent widget that paints a zone outline
plus an optional label badge on the user's screen.

Click-through: the OS layer must NOT route mouse events to this window,
otherwise it'd intercept the very clicks the engine is firing. Qt's
``Qt.WindowTransparentForInput`` flag covers most cases; on Windows we
also set ``WS_EX_TRANSPARENT | WS_EX_LAYERED`` via ctypes to be sure
games using low-level input don't see us.

Multi-monitor: the overlay sizes itself to the bounding box of the zone
and positions on the virtual desktop coords, so a zone drawn on a
secondary monitor (left < 0) renders correctly.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from .. import theme as t


class ZoneOverlay(QWidget):
    def __init__(self):
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

        self._zone = None
        self._color = QColor(t.ZONE_DEFAULT_COLOR)
        self._opacity = t.ZONE_DEFAULT_OPACITY
        self._label: Optional[str] = None

    # -- Public API --------------------------------------------------------

    def show_zone(self, zone, color: str, opacity: float, *,
                  label: Optional[str] = None) -> None:
        self._zone = zone
        self._color = QColor(color)
        self._opacity = float(opacity)
        self._label = label
        self._reposition()
        self.show()
        self._apply_click_through()
        self.update()

    def hide_zone(self) -> None:
        self.hide()

    def update_style(self, color: str, opacity: float) -> None:
        self._color = QColor(color)
        self._opacity = float(opacity)
        self.update()

    # -- Layout -----------------------------------------------------------

    def _reposition(self) -> None:
        if self._zone is None:
            return
        x1, y1, x2, y2 = self._zone.aabb()
        # Pad for the label badge above + stroke width.
        pad = 28
        w = max(1, x2 - x1) + pad * 2
        h = max(1, y2 - y1) + pad * 2
        self.setGeometry(int(x1) - pad, int(y1) - pad, int(w), int(h))
        self._origin = (int(x1) - pad, int(y1) - pad)

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 (Qt name)
        if self._zone is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ox, oy = self._origin

        fill = QColor(self._color)
        fill.setAlphaF(self._opacity)
        stroke = QColor(self._color)

        z = self._zone
        if z.shape == "rect":
            x1, y1, x2, y2 = z.rect
            r = QRectF(x1 - ox, y1 - oy, x2 - x1, y2 - y1)
            p.setPen(QPen(stroke, 2))
            p.setBrush(QBrush(fill))
            p.drawRoundedRect(r, 4, 4)
            label_anchor = QPointF(r.left(), r.top() - 4)
        elif z.shape == "circle":
            cx, cy, radius = z.circle
            r = QRectF(cx - radius - ox, cy - radius - oy, radius * 2, radius * 2)
            p.setPen(QPen(stroke, 2))
            p.setBrush(QBrush(fill))
            p.drawEllipse(r)
            label_anchor = QPointF(r.left(), r.top() - 4)
        else:
            path = QPainterPath()
            verts = z.vertices
            if verts:
                path.moveTo(verts[0][0] - ox, verts[0][1] - oy)
                for vx, vy in verts[1:]:
                    path.lineTo(vx - ox, vy - oy)
                path.closeSubpath()
            p.setPen(QPen(stroke, 2))
            p.setBrush(QBrush(fill))
            p.drawPath(path)
            x1, y1, x2, y2 = z.aabb()
            label_anchor = QPointF(x1 - ox, y1 - oy - 4)

        if self._label:
            self._draw_label(p, label_anchor)

    def _draw_label(self, p: QPainter, pos: QPointF) -> None:
        font = QFont(t.FONT_FAMILY.split(",")[0].strip(), 9)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetrics(font)
        text = self._label or ""
        tw = fm.horizontalAdvance(text) + 12
        th = fm.height() + 4
        bg_color = QColor(self._color)
        bg_color.setAlpha(220)
        rect = QRectF(pos.x(), pos.y() - th, tw, th)
        p.setPen(Qt.NoPen)
        p.setBrush(bg_color)
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(rect.adjusted(6, 1, 0, -1), Qt.AlignVCenter | Qt.AlignLeft, text)

    # -- Win32 click-through reinforcement --------------------------------

    def _apply_click_through(self) -> None:
        """Apply ``WS_EX_TRANSPARENT | WS_EX_LAYERED`` on Windows so that
        games using low-level input ignore us. ``WindowTransparentForInput``
        usually suffices but Win32 layered windows are the surest path."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x80
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                ex | WS_EX_LAYERED | WS_EX_TRANSPARENT
                | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            )
        except Exception:
            pass
