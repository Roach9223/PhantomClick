"""``BotOverlay`` — translucent click-through HUD that shows what the
bot "sees" at each tick.

The overlay paints, in screen coordinates:
- The active step's ROI rectangle (if any), so the user can verify the
  search region matches the on-screen feature.
- A small click marker at the last fire location, fading over a few
  ticks so the trail is readable but not noisy.
- A status badge in the top-left of the ROI: ``proc:pc — kind`` so the
  user knows where in the program flow the bot currently is.

Wired from ``BotRunner.block_executed`` (per-rule fire) and
``runner.tick_started`` (so the ROI updates even on dry ticks).
Toggled via the topbar 👁 button (same flag as zone overlays —
``cfg.show_zone_overlay``). When the bot stops, the overlay hides
itself; restart shows it again automatically when the toggle is on.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .. import theme as t


class BotOverlay(QWidget):
    """Single transparent widget covering the virtual desktop. Paints
    the bot's current ROI + last-fire marker + status badge. Shared
    across all bot runs — show/hide on bot start/stop."""

    # Click-trail keeps this many fire locations, fading by age.
    _TRAIL_LEN = 5
    _TRAIL_FADE_S = 2.0

    def __init__(self) -> None:
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

        # Cover the whole virtual desktop so any ROI on any monitor
        # paints inside our local coords.
        self._reposition_to_virtual_desktop()

        self._roi: Optional[Tuple[int, int, int, int]] = None
        self._roi_color = QColor(t.ACCENT)
        self._status: str = ""
        self._trail: list[tuple[int, int, float]] = []  # (x, y, ts_monotonic)

    # ── Public API ──────────────────────────────────────────────────

    def set_roi(self, roi: Optional[Tuple[int, int, int, int]],
                color: Optional[str] = None) -> None:
        """Update the highlighted ROI. ``roi = (x1, y1, x2, y2)`` in
        screen coords, or ``None`` to clear."""
        self._roi = tuple(roi) if roi else None
        if color:
            self._roi_color = QColor(color)
        self.update()

    def set_status(self, status: str) -> None:
        self._status = status or ""
        self.update()

    def add_fire(self, x: int, y: int) -> None:
        """Add a click trail marker at ``(x, y)`` in screen coords."""
        self._trail.append((int(x), int(y), time.monotonic()))
        if len(self._trail) > self._TRAIL_LEN:
            self._trail = self._trail[-self._TRAIL_LEN:]
        self.update()

    def clear(self) -> None:
        self._roi = None
        self._status = ""
        self._trail = []
        self.update()

    # ── Layout ──────────────────────────────────────────────────────

    def _reposition_to_virtual_desktop(self) -> None:
        screens = QApplication.screens()
        if not screens:
            return
        x1 = min(s.geometry().left() for s in screens)
        y1 = min(s.geometry().top() for s in screens)
        x2 = max(s.geometry().right() for s in screens)
        y2 = max(s.geometry().bottom() for s in screens)
        self.setGeometry(x1, y1, max(1, x2 - x1 + 1), max(1, y2 - y1 + 1))
        self._origin = (x1, y1)

    def showEvent(self, event):  # noqa: N802 (Qt signature)
        # Re-snap to the virtual desktop on each show in case a
        # monitor was added/removed since construction.
        self._reposition_to_virtual_desktop()
        super().showEvent(event)

    # ── Paint ──────────────────────────────────────────────────────

    def paintEvent(self, _event):  # noqa: N802
        if self._roi is None and not self._trail and not self._status:
            return
        ox, oy = self._origin
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # ROI rectangle.
        if self._roi is not None:
            x1, y1, x2, y2 = self._roi
            rect = QRect(int(x1) - ox, int(y1) - oy,
                         max(1, int(x2 - x1)), max(1, int(y2 - y1)))
            pen = QPen(self._roi_color)
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

            # Status badge above the ROI top-left.
            if self._status:
                self._draw_badge(
                    painter, rect.left(), rect.top() - 4, self._status,
                )

        # Click trail — fade older markers.
        now = time.monotonic()
        for x, y, ts in self._trail:
            age = max(0.0, now - ts)
            if age > self._TRAIL_FADE_S:
                continue
            alpha = int(255 * (1.0 - age / self._TRAIL_FADE_S))
            color = QColor(t.START)
            color.setAlpha(alpha)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
            cx, cy = int(x) - ox, int(y) - oy
            painter.drawEllipse(QPointF(cx, cy), 8.0, 8.0)
            painter.drawLine(cx - 12, cy, cx + 12, cy)
            painter.drawLine(cx, cy - 12, cx, cy + 12)

        painter.end()

    def _draw_badge(self, painter: QPainter, x: int, y: int, text: str) -> None:
        font = QFont(t.FONT_MONO, 9)
        font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        pad_x, pad_y = 8, 4
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        rect = QRect(x, y - th - 2 * pad_y, tw + 2 * pad_x, th + 2 * pad_y)
        bg = QColor(t.SURFACE_PANEL)
        bg.setAlpha(220)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(self._roi_color), 1))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QPen(QColor(t.TEXT_PRIMARY)))
        painter.drawText(
            rect.left() + pad_x,
            rect.top() + pad_y + fm.ascent(),
            text,
        )
