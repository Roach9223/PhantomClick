"""``ColorPicker`` — frozen-screen eyedropper, multi-sample.

Captures one screen into a QPixmap, paints it fullscreen, and lets the
user move the mouse to preview the pixel color under the cursor (with a
magnifier loupe for precision). Each click adds a sample to a stack;
Enter / Right-click commits the whole stack; Esc cancels.

Single sample stays the natural workflow — click once, press Enter (or
right-click) to save. For gradient targets like boon procs, just keep
clicking distinct shades; the stack indicator at the top of the banner
shows what's been captured so far.

Captures via ``mss`` so the bytes match what OpenCV / mss would see
elsewhere in the engine (avoids HiDPI scaling mismatches).

Single-screen scope is intentional: Qt6 doesn't render one window
cleanly across monitors with different DPI scales. A union-of-all-
screens overlay would look grey-but-unresponsive on the secondary
monitor when the primary has a different DPR — exactly the lock-up
the ZoneDrawer hit, fixed there for the same reason. Caller can re-
launch the picker if they need to pick from a different screen.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter, QPen,
    QPixmap, QScreen,
)
from PySide6.QtWidgets import QApplication, QWidget

from .. import theme as t


# ColorPicker emits ``ColorPickResult`` instances (or ``None`` on
# cancel). The result is a thin container so callers can decide
# between using just the primary or the whole stack.
class ColorPickResult:
    """One commit out of the picker.

    ``samples`` is the ordered list of (r, g, b) triples the user
    clicked (always non-empty on a successful commit). ``primary``
    is the first sample for convenience. ``last_xy`` is the final
    click position in absolute screen coordinates — useful when the
    caller wants a witness pixel to anchor a JSON record on.
    """

    __slots__ = ("samples", "primary", "last_xy")

    def __init__(
        self,
        samples: List[Tuple[int, int, int]],
        last_xy: Tuple[int, int],
    ) -> None:
        self.samples = list(samples)
        self.primary = samples[0]
        self.last_xy = last_xy

    # Tuple-like unpacking so older callers that wrote
    #     (rgb, x, y) = result
    # still work as long as they treat the first element as RGB.
    def __iter__(self):
        yield self.primary
        yield self.last_xy[0]
        yield self.last_xy[1]

    def __getitem__(self, idx):
        if idx == 0:
            return self.primary
        if idx == 1:
            return self.last_xy[0]
        if idx == 2:
            return self.last_xy[1]
        raise IndexError(idx)


class ColorPicker(QWidget):
    """Multi-sample eyedropper. Emits ``ColorPickResult`` or ``None``."""
    finished = Signal(object)

    def __init__(self, screen: Optional[QScreen] = None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        # Bind to a single screen — same mixed-DPI workaround as ZoneDrawer.
        if screen is None:
            try:
                cursor_pos = QCursor.pos()
            except Exception:
                cursor_pos = QApplication.primaryScreen().geometry().center()
            screen = (
                QApplication.screenAt(cursor_pos)
                or QApplication.primaryScreen()
            )
        self._screen = screen
        geom = screen.geometry()
        self._origin = (geom.left(), geom.top())
        self.setGeometry(geom)
        self.create()
        wh = self.windowHandle()
        if wh is not None:
            wh.setScreen(screen)
            self.setGeometry(geom)

        self._pixmap: Optional[QPixmap] = None
        self._image: Optional[QImage] = None
        self._cursor_pos: Optional[QPoint] = None
        self._keyboard_grabbed: bool = False
        # Multi-sample stack — one (r, g, b) per click.
        self._samples: List[Tuple[int, int, int]] = []
        self._last_click_xy: Optional[Tuple[int, int]] = None
        self._capture()

    def _capture(self) -> None:
        try:
            import mss
            from utils.dpi_cursor import dip_rect_to_physical

            # Qt's screen.geometry() returns DIPs (logical pixels), but mss
            # expects physical pixels. On a DPR>1 monitor (e.g. 4K at 150%)
            # passing DIP coords to mss grabs only the top-left portion of
            # the actual physical screen — the user sees the picker
            # "cut off" the right and bottom of their game. Convert via
            # the rect-aware helper so the entire physical monitor is
            # captured. Mirror fix to ai_captures._grab_full_frame.
            geom = self._screen.geometry()
            px, py, pw, ph = dip_rect_to_physical(
                geom.left(), geom.top(),
                geom.width(), geom.height(),
            )
            region = {"left": px, "top": py, "width": pw, "height": ph}
            with mss.mss() as sct:
                shot = sct.grab(region)
                w, h = shot.width, shot.height
                img = QImage(shot.bgra, w, h, QImage.Format_ARGB32).copy()
            # Tag the pixmap with the screen's DPR so Qt draws it at
            # the right size in the widget's logical-pixel coord space.
            try:
                dpr = float(self._screen.devicePixelRatio())
            except Exception:
                dpr = 1.0
            self._image = img
            pix = QPixmap.fromImage(img)
            if dpr > 0:
                pix.setDevicePixelRatio(dpr)
            self._pixmap = pix
            self._dpr = dpr
        except Exception:
            self._image = None
            self._pixmap = None
            self._dpr = 1.0

    # -- Lifecycle -------------------------------------------------------

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
        """Release the keyboard grab. Called from both ``closeEvent``
        and at the top of ``cancel()`` / ``_commit_stack()`` so any
        QInputDialog spawned by the ``finished`` callback receives
        keystrokes immediately — without this, the still-alive picker
        keeps the keyboard until its deferred close finishes, leaving
        the asset-name prompt unable to receive input."""
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

    def _commit_stack(self) -> None:
        if not self._samples or self._last_click_xy is None:
            self.cancel()
            return
        self._release_keyboard()
        result = ColorPickResult(self._samples, self._last_click_xy)
        self.finished.emit(result)
        self.close()

    def _pixel_rgb(self, x: int, y: int) -> Optional[Tuple[int, int, int]]:
        """Read the underlying pixel at screen DIP coords (x, y).

        The captured image is in PHYSICAL pixels (DPR-scaled), so DIP
        coordinates from the mouse must be scaled by DPR before
        indexing into the image.
        """
        if self._image is None:
            return None
        ox, oy = self._origin
        dpr = getattr(self, "_dpr", 1.0) or 1.0
        # DIP → physical-px offset within the captured image.
        local_x = int(round((x - ox) * dpr))
        local_y = int(round((y - oy) * dpr))
        if not (0 <= local_x < self._image.width()
                and 0 <= local_y < self._image.height()):
            return None
        c = QColor(self._image.pixel(local_x, local_y))
        return (c.red(), c.green(), c.blue())

    # -- Keyboard / mouse ------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancel()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit_stack()
        elif event.key() == Qt.Key_Backspace and self._samples:
            # Undo last sample so the user can recover from a misclick.
            self._samples.pop()
            self.update()

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        ox, oy = self._origin
        if event.button() == Qt.LeftButton:
            sx = int(event.position().x() + ox)
            sy = int(event.position().y() + oy)
            rgb = self._pixel_rgb(sx, sy)
            if rgb is None:
                return
            self._samples.append(rgb)
            self._last_click_xy = (sx, sy)
            self.update()
        elif event.button() == Qt.RightButton:
            # Right-click: commit if we have samples, cancel if not.
            if self._samples:
                self._commit_stack()
            else:
                self.cancel()

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        self._cursor_pos = event.position().toPoint()
        self.update()

    # -- Painting --------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        if self._pixmap is None:
            p.fillRect(self.rect(), QColor("#0d0f12"))
            p.setPen(QColor("#ededed"))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Failed to capture screen — Esc to cancel.")
            return
        p.drawPixmap(0, 0, self._pixmap)
        p.fillRect(self.rect(), QColor(0, 0, 0, 40))

        if self._cursor_pos is not None:
            self._draw_loupe(p, self._cursor_pos)

        self._draw_banner(p)

    def _draw_banner(self, p: QPainter) -> None:
        banner_h = 44
        p.fillRect(0, 0, self.width(), banner_h, QColor(0, 0, 0, 200))
        p.setPen(QColor("#ededed"))
        p.setFont(QFont(t.FONT_FAMILY.split(",")[0].strip(), 10, QFont.DemiBold))
        if not self._samples:
            hint = (
                "Click to pick a color  ·  add multiple to stack a sample set  "
                "·  Right-click / Enter to save  ·  Esc to cancel"
            )
            p.drawText(
                QRect(0, 0, self.width(), banner_h),
                Qt.AlignCenter, hint,
            )
            return
        # Sample swatches + count + hint.
        count_text = f"{len(self._samples)} sample{'s' if len(self._samples) > 1 else ''}"
        p.drawText(
            QRect(12, 0, 160, banner_h),
            Qt.AlignVCenter | Qt.AlignLeft, count_text,
        )
        # Swatch row — small filled squares so the user sees what they've stacked.
        sw = 18
        sh = 18
        gap = 4
        x = 180
        y = (banner_h - sh) // 2
        for r, g, b in self._samples[-10:]:  # last 10 if huge
            p.setPen(QPen(QColor("#ffffff"), 1))
            p.setBrush(QColor(r, g, b))
            p.drawRect(x, y, sw, sh)
            x += sw + gap
        # Right-aligned hint.
        hint = "  Click to add  ·  Backspace = undo  ·  Enter / right-click = save  ·  Esc cancel"
        p.drawText(
            QRect(0, 0, self.width(), banner_h),
            Qt.AlignVCenter | Qt.AlignRight, hint,
        )

    def _draw_loupe(self, p: QPainter, pos: QPoint) -> None:
        if self._image is None:
            return
        ox, oy = self._origin
        sx, sy = pos.x(), pos.y()
        rgb = self._pixel_rgb(sx + ox, sy + oy)
        if rgb is None:
            return
        loupe_size = 120
        zoom_radius_px = 8
        offset = QPoint(28, 28)
        rect = QRect(pos + offset, QPoint(pos.x() + offset.x() + loupe_size,
                                          pos.y() + offset.y() + loupe_size))
        # QPixmap.copy() indexes the underlying image in PHYSICAL pixel
        # coords (devicePixelRatio is a render hint, not a slicing one).
        # Scale the DIP-space source rect by DPR so the loupe samples
        # the same on-screen region the cursor's actually over.
        dpr = getattr(self, "_dpr", 1.0) or 1.0
        src_radius = int(round(zoom_radius_px * dpr))
        src_size = src_radius * 2 + 1
        src_rect = QRect(
            int(round(sx * dpr)) - src_radius,
            int(round(sy * dpr)) - src_radius,
            src_size, src_size,
        )
        sub = self._pixmap.copy(src_rect)
        scaled = sub.scaled(loupe_size, loupe_size,
                            Qt.IgnoreAspectRatio, Qt.FastTransformation)
        p.setPen(QPen(QColor(t.ACCENT), 2))
        p.setBrush(QColor(0, 0, 0, 220))
        p.drawRoundedRect(rect.adjusted(-4, -4, 4, 32), 6, 6)
        p.drawPixmap(rect, scaled)
        cx = rect.center().x()
        cy = rect.center().y()
        p.setPen(QPen(QColor(t.ACCENT), 1))
        p.drawLine(cx - 8, cy, cx + 8, cy)
        p.drawLine(cx, cy - 8, cx, cy + 8)
        readout = f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
        p.setPen(QColor("#ededed"))
        p.drawText(QRect(rect.left(), rect.bottom() + 6,
                         loupe_size, 24),
                   Qt.AlignCenter, readout)
