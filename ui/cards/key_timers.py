"""``KeyTimersPageBody`` — passive concurrent keypress timers.

Each timer fires a key (or combo) on its own clock while the engine is
otherwise running — the canonical use case is "press Z every 6 minutes"
for potion macros that don't fit into the click sequence.

Two :class:`SettingsGroup`s composed from the design-system primitives:

* **Settings** — single row toggling ±10 % jitter on every timer's wait
  (so a fixed 15 min interval doesn't fire at *exactly* 15 min every
  cycle, which anti-bot systems flag as a pattern).
* **Timers** — one :class:`TimerRow` per stored timer. Each row carries
  the key combo input, an :class:`IOSSwitch` for enable, a remove
  button, and a value-+-unit row beneath. The group header carries a
  ``+ Add timer`` :class:`QuietAccentButton`.

Engine support lives in :mod:`modules.key_timer`; this card is just the
UI shell. Timers persist as ``cfg["key_timers"]`` via
``serialize_timers``; the engine path is unchanged from the prior
``KeyTimersCard`` implementation.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from modules.key_timer import KeyTimer, parse_combo, serialize_timers
from ui.config_io import save_config

from .. import theme as t
from ..widgets.empty_state import EmptyState
from ..widgets.group_header import GroupHeader
from ..widgets.ios_switch import IOSSwitch
from ..widgets.quiet_button import QuietAccentButton
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow


# Per-unit (lo, hi, step, decimals, seconds_factor) for the spinbox.
_UNIT_SPECS = {
    "ms":  (50.0,    600_000.0, 50.0,  0, 0.001),
    "s":   (0.5,      86_400.0,  1.0,  1, 1.0),
    "min": (0.05,      1_440.0,  0.5,  2, 60.0),
    "hr":  (0.01,         24.0, 0.25,  2, 3600.0),
}
_UNIT_ORDER = ("ms", "s", "min", "hr")
_UNIT_LABEL = {
    "ms":  "ms",
    "s":   "sec",
    "min": "min",
    "hr":  "hr",
}

# Badge column width on the row's top line. Row 2's left indent matches
# this so its "Every X unit" controls align under the combo input above.
_BADGE_W = 28


def _unit_to_seconds(value: float, unit: str) -> float:
    _lo, _hi, _step, _dec, factor = _UNIT_SPECS.get(unit, _UNIT_SPECS["min"])
    return max(0.05, float(value) * factor)


def _seconds_to_unit(seconds: float, unit: str) -> float:
    _lo, _hi, _step, _dec, factor = _UNIT_SPECS.get(unit, _UNIT_SPECS["min"])
    return max(0.0, float(seconds) / factor)


class TimerRow(QFrame):
    """One timer in the list. Two-line layout under the standard
    settings-row chrome — top row carries the key combo + enable + remove,
    bottom row carries the interval value + unit picker."""

    def __init__(self, idx: int, body: "KeyTimersPageBody",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("role", "settings-row")
        self._idx = idx
        self._body = body
        self.app = body.app
        timer = self.app._key_timers[idx]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.ROW_PAD_X, t.ROW_PAD_Y,
                                  t.ROW_PAD_X, t.ROW_PAD_Y)
        outer.setSpacing(t.SP_SM)

        # ── Top row ─────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(t.SP_SM)

        badge = QLabel(f"#{idx + 1}")
        badge.setProperty("role", "zone-badge")
        badge.setMinimumWidth(_BADGE_W)
        top.addWidget(badge)

        self.key_edit = self.app.locker.register(QLineEdit(timer.key))
        self.key_edit.setPlaceholderText("z, f1, ctrl+shift+f5")
        self.key_edit.setMinimumHeight(t.INPUT_H)
        self.key_edit.setProperty("role", "value-entry")
        self.key_edit.textChanged.connect(self._validate_combo)
        self.key_edit.editingFinished.connect(self._on_key_edited)
        self._validate_combo(timer.key)
        top.addWidget(self.key_edit, 1)

        self.enable_switch = self.app.locker.register(IOSSwitch())
        self.enable_switch.setChecked(bool(timer.enabled))
        self.enable_switch.setToolTip("Enable or pause this timer.")
        self.enable_switch.toggled.connect(self._on_enabled_toggled)
        top.addWidget(self.enable_switch)

        self.remove_btn = self.app.locker.register(QPushButton("✕"))
        self.remove_btn.setProperty("variant", "icon-danger")
        self.remove_btn.setMaximumSize(28, 24)
        self.remove_btn.setMinimumSize(28, 24)
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setToolTip("Remove this timer.")
        self.remove_btn.clicked.connect(self._on_remove)
        top.addWidget(self.remove_btn)

        outer.addLayout(top)

        # ── Bottom row ──────────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(t.SP_SM)
        bottom.addSpacing(_BADGE_W + t.SP_SM)  # align with badge column above

        every_lbl = QLabel("Every")
        every_lbl.setProperty("role", "row-desc")
        bottom.addWidget(every_lbl)

        unit = timer.interval_unit if timer.interval_unit in _UNIT_SPECS else "min"

        self.value_spin = self.app.locker.register(QDoubleSpinBox())
        self.value_spin.setMinimumHeight(t.INPUT_H)
        self.value_spin.setMaximumWidth(140)
        # Mono font on the editable value: signals "this is a numeric
        # quantity" and visually echoes other mono readouts in the app.
        self.value_spin.setStyleSheet(f"font-family: {t.FONT_MONO};")
        self.value_spin.setToolTip(
            "How long to wait between fires. The Randomize toggle in the "
            "Settings group adds ±10 % jitter so this isn't perfectly "
            "periodic."
        )

        self.unit_combo = self.app.locker.register(QComboBox())
        self.unit_combo.setMinimumHeight(t.INPUT_H)
        self.unit_combo.setCursor(Qt.PointingHandCursor)
        self.unit_combo.setToolTip("Time unit for the interval.")
        for u in _UNIT_ORDER:
            self.unit_combo.addItem(_UNIT_LABEL[u], userData=u)

        self._configure_value_spin(unit)
        self.value_spin.setValue(_seconds_to_unit(timer.interval_min, unit))
        for i in range(self.unit_combo.count()):
            if self.unit_combo.itemData(i) == unit:
                self.unit_combo.setCurrentIndex(i)
                break

        self.value_spin.editingFinished.connect(self._on_interval_committed)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)

        bottom.addWidget(self.value_spin)
        bottom.addWidget(self.unit_combo)
        bottom.addStretch(1)
        outer.addLayout(bottom)

    # -- SettingsGroup contract -------------------------------------------

    def set_last(self, last: bool) -> None:
        new = "true" if last else "false"
        if self.property("last") == new:
            return
        self.setProperty("last", new)
        self.style().unpolish(self)
        self.style().polish(self)

    # -- Helpers ---------------------------------------------------------

    def _configure_value_spin(self, unit: str) -> None:
        lo, hi, step, decimals, _factor = _UNIT_SPECS[unit]
        self.value_spin.blockSignals(True)
        self.value_spin.setRange(lo, hi)
        self.value_spin.setSingleStep(step)
        self.value_spin.setDecimals(decimals)
        self.value_spin.setSuffix(f" {_UNIT_LABEL[unit]}")
        self.value_spin.blockSignals(False)

    def _validate_combo(self, text: str) -> None:
        ok = bool(text) and parse_combo(text.lower()) is not None
        self.key_edit.setProperty("invalid", "false" if ok else "true")
        self.key_edit.style().unpolish(self.key_edit)
        self.key_edit.style().polish(self.key_edit)
        if not ok and text:
            self.key_edit.setToolTip(
                "Unrecognized key. Try a single character (z), a function "
                "key (f5), or a combo with modifiers (ctrl+shift+f5)."
            )
        else:
            self.key_edit.setToolTip("")

    # -- Handlers --------------------------------------------------------

    def _on_key_edited(self) -> None:
        if not (0 <= self._idx < len(self.app._key_timers)):
            return
        new_key = (self.key_edit.text() or "").strip().lower()
        if new_key == self.app._key_timers[self._idx].key:
            return
        self.app._key_timers[self._idx].key = new_key
        self._body._save()

    def _on_enabled_toggled(self, checked: bool) -> None:
        if not (0 <= self._idx < len(self.app._key_timers)):
            return
        self.app._key_timers[self._idx].enabled = bool(checked)
        self._body._save()

    def _on_remove(self) -> None:
        if not (0 <= self._idx < len(self.app._key_timers)):
            return
        if QMessageBox.question(
            self, "Remove timer", f"Remove timer #{self._idx + 1}?",
        ) != QMessageBox.Yes:
            return
        del self.app._key_timers[self._idx]
        self._body._save()
        self._body.render_all()

    def _on_interval_committed(self) -> None:
        if not (0 <= self._idx < len(self.app._key_timers)):
            return
        unit = str(self.unit_combo.currentData() or "min")
        seconds = _unit_to_seconds(self.value_spin.value(), unit)
        timer = self.app._key_timers[self._idx]
        timer.interval_min = seconds
        timer.interval_max = seconds
        timer.interval_unit = unit
        self._body._save()

    def _on_unit_changed(self) -> None:
        """Switch the displayed unit without changing the actual timing.

        Captures current value × old unit (= seconds), reconfigures the
        spinbox bounds for the new unit, then writes the equivalent
        value back."""
        if not (0 <= self._idx < len(self.app._key_timers)):
            return
        timer = self.app._key_timers[self._idx]
        old_unit = timer.interval_unit if timer.interval_unit in _UNIT_SPECS else "min"
        new_unit = str(self.unit_combo.currentData() or "min")
        if new_unit == old_unit:
            return
        seconds = _unit_to_seconds(self.value_spin.value(), old_unit)
        self._configure_value_spin(new_unit)
        new_value = _seconds_to_unit(seconds, new_unit)
        lo, hi, _step, _dec, _factor = _UNIT_SPECS[new_unit]
        new_value = max(lo, min(hi, new_value))
        self.value_spin.blockSignals(True)
        self.value_spin.setValue(new_value)
        self.value_spin.blockSignals(False)
        timer.interval_unit = new_unit
        timer.interval_min = _unit_to_seconds(new_value, new_unit)
        timer.interval_max = timer.interval_min
        self._body._save()


class KeyTimersPageBody(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Settings group (jitter master toggle) ───────────────────
        outer.addWidget(GroupHeader("Settings"))
        settings_group = SettingsGroup()

        self._jitter_switch = self.app.locker.register(IOSSwitch())
        self._jitter_switch.setChecked(bool(
            self.app.cfg.get("key_timer_jitter_enabled", True)
        ))
        self._jitter_switch.setToolTip(
            "When on, the wait between fires is multiplied by a random "
            "factor between 0.9 and 1.1 — a 15 min interval fires at "
            "13.5–16.5 min instead of exactly 15 min every cycle."
        )
        self._jitter_switch.toggled.connect(self._on_jitter_toggled)
        jitter_row = SettingsRow(
            "Randomize intervals",
            desc=(
                "Add ±10 % jitter so a fixed interval isn't perfectly "
                "periodic — eliminates the bot-tell pattern."
            ),
        )
        jitter_row.set_control(self._jitter_switch)
        settings_group.add_row(jitter_row)
        outer.addWidget(settings_group)

        outer.addSpacing(t.SP_XL)

        # ── Timers group ────────────────────────────────────────────
        timers_header = GroupHeader("Timers")
        self._add_btn = self.app.locker.register(QuietAccentButton("+  Add timer"))
        self._add_btn.setToolTip(
            "Add a passive keypress that fires on its own clock."
        )
        self._add_btn.clicked.connect(self._on_add)
        timers_header.add_action(self._add_btn)
        outer.addWidget(timers_header)

        self._timers_group = SettingsGroup()
        outer.addWidget(self._timers_group)

        outer.addSpacing(t.SP_MD)

        # ── Footer hint ─────────────────────────────────────────────
        footer = QLabel(
            "Combos use ‘+’: ctrl+z, shift+f5. Timers fire only while the "
            "engine is running."
        )
        footer.setProperty("role", "footer-hint")
        footer.setWordWrap(True)
        outer.addWidget(footer)

        self.render_all()

    # -- Rendering --------------------------------------------------------

    def render_all(self) -> None:
        self._timers_group.clear()
        timers = self.app._key_timers
        if not timers:
            self._timers_group.add_widget(EmptyState(
                title="No timers yet",
                description=(
                    "Add a passive keypress that fires on its own clock — "
                    "useful for potion / buff macros that run alongside "
                    "your click sequence."
                ),
                cta_text="+  Add timer",
                on_cta=self._on_add,
            ))
            return
        for idx in range(len(timers)):
            self._timers_group.add_row(TimerRow(idx, self))
        self.app.locker.apply(self.app._state_str)

    # -- Handlers --------------------------------------------------------

    def _on_add(self) -> None:
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return
        # Default to "every 15 min" — the canonical use case.
        self.app._key_timers.append(KeyTimer(
            key="z", interval_min=900.0, interval_max=900.0, enabled=True,
            interval_unit="min",
        ))
        self._save()
        self.render_all()

    def _on_jitter_toggled(self, checked: bool) -> None:
        self.app.cfg["key_timer_jitter_enabled"] = bool(checked)
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()
        if hasattr(self.app, "toasts"):
            msg = ("✓ Timer intervals will be randomized ±10 %"
                   if checked else
                   "Timer intervals locked to exact values")
            self.app.toasts.post(msg, kind="info")

    def _save(self) -> None:
        self.app.cfg["key_timers"] = serialize_timers(self.app._key_timers)
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()


# Back-compat alias: ui/app.py still references KeyTimersCard.
KeyTimersCard = KeyTimersPageBody
