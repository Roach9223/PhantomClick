"""``LabeledSlider``: label + value (top), full-width slider (middle),
optional tick ruler and hint (bottom).

The field label is an uppercase tracked micro-label, the live value is a
right-aligned mono readout, the slider fills the row beneath, and a
:class:`TickRuler` sits under it when ``show_ruler`` is True (default).

Sliders register themselves into the App's shared ``_adv_sliders`` dict so
the Realism dial can push values back into the widgets. ``set()`` snaps
the handle instantly; the deck does not glide.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)

from .. import theme as t
from ui.config_io import save_config
from .ruler import TickRuler


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
        *,
        show_ruler: bool = True,
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

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)
        self.label = QLabel(label.lstrip().upper())
        self.label.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; "
            f"font-weight: 600;"
        )
        font = self.label.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        self.label.setFont(font)
        if tooltip:
            self.label.setToolTip(tooltip)
        head.addWidget(self.label)
        head.addStretch(1)

        self.value_lbl = QLabel("")
        self.value_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_FIELD_VALUE}px;"
        )
        self.value_lbl.setMinimumWidth(56)
        self.value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.value_lbl)
        outer.addLayout(head)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self._steps)
        initial = float(app.cfg.get(cfg_key, from_))
        self.slider.setValue(self._value_to_step(initial))
        self.slider.valueChanged.connect(self._on_slider_change)
        if tooltip:
            self.slider.setToolTip(tooltip)
        outer.addWidget(self.slider)

        self.ruler: Optional[TickRuler] = None
        if show_ruler:
            self.ruler = TickRuler(self._from, self._to, inset=5.0,
                                   fmt=self._ruler_fmt)
            outer.addWidget(self.ruler)

        if hint:
            self.hint = QLabel(hint)
            self.hint.setWordWrap(True)
            self.hint.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_HINT}px;"
            )
            outer.addWidget(self.hint)

        self._render_value(initial)
        app._adv_sliders[cfg_key] = (self, self.value_lbl, value_fmt, is_int)

    def _ruler_fmt(self, v: float) -> str:
        if self._is_int:
            return f"{int(round(v))}"
        span = abs(self._to - self._from)
        if span >= 20:
            return f"{v:.0f}"
        if span >= 2:
            return f"{v:.1f}".rstrip("0").rstrip(".")
        return f"{v:.2f}".rstrip("0").rstrip(".")

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

        def _commit(value=v) -> None:
            save_config(self.app.cfg)
            self.app._push_config_to_clicker()
            if self._on_change is not None:
                self._on_change(value)
        self.app._cfg_debounce.call(_commit)

    def set(self, value: float) -> None:
        """Push a value back into the widget without retriggering save/push.
        Snaps instantly."""
        target = self._value_to_step(value)
        self.slider.blockSignals(True)
        try:
            self.slider.setValue(target)
        finally:
            self.slider.blockSignals(False)
        self._render_value(value)
