"""``IntervalDisplay`` — large mono readout of an interval range.

Pairs with a ``RangeSlider`` below it: connect the slider's
``valueChanged(lo, hi)`` to ``set_values(lo, hi)`` and the readout updates
live as the user drags. The number / unit split keeps the magnitude
visually loud (mono 18 px) without making the unit shout.

Reuses :func:`ui.format.fmt_delay` to keep the ms ↔ s formatting
identical to every other delay surface in the app.
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..format import fmt_delay


def _split_unit(seconds: float) -> Tuple[str, str]:
    """Split ``fmt_delay``'s rendered string into ("75", "ms") / ("7.5", "s")."""
    s = fmt_delay(seconds)
    # fmt_delay returns "75 ms" / "1.50 s" / "15.0 s".
    if " " in s:
        num, unit = s.split(" ", 1)
        return (num, unit)
    return (s, "")


class IntervalDisplay(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._lo_num = QLabel("0")
        self._lo_num.setProperty("role", "mono-readout")
        self._lo_unit = QLabel("ms")
        self._lo_unit.setProperty("role", "mono-readout-unit")

        self._arrow = QLabel("→")
        self._arrow.setProperty("role", "mono-readout-arrow")

        self._hi_num = QLabel("0")
        self._hi_num.setProperty("role", "mono-readout")
        self._hi_unit = QLabel("ms")
        self._hi_unit.setProperty("role", "mono-readout-unit")

        for w in (self._lo_num, self._lo_unit, self._arrow,
                  self._hi_num, self._hi_unit):
            layout.addWidget(w)
        layout.addStretch(1)

    def set_values(self, lo_seconds: float, hi_seconds: float) -> None:
        lo_num, lo_unit = _split_unit(float(lo_seconds))
        hi_num, hi_unit = _split_unit(float(hi_seconds))
        self._lo_num.setText(lo_num)
        self._lo_unit.setText(lo_unit)
        self._hi_num.setText(hi_num)
        self._hi_unit.setText(hi_unit)
