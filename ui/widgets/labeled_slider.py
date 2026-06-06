"""``LabeledSlider`` — label + value (top), full-width slider (middle), hint (bottom).

Vertical layout: the field label is left-aligned and semibold, the live
value is right-aligned in mono accent, the slider fills the row beneath,
and an optional hint line sits underneath in tertiary tone. This rhythm
matches the :class:`Field` primitive so cards built from Sections + Fields
read consistently.

Sliders register themselves into the App's shared ``_adv_sliders`` dict
so the Realism dial can push values back into the widgets.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)

from .. import theme as t
from ui.config_io import save_config


class LabeledSlider(QWidget):
    def __init__(
        self,
        app,
        label: str,
        cfg_key: str,
        from_: float,
        to: float,
        steps: int,
        value_fmt: str,
        tooltip: str = "",
        is_int: bool = False,
        on_change: Optional[Callable[[float], None]] = None,
        hint: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.app = app
        self._key = cfg_key
        self._fmt = value_fmt
        self._is_int = is_int
        self._on_change = on_change
        self._from, self._to = float(from_), float(to)
        self._steps = max(1, int(steps))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Top row: label · spacer · mono value.
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)
        self.label = QLabel(label.lstrip())
        self.label.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; "
            f"font-weight: 600;"
        )
        if tooltip:
            self.label.setToolTip(tooltip)
        head.addWidget(self.label)
        head.addStretch(1)

        self.value_lbl = QLabel("")
        self.value_lbl.setStyleSheet(
            f"color: {t.ACCENT}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_FIELD_VALUE}px;"
        )
        self.value_lbl.setMinimumWidth(56)
        self.value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.value_lbl)
        outer.addLayout(head)

        # Slider fills the field width.
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self._steps)
        initial = float(app.cfg.get(cfg_key, from_))
        self.slider.setValue(self._value_to_step(initial))
        self.slider.valueChanged.connect(self._on_slider_change)
        if tooltip:
            self.slider.setToolTip(tooltip)
        outer.addWidget(self.slider)

        # Optional hint line under the slider.
        if hint:
            self.hint = QLabel(hint)
            self.hint.setWordWrap(True)
            self.hint.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_HINT}px;"
            )
            outer.addWidget(self.hint)

        self._render_value(initial)

        # Register so the Realism preset can push values back to us.
        app._adv_sliders[cfg_key] = (self, self.value_lbl, value_fmt, is_int)

    def _value_to_step(self, v: float) -> int:
        if self._to == self._from:
            return 0
        return int(round((v - self._from) / (self._to - self._from) * self._steps))

    def _step_to_value(self, step: int) -> float:
        return self._from + (step / self._steps) * (self._to - self._from)

    def _render_value(self, v: float) -> None:
        if self._is_int:
            self.value_lbl.setText(self._fmt.format(int(v)))
        else:
            self.value_lbl.setText(self._fmt.format(v))

    def _on_slider_change(self, step: int) -> None:
        v = self._step_to_value(step)
        v = int(v) if self._is_int else float(v)
        self.app.cfg[self._key] = v
        self._render_value(v)
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()
        if self._on_change is not None:
            self._on_change(v)

    def set(self, value: float) -> None:
        """Push a value back into the widget without retriggering save/push.

        Animated: when the Realism preset moves a slider, the handle
        glides to the new step over ~220 ms instead of snapping.
        """
        target = self._value_to_step(value)
        current = self.slider.value()
        if target == current:
            self._render_value(value)
            return
        # Stop any in-flight animation so rapid presses don't pile up.
        anim = getattr(self, "_set_anim", None)
        if anim is not None and anim.state() == QPropertyAnimation.Running:
            anim.stop()
        self.slider.blockSignals(True)
        self._set_anim = QPropertyAnimation(self.slider, b"value", self)
        self._set_anim.setDuration(220)
        self._set_anim.setStartValue(current)
        self._set_anim.setEndValue(target)
        self._set_anim.setEasingCurve(QEasingCurve.OutCubic)
        # Re-enable the slider's own signal once the animation lands so
        # subsequent user drags fire normally.
        def _done():
            try:
                self.slider.blockSignals(False)
            except RuntimeError:
                pass
        self._set_anim.finished.connect(_done)
        self._set_anim.start()
        self._render_value(value)
