"""``FrozenFrameDrawer`` — fullscreen overlay showing a *pre-captured*
frame as an opaque background, with rect-drag selection on top.

Used by the "Capture frame" hotkey (default F9). The game underneath
is hidden by a still image; the user drags a rectangle anywhere on
the frozen pixels and the result is cropped from the captured frame
(not re-captured live), so what they draw is exactly what they see.

Sibling of :class:`ZoneDrawer`. Differences worth calling out:

- **Background is the captured frame**, not a translucent scrim. This
  is the "freeze" — pixels stop updating, the cursor is still free
  to move, the user can take their time framing the crop.
- **Cursor marker** — a teal ring drawn at the cursor position at the
  moment the hotkey fired. Helpful when capturing tooltips that
  appeared while hovering an in-game element: the marker shows where
  the cursor was so the user remembers the anchor.
- **Single-screen scope** — same Qt6 mixed-DPI workaround as
  ZoneDrawer / ColorPicker. The captured frame must be for the same
  screen the drawer is bound to.
- **Output is PHYSICAL pixels** — matches the rest of the capture
  pipeline (see ``project_capture_units_physical_px`` memory).
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap, QScreen,
)
from PySide6.QtWidgets import QApplication, QWidget

import numpy as np

from utils.dpi_cursor import dip_to_physical, physical_to_dip

from .. import theme as t


class FrozenFrameDrawer(QWidget):
    """Emits ``(x, y, w, h)`` rect in PHYSICAL pixels on commit, or
    ``None`` on cancel. Caller supplies the frame as a numpy BGR
    ndarray (physical-px on the bound screen) plus the cursor xy at
    capture time."""

    finished = Signal(object)

    def __init__(
        self,
        frame: np.ndarray,
        *,
        cursor_xy: Tuple[int, int] = (0, 0),
        screen: Optional[QScreen] = None,
    ):
        super().__init__(None)
        self._frame = frame
        self._cursor_xy_physical: Tuple[int, int] = (
            int(cursor_xy[0]), int(cursor_xy[1])
        )
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        # Bind to the screen the frame was captured from. Mixed-DPI
        # across monitors makes a single-window-spanning-both-screens
        # overlay misrender — see ZoneDrawer for the full story.
        if screen is None:
            try:
                from PySide6.QtGui import QCursor
                cursor_pos = QCursor.pos()
            except Exception:
                cursor_pos = QApplication.primaryScreen().geometry().center()
            screen = (
                QApplication.screenAt(cursor_pos)
                or QApplication.primaryScreen()
            )
        self._screen = screen
        geom = screen.geometry()
        self._origin_dip = (geom.left(), geom.top())
        self.setGeometry(geom)
        self.create()
        wh = self.windowHandle()
        if wh is not None:
            wh.setScreen(screen)
            self.setGeometry(geom)

        # BGR ndarray → QImage → QPixmap, scaled to the widget's
        # logical size on display. Qt handles the physical-to-logical
        # blit at draw time via devicePixelRatio.
        self._pixmap = _frame_to_pixmap(frame)
        self._dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
        if self._pixmap is not None:
            self._pixmap.setDevicePixelRatio(self._dpr)

        # Cursor marker — convert the cursor's physical xy to DIPs in
        # this screen's coordinate space so we can draw it.
        self._cursor_marker_dip: Optional[Tuple[int, int]] = None
        try:
            dip_x, dip_y = physical_to_dip(
                self._cursor_xy_physical[0],
                self._cursor_xy_physical[1],
            )
            # Translate from virtual-desktop DIPs to this widget's
            # local coords (widget is at screen geometry's origin).
            local_x = dip_x - self._origin_dip[0]
            local_y = dip_y - self._origin_dip[1]
            self._cursor_marker_dip = (int(local_x), int(local_y))
        except Exception:
            pass

        # Drag state.
        self._start: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._dragging = False
        self._keyboard_grabbed = False

    # -- Lifecycle ---------------------------------------------------

    def showEvent(self, event):  # noqa: N802
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

    def _commit(self) -> None:
        self._release_keyboard()
        if self._start is None or self._current is None:
            self.finished.emit(None)
            self.close()
            return
        ox, oy = self._origin_dip
        x1 = self._start.x() + ox
        y1 = self._start.y() + oy
        x2 = self._current.x() + ox
        y2 = self._current.y() + oy
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        if (x2 - x1) < 4 or (y2 - y1) < 4:
            self.finished.emit(None)
            self.close()
            return
        # DIP → physical px so saved rects match the rest of the
        # capture pipeline (mss + bot ROIs all in physical px).
        px1, py1 = dip_to_physical(x1, y1)
        px2, py2 = dip_to_physical(x2, y2)
        pw = max(1, px2 - px1)
        ph = max(1, py2 - py1)
        self.finished.emit((int(px1), int(py1), int(pw), int(ph)))
        self.close()

    # -- Keyboard ----------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancel()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()

    # -- Mouse -------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() == Qt.RightButton:
            self.cancel()
            return
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        self._start = pos
        self._current = pos
        self._dragging = True
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        if self._dragging:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._current = event.position().toPoint()
        self._commit()

    # -- Painting ----------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        if self._pixmap is not None:
            # Paint the frozen frame across the whole widget.
            p.drawPixmap(self.rect(), self._pixmap)
        else:
            # Fallback: black background + hint.
            p.fillRect(self.rect(), QColor("#0d0f12"))
            p.setPen(QColor("#ededed"))
            p.drawText(
                self.rect(),
                Qt.AlignCenter,
                "Failed to load captured frame — Esc to cancel.",
            )

        # Subtle scrim to make the rect outline pop.
        if self._start and self._current:
            r = QRect(self._start, self._current).normalized()
            # Dim everything outside the rect; keep inside pristine.
            p.save()
            p.setBrush(QColor(0, 0, 0, 120))
            p.setPen(Qt.NoPen)
            # Top, bottom, left, right slabs around the rect.
            full = self.rect()
            p.drawRect(full.left(), full.top(),
                       full.width(), r.top() - full.top())
            p.drawRect(full.left(), r.bottom(),
                       full.width(), full.bottom() - r.bottom())
            p.drawRect(full.left(), r.top(),
                       r.left() - full.left(), r.height())
            p.drawRect(r.right(), r.top(),
                       full.right() - r.right(), r.height())
            p.restore()
            # Rect outline.
            accent = QColor(t.ACCENT)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)

        # Cursor marker — small teal ring at the pre-hotkey cursor xy.
        if self._cursor_marker_dip is not None:
            cx, cy = self._cursor_marker_dip
            p.setPen(QPen(QColor(t.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPoint(cx, cy), 12, 12)
            # Inner dot for precision.
            p.setBrush(QColor(t.ACCENT))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(cx, cy), 2, 2)

        # Hint banner at the top.
        banner_h = 40
        p.fillRect(0, 0, self.width(), banner_h, QColor(0, 0, 0, 200))
        p.setPen(QColor("#ededed"))
        from PySide6.QtGui import QFont
        font = QFont(t.FONT_FAMILY.split(",")[0].strip(), 10, QFont.DemiBold)
        p.setFont(font)
        p.drawText(
            QRect(0, 0, self.width(), banner_h),
            Qt.AlignCenter,
            "Drag to crop the frozen frame  ·  Enter saves  ·  Esc / right-click cancels",
        )


def _frame_to_pixmap(frame: np.ndarray) -> Optional[QPixmap]:
    """BGR uint8 ndarray → QPixmap. Returns None on a malformed input."""
    if frame is None:
        return None
    try:
        if frame.ndim != 3 or frame.shape[2] not in (3, 4) or frame.size == 0:
            return None
        # Convert BGR(A) → RGB(A) so QImage interprets channels correctly.
        if frame.shape[2] == 4:
            rgb = np.ascontiguousarray(frame[..., [2, 1, 0, 3]])
            fmt = QImage.Format_RGBA8888
        else:
            rgb = np.ascontiguousarray(frame[..., ::-1])
            fmt = QImage.Format_RGB888
        h, w = rgb.shape[:2]
        stride = rgb.strides[0]
        # ``.copy()`` so the QImage owns its buffer — the ndarray
        # passed in may be freed by the caller after this call.
        img = QImage(rgb.data, w, h, stride, fmt).copy()
        return QPixmap.fromImage(img)
    except Exception:
        return None
