"""``TickRuler``: the tick strip drawn beneath deck sliders.

Major ticks in BORDER_STRONG with a value label in TEXT_MICRO (9 px mono),
minor ticks in BORDER between them. The ruler is purely visual; it takes a
``(min, max)`` range, an optional value formatter, and a horizontal inset
so its ticks line up with the slider's usable track (thumb radius on each
side).

Used by :class:`LabeledSlider` and :class:`RangeSpinSlider`; both expose a
``show_ruler`` flag that defaults to True.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme as t


_HEIGHT = 16
_MAJOR_H = 6
_MINOR_H = 3


def _default_fmt(v: float) -> str:
    if abs(v) >= 100 or float(v).is_integer():
        return f"{int(round(v))}"
    if abs(v) >= 10:
        return f"{v:.0f}"
    return f"{v:.1f}".rstrip("0").rstrip(".")


class TickRuler(QWidget):
    def __init__(
        self,
        lo: float = 0.0,
        hi: float = 1.0,
        *,
        majors: int = 5,
        minors_per_major: int = 4,
        inset: float = 5.0,
        fmt: Optional[Callable[[float], str]] = None,
        log_scale: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._lo, self._hi = float(lo), float(hi)
        self._majors = max(2, int(majors))
        self._minors = max(0, int(minors_per_major))
        self._inset = float(inset)
        self._fmt = fmt or _default_fmt
        self._log = bool(log_scale)
        self.setFixedHeight(_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # -- Public API -------------------------------------------------------

    def set_range(self, lo: float, hi: float) -> None:
        self._lo, self._hi = float(lo), float(hi)
        self.update()

    def set_inset(self, inset: float) -> None:
        self._inset = float(inset)
        self.update()

    # -- Painting ---------------------------------------------------------

    def _value_at(self, frac: float) -> float:
        if self._log and self._lo > 0 and self._hi > self._lo:
            import math
            return self._lo * math.exp(frac * math.log(self._hi / self._lo))
        return self._lo + frac * (self._hi - self._lo)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        usable = max(1.0, w - 2 * self._inset)
        major_pen = QPen(QColor(t.BORDER_STRONG), 1)
        minor_pen = QPen(QColor(t.BORDER), 1)

        font = QFont(self.font())
        font.setFamily("JetBrains Mono")
        font.setPixelSize(t.SIZE_XS)
        p.setFont(font)
        fm = p.fontMetrics()

        total_segments = (self._majors - 1) * (self._minors + 1)
        for i in range(total_segments + 1):
            frac = i / total_segments
            x = int(round(self._inset + frac * usable))
            is_major = (i % (self._minors + 1)) == 0
            if is_major:
                p.setPen(major_pen)
                p.drawLine(x, 0, x, _MAJOR_H)
                label = self._fmt(self._value_at(frac))
                tw = fm.horizontalAdvance(label)
                # Clamp end labels inside the widget.
                tx = x - tw / 2
                tx = max(0.0, min(float(w - tw), tx))
                p.setPen(QColor(t.TEXT_MICRO))
                p.drawText(QRectF(tx, _MAJOR_H, tw + 2, _HEIGHT - _MAJOR_H),
                           Qt.AlignLeft | Qt.AlignVCenter, label)
            else:
                p.setPen(minor_pen)
                p.drawLine(x, 0, x, _MINOR_H)
