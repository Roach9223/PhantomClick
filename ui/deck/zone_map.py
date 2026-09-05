"""Zone map: every attached monitor drawn to scale, with the click zone,
recent clicks and hover zones placed on it. It is also the monitor
picker: click a monitor to make it the engine's target (what the
viewport shows and where the fullscreen drawers open); right-click for
the same list plus AUTO, which follows the click area.

Geometry comes from Qt's ``QScreen`` list (DIP space, same as zones), so
the map never needs the physical-pixel conversion the capture path does.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from ui.config_io import DEFAULTS

from . import common as c

_MARGIN = 10
_RING_MIN_PX, _RING_MAX_PX = 12, 40
MAP_H = 150


class ZoneMap(QWidget):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setFixedHeight(MAP_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Every monitor to scale. Click one to make it the target the "
            "viewport shows and the engine captures; right-click for AUTO, "
            "which follows the click area.")
        # Monitor hit rects from the last paint, in widget px.
        self._hits: list[tuple[QRectF, int]] = []

    # -- Data ------------------------------------------------------------------

    def _screen_rects(self) -> list[tuple[int, int, int, int]]:
        out = []
        try:
            for s in QApplication.instance().screens():
                g = s.geometry()
                out.append((g.left(), g.top(), g.width(), g.height()))
        except Exception:
            pass
        return out or [(0, 0, 1920, 1080)]

    def _target_index(self) -> Optional[int]:
        """0-based index of the monitor the engine targets right now."""
        try:
            x, y, w, h = self.app.target_screen_bounds()
            for i, r in enumerate(self._screen_rects()):
                if r == (x, y, w, h):
                    return i
        except Exception:
            pass
        return None

    def _explicit(self) -> bool:
        return str(self.app.cfg.get("target_monitor", "auto")) != "auto"

    # -- Interaction -------------------------------------------------------------

    def _monitor_at(self, pos) -> Optional[int]:
        for rect, idx in self._hits:
            if rect.contains(pos):
                return idx
        return None

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            idx = self._monitor_at(event.position())
            if idx is not None:
                self.app.set_target_monitor(idx)
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802 (Qt name)
        menu = QMenu(self)
        idx = self.app._explicit_target_screen_index()
        cur = "auto" if idx is None else str(idx)
        auto = QAction("Auto (follow the click area)", menu)
        auto.setCheckable(True)
        auto.setChecked(cur == "auto")
        auto.triggered.connect(lambda: self.app.set_target_monitor("auto"))
        menu.addAction(auto)
        menu.addSeparator()
        for i, (_x, _y, w, h) in enumerate(self._screen_rects()):
            act = QAction(f"MON{i + 1}  {w} x {h}", menu)
            act.setCheckable(True)
            act.setChecked(cur == str(i))
            act.triggered.connect(lambda _c=False, n=i: self.app.set_target_monitor(n))
            menu.addAction(act)
        menu.exec(event.globalPos())

    # -- Painting ----------------------------------------------------------------

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        screens = self._screen_rects()
        ux = min(r[0] for r in screens)
        uy = min(r[1] for r in screens)
        ur = max(r[0] + r[2] for r in screens)
        ub = max(r[1] + r[3] for r in screens)
        uw, uh = max(1, ur - ux), max(1, ub - uy)
        avail_w = max(1, self.width() - 2 * _MARGIN)
        avail_h = max(1, self.height() - 2 * _MARGIN)
        scale = min(avail_w / uw, avail_h / uh)
        ox = _MARGIN + (avail_w - uw * scale) / 2
        oy = _MARGIN + (avail_h - uh * scale) / 2

        def to_px(x: float, y: float) -> tuple[float, float]:
            return ox + (x - ux) * scale, oy + (y - uy) * scale

        target = self._target_index()
        explicit = self._explicit()
        self._hits = []

        # Monitors. The target is lime-framed and says so; the others are
        # plain wells the user can click.
        p.setFont(c.mono_font(c.SIZE_XS - 1, QFont.DemiBold))
        for i, (x, y, w, h) in enumerate(screens):
            ax, ay = to_px(x, y)
            r = QRectF(ax, ay, w * scale, h * scale)
            self._hits.append((r, i))
            is_target = i == target
            p.setPen(QPen(QColor(c.ACCENT if is_target else c.BORDER_STRONG), 1))
            p.setBrush(QColor(c.SURFACE_HIGH if is_target else c.SURFACE_PANEL))
            p.drawRect(r)
            p.setPen(QColor(c.ACCENT if is_target else c.TEXT_MICRO))
            tag = f"MON{i + 1}"
            if is_target:
                tag += " " + ("TARGET" if explicit else "AUTO")
            p.drawText(int(r.left()) + 4, int(r.top()) + 11, tag)
            if r.height() > 26:
                p.setPen(QColor(c.TEXT_MICRO))
                p.drawText(int(r.left()) + 4, int(r.top()) + 22, f"{w}x{h}")

        # Hover zones as dashed outlines.
        dash = QPen(QColor(c.BORDER_STRONG), 1, Qt.DashLine)
        p.setBrush(Qt.NoBrush)
        for hz in getattr(self.app, "_hover_zones", []) or []:
            try:
                x1, y1, x2, y2 = hz.aabb()
            except Exception:
                continue
            ax, ay = to_px(x1, y1)
            bx, by = to_px(x2, y2)
            p.setPen(dash)
            p.drawRect(QRectF(ax, ay, max(2.0, bx - ax), max(2.0, by - ay)))

        # Recent clicks.
        p.setPen(Qt.NoPen)
        pts = self.app.click_ring.last(24)
        for i, (_t, x, y) in enumerate(pts):
            px, py = to_px(x, y)
            col = QColor(c.TEXT_PRIMARY)
            col.setAlpha(int(90 + 165 * (i + 1) / max(1, len(pts))))
            p.setBrush(col)
            p.drawEllipse(QRectF(px - 1.0, py - 1.0, 2.0, 2.0))

        # Zone marker with radar rings, at the window-lock-resolved spot.
        zone, status, _title = c.lock_view(self.app)
        if zone is None and self.app._active_mode != "clicker":
            for s in getattr(self.app, "_steps", []) or []:
                if getattr(s, "zone", None) is not None:
                    zone = s.zone
                    break
        if zone is not None:
            color = c.WARN if status in ("lost", "minimized") else c.ACCENT
            cx, cy = zone.centroid()
            px, py = to_px(cx, cy)
            # The ring radius is the anti-cluster radius in map scale, so
            # the rings say how far consecutive clicks are pushed apart.
            radius = float(self.app.cfg.get("anti_cluster_radius", DEFAULTS["anti_cluster_radius"]))
            ring = int(c.clamp(radius * scale, _RING_MIN_PX, _RING_MAX_PX))
            pm = c.icon_pixmap("mg130", ring * 2, color)
            p.setOpacity(0.55)
            p.drawPixmap(int(px - ring), int(py - ring), pm)
            p.setOpacity(1.0)
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(px - 3, py - 3, 6, 6))
        p.end()
