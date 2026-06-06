"""``ZoneThumbnail`` — 38×22 mini monitor with a single zone painted.

Sized for inline use as a :class:`SettingsRow` ``leading`` widget so each
hover-zone row carries its own spatial context (the user can see *where*
on the monitor the zone sits without flipping to a hero canvas).

Optionally paints a faint dashed reference for the active click zone,
giving an at-a-glance sense of how the hover zone relates to the click
target. Color is fixed at :data:`ui.theme.ACCENT` — this is a UI
affordance, not a fidelity preview of the in-world overlay.

Accepts a :class:`~modules.zone_selector.Zone` directly (via the existing
``rect``/``circle``/``vertices`` attributes) — no JSON conversion needed.
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import theme as t


class ZoneThumbnail(QWidget):
    DEFAULT_W = 38
    DEFAULT_H = 22

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(self.DEFAULT_W, self.DEFAULT_H)
        self._monitor: Tuple[int, int] = (0, 0)
        self._zone = None
        self._click_zone = None

    # -- Public API --------------------------------------------------------

    def set_monitor(self, width: int, height: int) -> None:
        self._monitor = (int(width), int(height))
        self.update()

    def set_zone(self, zone) -> None:
        self._zone = zone
        self.update()

    def set_click_reference(self, zone) -> None:
        self._click_zone = zone
        self.update()

    # -- Painting ----------------------------------------------------------

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Frame
        p.setPen(QPen(QColor(t.BORDER_SUBTLE), 1))
        p.setBrush(QColor(t.BG))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 3, 3)

        mw, mh = self._monitor
        if mw <= 0 or mh <= 0 or self._zone is None:
            return

        sx = (self.DEFAULT_W - 2) / mw
        sy = (self.DEFAULT_H - 2) / mh

        # Click reference (faint dashed) drawn first so the hover zone
        # paints over it.
        if self._click_zone is not None:
            ref_pen = QPen(QColor("#3a3f48"), 0.8, Qt.DashLine)
            p.setPen(ref_pen)
            p.setBrush(Qt.NoBrush)
            self._draw_shape(p, self._click_zone, sx, sy)

        # Hover zone — coral fill + stroke.
        coral_stroke = QColor(t.ACCENT)
        coral_stroke.setAlphaF(0.85)
        coral_fill = QColor(t.ACCENT)
        coral_fill.setAlphaF(0.5)
        p.setPen(QPen(coral_stroke, 1))
        p.setBrush(coral_fill)
        self._draw_shape(p, self._zone, sx, sy)

    def _draw_shape(self, p: QPainter, zone, sx: float, sy: float) -> None:
        if zone.shape == "rect":
            x1, y1, x2, y2 = zone.rect
            x = x1 * sx + 1
            y = y1 * sy + 1
            w = max(1.5, (x2 - x1) * sx)
            h = max(1.5, (y2 - y1) * sy)
            p.drawRoundedRect(QRectF(x, y, w, h), 1, 1)
        elif zone.shape == "circle":
            cx, cy, r = zone.circle
            cx_p = cx * sx + 1
            cy_p = cy * sy + 1
            r_p = max(1.5, r * min(sx, sy))
            p.drawEllipse(QRectF(cx_p - r_p, cy_p - r_p, r_p * 2, r_p * 2))
        else:
            verts = zone.vertices
            if not verts:
                return
            path = QPainterPath()
            path.moveTo(verts[0][0] * sx + 1, verts[0][1] * sy + 1)
            for vx, vy in verts[1:]:
                path.lineTo(vx * sx + 1, vy * sy + 1)
            path.closeSubpath()
            p.drawPath(path)
