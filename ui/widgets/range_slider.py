"""``RangeSlider`` — dual-thumb min/max slider.

Qt ships no native range slider, so this is a custom-painted ``QWidget``.
Track + filled-range + two thumbs, mouse-drag updates whichever thumb
the cursor is closer to. Emits a ``valueChanged(min, max)`` signal that
mirrors the original CTk RangeSlider's callback shape.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QMouseEvent
from PySide6.QtWidgets import QWidget, QSizePolicy

from .. import theme as t


_TRACK_H = 4
_THUMB_R = 8
_HEIGHT = 28


class RangeSlider(QWidget):
    valueChanged = Signal(float, float)

    def __init__(
        self,
        from_: float = 0.0,
        to: float = 1.0,
        steps: int = 100,
        init_min: float | None = None,
        init_max: float | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._min, self._max = float(from_), float(to)
        self._steps = max(1, int(steps))
        self._lo = float(init_min if init_min is not None else from_)
        self._hi = float(init_max if init_max is not None else to)
        self._lo, self._hi = self._clamp(self._lo, self._hi)
        self._dragging: str | None = None  # "lo" | "hi" | None
        self.setMinimumHeight(_HEIGHT)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    # -- Public API --------------------------------------------------------

    def set_range(self, from_: float, to: float) -> None:
        self._min, self._max = float(from_), float(to)
        self._lo, self._hi = self._clamp(self._lo, self._hi)
        self.update()

    def set_values(self, lo: float, hi: float) -> None:
        new_lo, new_hi = self._clamp(float(lo), float(hi))
        if (new_lo, new_hi) != (self._lo, self._hi):
            self._lo, self._hi = new_lo, new_hi
            self.update()
            self.valueChanged.emit(self._lo, self._hi)
        else:
            self._lo, self._hi = new_lo, new_hi
            self.update()

    def values(self) -> tuple[float, float]:
        return self._lo, self._hi

    # -- Internal ----------------------------------------------------------

    def _clamp(self, lo: float, hi: float) -> tuple[float, float]:
        lo = max(self._min, min(self._max, lo))
        hi = max(self._min, min(self._max, hi))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi

    def _value_to_x(self, v: float) -> float:
        if self._max == self._min:
            return _THUMB_R
        usable = self.width() - 2 * _THUMB_R
        return _THUMB_R + (v - self._min) / (self._max - self._min) * usable

    def _x_to_value(self, x: float) -> float:
        usable = max(1, self.width() - 2 * _THUMB_R)
        frac = (x - _THUMB_R) / usable
        v = self._min + frac * (self._max - self._min)
        # Quantize to ``steps`` for predictable values.
        step_size = (self._max - self._min) / self._steps
        if step_size > 0:
            v = round(v / step_size) * step_size
        return max(self._min, min(self._max, v))

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        # Track
        track = QRectF(_THUMB_R, cy - _TRACK_H / 2,
                       self.width() - 2 * _THUMB_R, _TRACK_H)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.SURFACE_HIGH))
        p.drawRoundedRect(track, 2, 2)
        # Filled range
        x_lo = self._value_to_x(self._lo)
        x_hi = self._value_to_x(self._hi)
        filled = QRectF(x_lo, cy - _TRACK_H / 2, x_hi - x_lo, _TRACK_H)
        p.setBrush(QColor(t.ACCENT))
        p.drawRoundedRect(filled, 2, 2)
        # Thumbs
        for x in (x_lo, x_hi):
            p.setBrush(QColor(t.ACCENT))
            p.drawEllipse(QRectF(x - _THUMB_R, cy - _THUMB_R,
                                  _THUMB_R * 2, _THUMB_R * 2))

    # -- Mouse handling ---------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x = event.position().x()
        x_lo = self._value_to_x(self._lo)
        x_hi = self._value_to_x(self._hi)
        # Pick the closer thumb. Tie goes to "hi" so dragging from the right
        # of the bar feels natural.
        self._dragging = "lo" if abs(x - x_lo) < abs(x - x_hi) else "hi"
        self._handle_drag(x)

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        if self._dragging is None:
            return
        self._handle_drag(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        self._dragging = None

    def _handle_drag(self, x: float) -> None:
        v = self._x_to_value(x)
        if self._dragging == "lo":
            self._lo = min(v, self._hi)
        else:
            self._hi = max(v, self._lo)
        self.update()
        self.valueChanged.emit(self._lo, self._hi)
