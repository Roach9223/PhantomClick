"""``RangeSpinSlider``: :class:`RangeSlider` with log scaling + spinboxes.

Two reasons this exists:

1. **Logarithmic slider mapping.** A linear slider over 10 ms..120 s is
   unusable for sub-second entry. We map the slider's internal position
   (linear 0..1) to the user-visible value exponentially:
   ``value = from_ * (to / from_) ** position``, roughly an order of
   magnitude per quarter of the bar.

2. **Companion spinboxes for typed entry.** Two :class:`QDoubleSpinBox`es
   sit under the slider; drag updates them, typing updates the thumbs.
   Both inputs stay in sync via a single suppress flag.

A :class:`TickRuler` (log-scaled) sits directly under the track when
``show_ruler`` is True (default). Same ``valueChanged(min, max)`` signal
as :class:`RangeSlider`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from .range_slider import RangeSlider
from .ruler import TickRuler


_POS_FROM = 0.0
_POS_TO = 1.0
_POS_STEPS = 10000

_SLIDER_PAD_X = 12


class RangeSpinSlider(QWidget):
    valueChanged = Signal(float, float)

    def __init__(
        self,
        from_: float = 0.01,
        to: float = 1.0,
        steps: int = 100,  # accepted for API parity, ignored under log mapping
        init_min: float | None = None,
        init_max: float | None = None,
        decimals: int = 3,
        suffix: str = " s",
        spin_step: float = 0.01,
        parent: QWidget | None = None,
        *,
        show_ruler: bool = True,
    ):
        super().__init__(parent)
        self._from = max(1e-6, float(from_))
        self._to = max(self._from * 1.001, float(to))
        self._log_ratio = math.log(self._to / self._from)
        self._suppress = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.SP_XS)

        slider_col = QVBoxLayout()
        slider_col.setContentsMargins(_SLIDER_PAD_X, 0, _SLIDER_PAD_X, 0)
        slider_col.setSpacing(0)

        lo_init = float(init_min) if init_min is not None else self._from
        hi_init = float(init_max) if init_max is not None else self._to
        if lo_init > hi_init:
            lo_init, hi_init = hi_init, lo_init
        lo_init = self._clamp_value(lo_init)
        hi_init = self._clamp_value(hi_init)

        self._slider = RangeSlider(
            from_=_POS_FROM, to=_POS_TO, steps=_POS_STEPS,
            init_min=self._value_to_pos(lo_init),
            init_max=self._value_to_pos(hi_init),
        )
        self._slider.valueChanged.connect(self._on_slider_change)
        slider_col.addWidget(self._slider)

        self.ruler: TickRuler | None = None
        if show_ruler:
            self.ruler = TickRuler(
                self._from, self._to, majors=5, minors_per_major=3,
                inset=RangeSlider.THUMB_R, log_scale=True,
                fmt=_ruler_fmt,
            )
            slider_col.addWidget(self.ruler)
        outer.addLayout(slider_col)

        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(0, 0, 0, 0)
        spin_row.setSpacing(t.SP_SM)

        self._min_spin = self._make_spin(decimals, suffix, spin_step, lo_init)
        self._max_spin = self._make_spin(decimals, suffix, spin_step, hi_init)
        self._min_spin.setKeyboardTracking(False)
        self._max_spin.setKeyboardTracking(False)
        self._min_spin.valueChanged.connect(self._on_min_spin_change)
        self._max_spin.valueChanged.connect(self._on_max_spin_change)

        min_label = QLabel("MIN")
        min_label.setProperty("role", "row-desc")
        max_label = QLabel("MAX")
        max_label.setProperty("role", "row-desc")
        spin_row.addWidget(min_label)
        spin_row.addWidget(self._min_spin, 1)
        spin_row.addSpacing(t.SP_MD)
        spin_row.addWidget(max_label)
        spin_row.addWidget(self._max_spin, 1)
        outer.addLayout(spin_row)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # -- Public API (mirrors RangeSlider) ---------------------------------

    def set_values(self, lo: float, hi: float) -> None:
        lo = self._clamp_value(float(lo))
        hi = self._clamp_value(float(hi))
        if lo > hi:
            lo, hi = hi, lo
        self._suppress = True
        self._slider.set_values(self._value_to_pos(lo), self._value_to_pos(hi))
        self._min_spin.setValue(lo)
        self._max_spin.setValue(hi)
        self._suppress = False
        self.valueChanged.emit(lo, hi)

    def values(self) -> tuple[float, float]:
        return (float(self._min_spin.value()), float(self._max_spin.value()))

    # -- Mapping ----------------------------------------------------------

    def _value_to_pos(self, v: float) -> float:
        v = self._clamp_value(v)
        return math.log(v / self._from) / self._log_ratio

    def _pos_to_value(self, p: float) -> float:
        p = max(0.0, min(1.0, p))
        return self._from * math.exp(p * self._log_ratio)

    def _clamp_value(self, v: float) -> float:
        return max(self._from, min(self._to, v))

    # -- Internal sync ----------------------------------------------------

    def _make_spin(self, decimals: int, suffix: str, step: float, init: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setMinimum(self._from)
        s.setMaximum(self._to)
        s.setDecimals(int(decimals))
        s.setSingleStep(float(step))
        s.setSuffix(suffix)
        s.setValue(float(init))
        s.setMinimumWidth(96)
        return s

    def _on_slider_change(self, lo_pos: float, hi_pos: float) -> None:
        if self._suppress:
            return
        lo = self._pos_to_value(lo_pos)
        hi = self._pos_to_value(hi_pos)
        self._suppress = True
        self._min_spin.setValue(lo)
        self._max_spin.setValue(hi)
        self._suppress = False
        self.valueChanged.emit(lo, hi)

    def _on_min_spin_change(self, lo: float) -> None:
        if self._suppress:
            return
        hi = self._max_spin.value()
        if lo > hi:
            lo = hi
            self._suppress = True
            self._min_spin.setValue(lo)
            self._suppress = False
        self._suppress = True
        self._slider.set_values(self._value_to_pos(lo), self._value_to_pos(hi))
        self._suppress = False
        self.valueChanged.emit(lo, hi)

    def _on_max_spin_change(self, hi: float) -> None:
        if self._suppress:
            return
        lo = self._min_spin.value()
        if hi < lo:
            hi = lo
            self._suppress = True
            self._max_spin.setValue(hi)
            self._suppress = False
        self._suppress = True
        self._slider.set_values(self._value_to_pos(lo), self._value_to_pos(hi))
        self._suppress = False
        self.valueChanged.emit(lo, hi)


def _ruler_fmt(seconds: float) -> str:
    """Compact tick label: ``10ms``, ``1s``, ``2m``."""
    if seconds >= 60:
        return f"{seconds / 60:.0f}m"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}".rstrip("0").rstrip(".") + "s"
