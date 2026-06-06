"""``ZoneDrawer`` — fullscreen interactive overlay for drawing a zone.

Covers a single :class:`QScreen` with a translucent black scrim, then
lets the user paint:
- **Rect**: drag to draw a corner-to-corner rectangle.
- **Circle**: drag from center outward (release radius).
- **Polygon**: click to add vertices, double-click / right-click to close.

Esc cancels, Enter confirms (rect/circle commit on release).

The drawer captures keyboard + mouse, so its window is NOT click-through.
Returns the resulting :class:`Zone` via the ``finished`` signal.

Single-screen scope is intentional: Qt6's mixed-DPI behavior across a
window that spans monitors with different scales (e.g. 150% primary +
100% secondary) introduces small but visible offsets between the cursor
and the painted rectangle. Restricting the drawer to the screen the
cursor is on at draw-start means the entire window has a single uniform
DPR, which Qt renders cleanly.
"""

from __future__ import annotations

import math
import sys
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen,
    QScreen,
)
from PySide6.QtWidgets import QApplication, QWidget

from modules.zone_selector import Zone

from .. import theme as t


class ZoneDrawer(QWidget):
    finished = Signal(object)  # Zone or None

    def __init__(self, shape: str = "rect", screen: Optional[QScreen] = None):
        super().__init__(None)
        self._shape = shape
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # Bind to a single screen for uniform DPR. Caller can pass a
        # specific screen; otherwise we default to the cursor's current
        # screen at construction time.
        if screen is None:
            cursor_pos = QApplication.primaryScreen().geometry().center()
            try:
                from PySide6.QtGui import QCursor
                cursor_pos = QCursor.pos()
            except Exception:
                pass
            screen = QApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        self._screen = screen
        geom = screen.geometry()
        self._origin = (geom.left(), geom.top())
        self.setGeometry(geom)
        # Force the window onto this screen so Qt renders at its DPR.
        # ``windowHandle()`` is None until the widget is created, so we
        # call create() to instantiate it, then bind the screen.
        self.create()
        wh = self.windowHandle()
        if wh is not None:
            wh.setScreen(screen)
            # Re-apply geometry after the screen change so position is
            # accurate in physical-pixel terms on this monitor's DPR.
            self.setGeometry(geom)

        # Drawing state.
        self._start: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._verts: list[QPoint] = []  # for polygon
        self._dragging = False
        self._cursor_pos: Optional[QPoint] = None
        self._keyboard_grabbed: bool = False

    # -- Lifecycle --------------------------------------------------------

    def showEvent(self, event):  # noqa: N802
        """Force-grab the keyboard so Esc lands on the drawer no matter
        what window held focus when we spawned. Matches ColorPicker."""
        super().showEvent(event)
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        try:
            self.grabKeyboard()
            self._keyboard_grabbed = True
        except Exception:
            self._keyboard_grabbed = False

    def closeEvent(self, event):  # noqa: N802
        self._release_keyboard()
        super().closeEvent(event)

    def _release_keyboard(self) -> None:
        """Release the keyboard grab safely. Called both from
        ``closeEvent`` and at the top of ``cancel()`` / ``commit()``
        so any QInputDialog spawned by the ``finished`` callback
        receives keystrokes immediately, instead of waiting for the
        deferred ``closeEvent`` to actually run."""
        if self._keyboard_grabbed:
            try:
                self.releaseKeyboard()
            except Exception:
                pass
            self._keyboard_grabbed = False

    def cancel(self) -> None:
        self._release_keyboard()
        self.finished.emit(None)
        self.close()

    def commit(self, zone: Zone) -> None:
        self._release_keyboard()
        self.finished.emit(zone)
        self.close()

    # -- Keyboard --------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancel()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self._shape == "polygon" and len(self._verts) >= 3:
                self._commit_polygon()
            return

    # -- Mouse -----------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() != Qt.LeftButton and event.button() != Qt.RightButton:
            return
        pos = event.position().toPoint()
        if self._shape == "polygon":
            if event.button() == Qt.RightButton or event.type() == 4:  # right or double click
                if len(self._verts) >= 3:
                    self._commit_polygon()
                return
            self._verts.append(pos)
            self.update()
        else:
            self._start = pos
            self._current = pos
            self._dragging = True
            self.update()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if self._shape == "polygon" and len(self._verts) >= 3:
            self._commit_polygon()

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        pos = event.position().toPoint()
        self._cursor_pos = pos
        if self._dragging and self._shape != "polygon":
            self._current = pos
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        if not self._dragging or self._shape == "polygon":
            return
        self._dragging = False
        if self._start is None or self._current is None:
            return
        if self._shape == "rect":
            self._commit_rect()
        elif self._shape == "circle":
            self._commit_circle()

    # -- Commit helpers --------------------------------------------------

    def _commit_rect(self) -> None:
        ox, oy = self._origin
        x1 = self._start.x() + ox
        y1 = self._start.y() + oy
        x2 = self._current.x() + ox
        y2 = self._current.y() + oy
        if x1 > x2: x1, x2 = x2, x1
        if y1 > y2: y1, y2 = y2, y1
        if x2 - x1 < 4 or y2 - y1 < 4:
            self.cancel()
            return
        self.commit(Zone.make_rect(x1, y1, x2, y2))

    def _commit_circle(self) -> None:
        ox, oy = self._origin
        cx = self._start.x() + ox
        cy = self._start.y() + oy
        dx = self._current.x() - self._start.x()
        dy = self._current.y() - self._start.y()
        r = int(math.sqrt(dx * dx + dy * dy))
        if r < 4:
            self.cancel()
            return
        self.commit(Zone(shape="circle", circle=(cx, cy, r)))

    def _commit_polygon(self) -> None:
        ox, oy = self._origin
        verts = [(v.x() + ox, v.y() + oy) for v in self._verts]
        self.commit(Zone(shape="polygon", vertices=verts))

    # -- Painting --------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Scrim across the whole virtual desktop.
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))

        accent = QColor(t.ACCENT)
        # Cut a hole through the scrim where the user is drawing.
        if self._shape == "rect" and self._start and self._current:
            r = QRect(self._start, self._current).normalized()
            self._punch_rect(p, r)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        elif self._shape == "circle" and self._start and self._current:
            dx = self._current.x() - self._start.x()
            dy = self._current.y() - self._start.y()
            radius = int(math.sqrt(dx * dx + dy * dy))
            self._punch_circle(p, self._start, radius)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._start, radius, radius)
        elif self._shape == "polygon" and self._verts:
            path = QPainterPath()
            path.moveTo(self._verts[0])
            for v in self._verts[1:]:
                path.lineTo(v)
            if self._cursor_pos is not None:
                path.lineTo(self._cursor_pos)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            for v in self._verts:
                p.setBrush(accent)
                p.drawEllipse(v, 4, 4)

        # Hint text.
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(self.rect().adjusted(0, 24, 0, 0),
                   Qt.AlignTop | Qt.AlignHCenter,
                   self._hint_text())

    def _punch_rect(self, p: QPainter, r: QRect) -> None:
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(r, QColor(0, 0, 0, 255))
        p.restore()

    def _punch_circle(self, p: QPainter, center: QPoint, radius: int) -> None:
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setBrush(QColor(0, 0, 0, 255))
        p.setPen(Qt.NoPen)
        p.drawEllipse(center, radius, radius)
        p.restore()

    def _hint_text(self) -> str:
        if self._shape == "rect":
            return "Drag to draw a rectangle  ·  Esc to cancel"
        if self._shape == "circle":
            return "Drag from center outward  ·  Esc to cancel"
        return ("Click to add vertices  ·  Right-click / double-click / Enter "
                "to close  ·  Esc to cancel")
