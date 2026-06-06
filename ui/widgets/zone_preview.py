"""``ZonePreview`` — mini-map of the target monitor with one or more zones
painted on top.

Used by both the Click page (single zone or empty) and the Hover page
(0..N zones with index badges). The widget letterbox-fits the monitor's
aspect ratio inside a fixed 130 px-tall card slot, paints a 22 px screen
grid, then draws each zone using the same shape branches as
:class:`~ui.overlays.zone_overlay.ZoneOverlay`.

Color is fixed at :data:`ui.theme.ACCENT` rather than the user's overlay
color — this is a UI affordance, not a fidelity preview of the in-world
overlay.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

from .. import theme as t


class ZonePreview(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(130)
        self.setMinimumWidth(180)
        self._zones: List = []
        self._monitor_label: str = ""
        self._monitor_size: Tuple[int, int] = (0, 0)
        self._show_indices: bool = False
        self._empty_caption: str = "Drag to define your click area"

    # -- Public API --------------------------------------------------------

    def set_zones(
        self,
        zones: Optional[Sequence],
        monitor_label: str = "",
        monitor_size: Tuple[int, int] = (0, 0),
        *,
        show_indices: bool = False,
        empty_caption: Optional[str] = None,
    ) -> None:
        self._zones = [z for z in (zones or []) if z is not None]
        self._monitor_label = monitor_label
        self._monitor_size = monitor_size
        self._show_indices = show_indices
        if empty_caption is not None:
            self._empty_caption = empty_caption
        self.update()

    # Single-zone convenience for the Click page (preserves the old call site).
    def set_zone(
        self,
        zone,
        monitor_label: str = "",
        monitor_size: Tuple[int, int] = (0, 0),
    ) -> None:
        self.set_zones([zone] if zone is not None else [],
                       monitor_label, monitor_size)

    # -- Painting ----------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(t.BORDER_SUBTLE), 1))
        p.setBrush(QBrush(QColor(t.BG)))
        p.drawRoundedRect(outer, 6, 6)

        clip_path = QPainterPath()
        clip_path.addRoundedRect(outer, 6, 6)
        p.setClipPath(clip_path)

        self._paint_grid(p)
        self._paint_corner_label(p)

        if not self._zones:
            self._paint_empty_state(p)
        else:
            for idx, zone in enumerate(self._zones):
                self._paint_zone(p, zone, idx)
            self._paint_readout_pill(p)

    def _paint_grid(self, p: QPainter) -> None:
        grid_color = QColor(t.SURFACE_HIGH)
        grid_color.setAlphaF(0.5)
        p.setPen(QPen(grid_color, 1))
        step = 22
        x = step
        while x < self.width():
            p.drawLine(x, 1, x, self.height() - 1)
            x += step
        y = step
        while y < self.height():
            p.drawLine(1, y, self.width() - 1, y)
            y += step

    def _paint_corner_label(self, p: QPainter) -> None:
        if not self._monitor_label:
            return
        font = QFont(t.FONT_MONO.split(",")[0].strip(), 8)
        p.setFont(font)
        p.setPen(QPen(QColor(t.TEXT_TERTIARY)))
        p.drawText(9, 16, self._monitor_label)

    def _paint_empty_state(self, p: QPainter) -> None:
        w = self.width()
        h = self.height()
        rect_w = int(w * 0.6)
        rect_h = int(h * 0.42)
        rx = (w - rect_w) // 2
        ry = int(h * 0.22)
        pen = QPen(QColor(t.BORDER_STRONG), 1, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(rx, ry, rect_w, rect_h), 4, 4)

        font = QFont(t.FONT_FAMILY.split(",")[0].strip(), 9)
        p.setFont(font)
        p.setPen(QPen(QColor(t.TEXT_SECONDARY)))
        fm = QFontMetrics(font)
        text = self._empty_caption
        tw = fm.horizontalAdvance(text)
        p.drawText((w - tw) // 2, ry + rect_h + 16, text)

    # -- Zone painting -----------------------------------------------------

    def _zones_aabb(self) -> Tuple[int, int, int, int]:
        """AABB across every zone — used as a fallback fit when the
        monitor size is unknown."""
        xs1, ys1, xs2, ys2 = [], [], [], []
        for z in self._zones:
            x1, y1, x2, y2 = z.aabb()
            xs1.append(x1)
            ys1.append(y1)
            xs2.append(x2)
            ys2.append(y2)
        return (min(xs1), min(ys1), max(xs2), max(ys2))

    def _scale_xform(self) -> Tuple[float, float, float]:
        """Return ``(scale, dx, dy)`` so screen pt ``(sx, sy)`` maps to
        preview coords via ``(sx*scale + dx, sy*scale + dy)``."""
        mw, mh = self._monitor_size
        pad_x = 6
        pad_y_top = 24  # space for monitor caption
        pad_y_bot = 22  # space for readout pill
        inner_w = max(1, self.width() - pad_x * 2)
        inner_h = max(1, self.height() - pad_y_top - pad_y_bot)
        if mw <= 0 or mh <= 0:
            x1, y1, x2, y2 = self._zones_aabb()
            mw = max(1, x2 - x1)
            mh = max(1, y2 - y1)
            scale = min(inner_w / mw, inner_h / mh)
            dx = pad_x - x1 * scale + (inner_w - mw * scale) / 2
            dy = pad_y_top - y1 * scale + (inner_h - mh * scale) / 2
            return (scale, dx, dy)
        scale = min(inner_w / mw, inner_h / mh)
        dx = pad_x + (inner_w - mw * scale) / 2
        dy = pad_y_top + (inner_h - mh * scale) / 2
        return (scale, dx, dy)

    def _paint_zone(self, p: QPainter, z, idx: int) -> None:
        scale, dx, dy = self._scale_xform()
        fill = QColor(t.ACCENT)
        fill.setAlphaF(0.18)
        stroke = QColor(t.ACCENT)
        p.setPen(QPen(stroke, 1.5))
        p.setBrush(QBrush(fill))

        if z.shape == "rect":
            x1, y1, x2, y2 = z.rect
            r = QRectF(x1 * scale + dx, y1 * scale + dy,
                       (x2 - x1) * scale, (y2 - y1) * scale)
            p.drawRoundedRect(r, 3, 3)
            anchor = (r.left(), r.top())
        elif z.shape == "circle":
            cx, cy, radius = z.circle
            r = QRectF((cx - radius) * scale + dx,
                       (cy - radius) * scale + dy,
                       radius * 2 * scale, radius * 2 * scale)
            p.drawEllipse(r)
            anchor = (r.left(), r.top())
        else:
            path = QPainterPath()
            verts = z.vertices
            if verts:
                path.moveTo(verts[0][0] * scale + dx, verts[0][1] * scale + dy)
                for vx, vy in verts[1:]:
                    path.lineTo(vx * scale + dx, vy * scale + dy)
                path.closeSubpath()
            p.drawPath(path)
            x1, y1, _, _ = z.aabb()
            anchor = (x1 * scale + dx, y1 * scale + dy)

        if self._show_indices:
            self._paint_badge(p, idx + 1, anchor)

    def _paint_badge(self, p: QPainter, n: int, anchor: Tuple[float, float]) -> None:
        font = QFont(t.FONT_MONO.split(",")[0].strip(), 8)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetrics(font)
        text = f"#{n}"
        tw = fm.horizontalAdvance(text) + 8
        th = fm.height() + 2
        x, y = anchor
        bg = QColor(t.ACCENT)
        rect = QRectF(x + 2, y + 2, tw, th)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(QPen(QColor("#1a0510")))
        p.drawText(rect.adjusted(4, 1, 0, -1),
                   Qt.AlignVCenter | Qt.AlignLeft, text)

    def _readout_text(self) -> str:
        n = len(self._zones)
        if n == 0:
            return ""
        if n == 1:
            z = self._zones[0]
            if z.shape == "rect":
                x1, y1, x2, y2 = z.rect
                return f"{x1},{y1} → {x2},{y2} · {x2-x1}×{y2-y1} px"
            if z.shape == "circle":
                cx, cy, radius = z.circle
                return f"{cx},{cy} · r={radius} px"
            x1, y1, x2, y2 = z.aabb()
            return f"{len(z.vertices)} corners · {x2-x1}×{y2-y1} px"
        return f"{n} zones"

    def _paint_readout_pill(self, p: QPainter) -> None:
        text = self._readout_text()
        if not text:
            return
        font = QFont(t.FONT_MONO.split(",")[0].strip(), 8)
        p.setFont(font)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad_x = 7
        pad_y = 3
        pill_w = tw + pad_x * 2
        pill_h = th + pad_y * 2
        x = self.width() - pill_w - 8
        y = self.height() - pill_h - 7
        bg = QColor(0, 0, 0, int(0.65 * 255))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(x, y, pill_w, pill_h), 4, 4)
        p.setPen(QPen(QColor(t.TEXT_PRIMARY)))
        p.drawText(QPointF(x + pad_x, y + pad_y + fm.ascent()), text)
