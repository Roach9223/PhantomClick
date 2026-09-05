"""Zone map: every attached monitor drawn to scale, with the click zone,
recent clicks and hover zones placed on it. It is also the monitor
picker: click a monitor to make it the engine's target (what the
viewport shows and where the fullscreen drawers open); right-click for
the same list plus AUTO, which follows the click zone.

It reads as a tactical plot: bracketed corners, monitors as outlines,
clicks as contacts that fade with age, and a sweep that turns around the
zone only while the engine runs. The sweep is the deck's one moving
element; it exists to say "running" from across the room and stops the
moment the engine does (see the motion note in ``ui/theme.py``).

Geometry comes from Qt's ``QScreen`` list (DIP space, same as zones), so
the map never needs the physical-pixel conversion the capture path does.
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QConicalGradient, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from modules.clicker import ClickerState
from ui.config_io import DEFAULTS

from . import common as c

_MARGIN = 12
_RING_MIN_PX, _RING_MAX_PX = 12, 40
_BRACKET = 10
_CONTACT_FADE_S = 45.0
_SWEEP_FPS = 30
MAP_H = 150


def _brackets(p: QPainter, r: QRectF, color: str, arm: float = _BRACKET, width: float = 1.0) -> None:
    """Four L-shaped corner marks just inside ``r``. Shared by the map
    and the viewport so every frame on the deck wears the same corners."""
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCosmetic(True)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(pen)
    left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
    for (x, y, dx, dy) in ((left, top, 1, 1), (right, top, -1, 1),
                           (left, bottom, 1, -1), (right, bottom, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
    p.restore()


class ZoneMap(QWidget):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setFixedHeight(MAP_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Every monitor to scale, with the click zone, recent clicks and "
            "hover zones. Click a monitor to make it the target the viewport "
            "shows and the engine captures; right-click for AUTO, which "
            "follows the click zone. The sweep turns while the engine runs.")
        # Monitor hit rects from the last paint, in widget px.
        self._hits: list[tuple[QRectF, int]] = []
        # Sweep clock: runs only while the engine does.
        self._sweep = QTimer(self)
        self._sweep.setInterval(int(1000 / _SWEEP_FPS))
        self._sweep.timeout.connect(self.update)
        self._sweep_started = 0.0

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

    def _running(self) -> bool:
        return self.app._state_str != ClickerState.IDLE

    def sweep_active(self) -> bool:
        return self._sweep.isActive()

    def sync_sweep(self) -> None:
        """Start the sweep clock when the engine runs, stop it when it
        stops. Called from the column tick (10 Hz), so a run shows its
        sweep within 100 ms and an idle deck paints nothing that moves."""
        running = self._running() and self.isVisible()
        if running and not self._sweep.isActive():
            self._sweep_started = time.monotonic()
            self._sweep.start()
        elif not running and self._sweep.isActive():
            self._sweep.stop()
            self.update()

    def hideEvent(self, event):  # noqa: N802 (Qt name)
        super().hideEvent(event)
        self._sweep.stop()

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
        auto = QAction("Auto (follow the click zone)", menu)
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
        running = self._running()
        well = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(well, QColor(c.SURFACE_PANEL))
        _brackets(p, well, c.RUN if running else c.BORDER_STRONG)

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

        # Monitors. The target is ice-framed and says so; the others are
        # plain wells the user can click.
        p.setFont(c.label_font(c.SIZE_XS - 1, QFont.DemiBold, 0.6))
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
            if is_target and r.width() >= 78:
                tag += " " + ("TGT" if explicit else "AUTO")
            p.drawText(int(r.left()) + 4, int(r.top()) + 11, tag)
            if r.height() > 26 and r.width() >= 70:
                p.setFont(c.mono_font(c.SIZE_XS - 1))
                p.setPen(QColor(c.TEXT_MICRO))
                p.drawText(int(r.left()) + 4, int(r.top()) + 22, f"{w}x{h}")
                p.setFont(c.label_font(c.SIZE_XS - 1, QFont.DemiBold, 0.6))

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

        # Zone marker, sweep and contacts at the window-lock-resolved spot.
        zone, status, _title = c.lock_view(self.app)
        if zone is None and self.app._active_mode != "clicker":
            for s in getattr(self.app, "_steps", []) or []:
                if getattr(s, "zone", None) is not None:
                    zone = s.zone
                    break
        radius = float(self.app.cfg.get("anti_cluster_radius", DEFAULTS["anti_cluster_radius"]))
        ring = int(c.clamp(radius * scale, _RING_MIN_PX, _RING_MAX_PX))
        if zone is not None:
            holding = status in ("lost", "minimized")
            color = c.WARN if holding else c.ACCENT
            cx, cy = zone.centroid()
            px, py = to_px(cx, cy)
            if running and self._sweep.isActive() and not holding:
                self._paint_sweep(p, px, py, ring * 1.8)
            # The ring radius is the anti-cluster radius in map scale, so
            # the rings say how far consecutive clicks are pushed apart.
            pm = c.icon_pixmap("mg130", ring * 2, color)
            p.setOpacity(0.55)
            p.drawPixmap(int(px - ring), int(py - ring), pm)
            p.setOpacity(1.0)
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(px - 3, py - 3, 6, 6))

        # Recent clicks as contacts: newest brightest, all fading with age.
        now = time.monotonic()
        p.setPen(Qt.NoPen)
        pts = self.app.click_ring.last(24)
        for i, (t0, x, y) in enumerate(pts):
            px, py = to_px(x, y)
            age = c.clamp(1.0 - (now - t0) / _CONTACT_FADE_S, 0.0, 1.0)
            rank = (i + 1) / max(1, len(pts))
            col = QColor(c.RUN if running else c.TEXT_PRIMARY)
            col.setAlpha(int(40 + 215 * max(age * 0.7, rank * 0.3)))
            p.setBrush(col)
            size = 3.0 if i == len(pts) - 1 else 2.0
            p.drawEllipse(QRectF(px - size / 2, py - size / 2, size, size))
        p.end()

    def _paint_sweep(self, p: QPainter, cx: float, cy: float, radius: float) -> None:
        """A conical fade behind a leading edge, one turn per
        SWEEP_PERIOD_MS, clipped to the well."""
        period = max(500.0, float(c.SWEEP_PERIOD_MS)) / 1000.0
        frac = ((time.monotonic() - self._sweep_started) % period) / period
        angle = 360.0 * frac
        grad = QConicalGradient(QPointF(cx, cy), 90.0 - angle)
        head = QColor(c.RUN)
        head.setAlpha(150)
        tail = QColor(c.RUN)
        tail.setAlpha(0)
        # Qt's conical gradient runs counter-clockwise from its angle; the
        # bright edge sits at 0 and fades over the following quarter turn.
        grad.setColorAt(0.0, head)
        grad.setColorAt(0.28, tail)
        grad.setColorAt(1.0, tail)
        p.save()
        p.setClipRect(self.rect().adjusted(1, 1, -1, -1))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        p.restore()


__all__ = ["ZoneMap", "MAP_H", "_brackets"]
