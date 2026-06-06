"""``RangeSpinSlider`` — :class:`RangeSlider` with log scaling + spinboxes.

Two reasons this exists:

1. **Logarithmic slider mapping.** A linear slider over 10 ms..120 s is
   unusable for sub-second entry — the first 1 % of the bar covers
   ~1.2 s, so dialing in 75 ms by drag is near-impossible. We map the
   slider's internal position (linear 0..1) to the user-visible value
   exponentially: ``value = from_ * (to / from_) ** position``. This
   gives roughly an order of magnitude per quarter of the bar:
   10 ms → 100 ms → 1 s → 10 s → 120 s. Sub-second values now occupy
   half the slider's drag distance instead of <1 %.

2. **Companion spinboxes for typed entry.** Even with log scaling, a
   user who knows they want exactly ``1.500 s`` shouldn't have to
   scrub. Two :class:`QDoubleSpinBox`es sit under the slider; drag
   updates them, typing updates the slider thumbs. Both inputs stay
   in sync via a single suppress flag that breaks recursion.

Same ``valueChanged(min, max)`` signal as :class:`RangeSlider` so the
swap is a one-line change at each call site.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import theme as t
from .range_slider import RangeSlider


# Internal slider works in normalized [0, 1] position space; we convert
# both directions in this widget so the underlying RangeSlider stays
# generic + linear (it's used elsewhere with normal scaling).
_POS_FROM = 0.0
_POS_TO = 1.0
_POS_STEPS = 10000   # ~0.01 % position resolution — sub-pixel under any reasonable bar width


# Padding around the slider so it doesn't span the full row width.
# Pulled in from each side; spinbox row stays full width below.
_SLIDER_PAD_X = 24


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
    ):
        """``decimals=3`` + ``suffix=" s"`` displays sub-second values
        as e.g. ``0.075 s`` — readable and unambiguous about units.
        ``spin_step`` (default 10 ms) is the up/down-arrow increment;
        users can still type any value at full ``decimals`` precision.

        ``from_`` must be > 0 — the log mapping ``value =
        from_·(to/from_)^pos`` requires a strictly positive lower
        bound. Callers should pass e.g. 0.01 (10 ms) instead of 0.
        """
        super().__init__(parent)
        # Guard against pathological ranges. We need from_ > 0 for log,
        # and to > from_ so the ratio is well-defined and > 1.
        self._from = max(1e-6, float(from_))
        self._to = max(self._from * 1.001, float(to))
        self._log_ratio = math.log(self._to / self._from)
        # Suppress recursive emits while one input updates the other —
        # without this, slider-drag → spin-update → slider-update would
        # loop on every pixel.
        self._suppress = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.SP_XS)

        # Slider lives in a padded HBox so the bar doesn't span the
        # full widget width — the user found that visually heavy. The
        # spinbox row beneath uses the full width since it carries
        # text labels and benefits from the extra space.
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(_SLIDER_PAD_X, 0, _SLIDER_PAD_X, 0)
        slider_row.setSpacing(0)

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
        slider_row.addWidget(self._slider, 1)
        outer.addLayout(slider_row)

        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(0, 0, 0, 0)
        spin_row.setSpacing(t.SP_SM)

        self._min_spin = self._make_spin(decimals, suffix, spin_step, lo_init)
        self._max_spin = self._make_spin(decimals, suffix, spin_step, hi_init)
        # ``setKeyboardTracking(False)`` makes the spinbox emit only on
        # Enter / focus loss / arrow click — not on every keystroke
        # while the user is mid-typing — so partial values like ``1.``
        # don't briefly snap the slider to 1.000.
        self._min_spin.setKeyboardTracking(False)
        self._max_spin.setKeyboardTracking(False)
        self._min_spin.valueChanged.connect(self._on_min_spin_change)
        self._max_spin.valueChanged.connect(self._on_max_spin_change)

        min_label = QLabel("min")
        min_label.setProperty("role", "row-desc")
        max_label = QLabel("max")
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
        """Programmatic setter — emits ``valueChanged`` once. Mirrors
        :meth:`RangeSlider.set_values` so callers don't have to know
        which slider variant they're holding."""
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
        # Read straight off the spinboxes — they hold the canonical
        # post-log-mapping values that match what gets emitted.
        return (float(self._min_spin.value()), float(self._max_spin.value()))

    # -- Mapping ----------------------------------------------------------

    def _value_to_pos(self, v: float) -> float:
        """Map a real value (e.g. 1.5 s) to slider position [0, 1]."""
        v = self._clamp_value(v)
        return math.log(v / self._from) / self._log_ratio

    def _pos_to_value(self, p: float) -> float:
        """Map slider position [0, 1] to real value (e.g. 1.5 s)."""
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
        # Spinboxes can cross over via typing; clamp the min not to
        # exceed the max. We do this by snapping min back down rather
        # than swapping, because the user likely meant "make min big"
        # — better to cap at max than to silently relabel the inputs.
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
