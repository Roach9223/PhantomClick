"""``BehaviorPageBody`` — Pre-start delay, Realism dial, Advanced overrides.

The 2026 redesign flattens the prior single-:class:`Card`-with-Expander
into a stack of :class:`SettingsGroup`s. The Realism dial gets a custom
hero treatment between the Pre-start group and the Advanced sub-groups.
Every Advanced sub-group's first row is its master enable switch; the
remaining rows disable when the master is off.

Public API kept: :meth:`apply_realism_preset` (called by
:class:`RealismStub` instances on Click and Record pages),
:meth:`refresh_advanced` (called after Realism push to sync widgets),
plus the four ``_clamp_*`` clamp callbacks wired into Break sliders.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)

from ui.config_io import save_config

from .. import theme as t
from ..widgets.feature_toggle import FeatureToggle
from ..widgets.field import value_label
from ..widgets.group_header import GroupHeader
from ..widgets.ios_switch import IOSSwitch
from ..widgets.labeled_slider import LabeledSlider
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow


class _Group:
    """Lightweight bundle so each sub-group can disable its sub-rows
    when the master toggle goes off and surface the canonical
    ``[active="true"]`` left stripe on the group widget while it does."""
    __slots__ = ("master", "widget", "sub_rows")

    def __init__(self, master: IOSSwitch, widget: SettingsGroup,
                 sub_rows: List[SettingsRow]):
        self.master = master
        self.widget = widget
        self.sub_rows = sub_rows


class BehaviorPageBody(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        # Register so RealismStubs on other pages can dispatch the preset
        # back through the canonical apply_realism_preset() path.
        app._behavior_card = self

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Pre-start ────────────────────────────────────────────────
        outer.addWidget(GroupHeader("Pre-start"))
        prestart_group = SettingsGroup()
        prestart_group.add_row(self._build_slider_row(
            "Delay before first click",
            "Time after pressing Start before the first click — gives "
            "you a window to alt-tab into the target window.",
            cfg_key="prestart_delay",
            from_=0.0, to=10.0, steps=100, value_fmt="{:.1f}s",
        ))
        outer.addWidget(prestart_group)

        outer.addSpacing(t.SP_XL)

        # ── Realism hero ────────────────────────────────────────────
        outer.addWidget(GroupHeader("Realism"))
        outer.addWidget(self._build_realism_hero())

        outer.addSpacing(t.SP_XL)

        # ── Advanced sub-groups ─────────────────────────────────────
        self._groups: List[_Group] = []

        self._build_idle_wander(outer)
        self._build_fatigue(outer)
        self._build_breaks(outer)
        self._build_overshoot(outer)
        self._build_anti_cluster(outer)
        self._build_stop_after(outer)
        # Key-input backend selector + Serial HID port now live on the
        # Settings page (see ui/cards/settings.py). Behavior is for
        # humanization knobs; system / I/O concerns belong in Settings.

        outer.addSpacing(t.SP_MD)

        # ── Footer hint ─────────────────────────────────────────────
        footer = QLabel(
            "Moving the Realism dial overwrites every Advanced value below. "
            "Set the dial first, then tweak Advanced."
        )
        footer.setProperty("role", "footer-hint")
        footer.setWordWrap(True)
        outer.addWidget(footer)

        # Apply initial enable state for every sub-group.
        for g in self._groups:
            self._apply_master(g)

    # -- Realism hero ----------------------------------------------------

    def _build_realism_hero(self) -> QWidget:
        """Custom panel: title + percent value chip, then full-width
        slider with Mechanical / Natural end labels and a helper line."""
        panel = QFrame()
        panel.setProperty("role", "settings-group")  # reuse rounded chrome
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(t.SP_LG, t.SP_LG - 2,
                                   t.SP_LG, t.SP_LG - 2)
        layout.setSpacing(t.SP_SM)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)
        title = QLabel("Humanization level")
        title.setProperty("role", "row-label")
        head.addWidget(title)
        head.addStretch(1)
        self.realism_value_lbl = value_label(
            f"{int(self.app.cfg.get('realism', 0.5) * 100)}%"
        )
        head.addWidget(self.realism_value_lbl)
        layout.addLayout(head)

        self.realism_slider = QSlider(Qt.Horizontal)
        self.realism_slider.setRange(0, 100)
        self.realism_slider.setValue(int(round(self.app.cfg.get("realism", 0.5) * 100)))
        self.realism_slider.valueChanged.connect(self._on_realism_change)
        self.realism_slider.setToolTip(
            "Higher = more wander, hover, fatigue, breaks, overshoots. "
            "Moves overwrite Advanced values."
        )
        layout.addWidget(self.realism_slider)

        ends = QHBoxLayout()
        ends.setContentsMargins(0, 0, 0, 0)
        left = QLabel("Mechanical")
        left.setProperty("role", "row-desc")
        right = QLabel("Natural")
        right.setProperty("role", "row-desc")
        ends.addWidget(left)
        ends.addStretch(1)
        ends.addWidget(right)
        layout.addLayout(ends)

        helper = QLabel(
            "One dial drives every humanization behavior. "
            "Tweak individual settings below to override."
        )
        helper.setProperty("role", "row-desc")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        return panel

    # -- Row builders ----------------------------------------------------

    def _build_slider_row(
        self,
        title: str,
        desc: str,
        *,
        cfg_key: str,
        from_: float,
        to: float,
        steps: int,
        value_fmt: str,
        is_int: bool = False,
        on_change=None,
    ) -> SettingsRow:
        """A row whose right-side control is a LabeledSlider with its
        own internal label hidden — the row's title carries the label
        instead. Slider value chip remains visible above the slider."""
        slider = LabeledSlider(
            self.app, "", cfg_key,
            from_=from_, to=to, steps=steps,
            value_fmt=value_fmt, is_int=is_int,
            on_change=on_change,
        )
        # Hide the redundant internal label; keep value chip + slider.
        slider.label.hide()
        slider.setMinimumWidth(220)
        row = SettingsRow(title, desc=desc)
        row.set_control(slider)
        return row

    def _build_switch_row(
        self,
        title: str,
        desc: str,
        *,
        cfg_key: str,
        tooltip: str = "",
    ) -> tuple[SettingsRow, IOSSwitch]:
        """A row whose control is an :class:`IOSSwitch` bound to a cfg
        key. The switch is registered into ``app._adv_vars`` so the
        Realism dial can flip it via :meth:`refresh_advanced`."""
        switch = IOSSwitch()
        switch.setChecked(bool(self.app.cfg.get(cfg_key, False)))
        if tooltip:
            switch.setToolTip(tooltip)
        switch.toggled.connect(lambda checked, k=cfg_key: self._on_switch_toggled(k, checked))
        self.app._adv_vars[cfg_key] = switch

        row = SettingsRow(title, desc=desc)
        row.set_control(switch)
        return row, switch

    def _on_switch_toggled(self, cfg_key: str, checked: bool) -> None:
        self.app.cfg[cfg_key] = bool(checked)
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()

    def _apply_master(self, g: _Group) -> None:
        on = g.master.isChecked()
        for r in g.sub_rows:
            r.set_row_enabled(on)
        # OR-aggregate the active stripe across every master that shares
        # this group widget. Stop-after has two independent masters in
        # one group; the stripe should show whenever either is on.
        any_on = any(other.master.isChecked() for other in self._groups
                     if other.widget is g.widget)
        g.widget.set_active(any_on)

    # -- Advanced groups -------------------------------------------------

    def _build_idle_wander(self, outer: QVBoxLayout) -> None:
        outer.addWidget(GroupHeader("Idle wander"))
        group = SettingsGroup()

        master_row, master = self._build_switch_row(
            "Drift between clicks",
            "Short curved drifts during the wait window.",
            cfg_key="idle_wander_enabled",
            tooltip="Short curved drifts between clicks.",
        )
        group.add_row(master_row)

        freq_row = self._build_slider_row(
            "Frequency",
            "Chance of a drift during the wait window.",
            cfg_key="idle_wander_frequency",
            from_=0.0, to=1.0, steps=100, value_fmt="{:.2f}",
        )
        group.add_row(freq_row)

        radius_max = max(2000, self.app.monitor_w)
        radius_row = self._build_slider_row(
            "Radius",
            f"How far drifts roam · monitor {self.app.monitor_w}×{self.app.monitor_h}.",
            cfg_key="idle_wander_padding",
            from_=50, to=radius_max,
            steps=min(1000, radius_max - 50),
            value_fmt="{} px", is_int=True,
        )
        group.add_row(radius_row)

        whole_row, _ = self._build_switch_row(
            "Roam the whole screen",
            "Drifts roam the entire monitor instead of staying near the zone.",
            cfg_key="idle_wander_whole_screen",
            tooltip="Drifts roam the entire monitor instead of staying near the zone.",
        )
        group.add_row(whole_row)

        outer.addWidget(group)
        outer.addSpacing(t.SP_XL)
        self._register_group(master, group, [freq_row, radius_row, whole_row])

    def _build_fatigue(self, outer: QVBoxLayout) -> None:
        outer.addWidget(GroupHeader("Fatigue"))
        group = SettingsGroup()

        master_row, master = self._build_switch_row(
            "Stretch over a session",
            "Inter-click delays gradually increase; movement slows.",
            cfg_key="fatigue_enabled",
        )
        group.add_row(master_row)

        intensity_row = self._build_slider_row(
            "Intensity",
            "How quickly fatigue accumulates.",
            cfg_key="fatigue_intensity",
            from_=0.0, to=0.5, steps=50, value_fmt="{:.2f}",
        )
        group.add_row(intensity_row)

        outer.addWidget(group)
        outer.addSpacing(t.SP_XL)
        self._register_group(master, group, [intensity_row])

    def _build_breaks(self, outer: QVBoxLayout) -> None:
        outer.addWidget(GroupHeader("Breaks"))
        group = SettingsGroup()

        master_row, master = self._build_switch_row(
            "Periodic walks-away",
            "Long pauses every N clicks, like stepping away.",
            cfg_key="break_bursts_enabled",
        )
        group.add_row(master_row)

        min_clicks_row = self._build_slider_row(
            "After ~N clicks",
            "Earliest a break can start, in clicks since the last one.",
            cfg_key="break_min_clicks",
            from_=5, to=200, steps=195, value_fmt="{}", is_int=True,
            on_change=self._clamp_break_max_low,
        )
        max_clicks_row = self._build_slider_row(
            "Up to N clicks",
            "Latest a break can start.",
            cfg_key="break_max_clicks",
            from_=5, to=300, steps=295, value_fmt="{}", is_int=True,
            on_change=self._clamp_break_max_low_paired,
        )
        min_dur_row = self._build_slider_row(
            "Duration min",
            "Shortest a break can last.",
            cfg_key="break_min_duration",
            from_=1, to=300, steps=299, value_fmt="{:.0f}s",
            on_change=self._clamp_duration_max,
        )
        max_dur_row = self._build_slider_row(
            "Duration max",
            "Longest a break can last.",
            cfg_key="break_max_duration",
            from_=1, to=600, steps=599, value_fmt="{:.0f}s",
            on_change=self._clamp_duration_min,
        )
        for row in (min_clicks_row, max_clicks_row, min_dur_row, max_dur_row):
            group.add_row(row)

        outer.addWidget(group)
        outer.addSpacing(t.SP_XL)
        self._register_group(
            master, group,
            [min_clicks_row, max_clicks_row, min_dur_row, max_dur_row],
        )

    def _build_overshoot(self, outer: QVBoxLayout) -> None:
        outer.addWidget(GroupHeader("Overshoot"))
        group = SettingsGroup()

        master_row, master = self._build_switch_row(
            "Over-then-correct",
            "Cursor occasionally overshoots and corrects back.",
            cfg_key="overshoot_enabled",
        )
        group.add_row(master_row)

        prob_row = self._build_slider_row(
            "Probability",
            "How often the cursor overshoots before settling on the click.",
            cfg_key="overshoot_probability",
            from_=0.0, to=0.5, steps=50, value_fmt="{:.2f}",
        )
        group.add_row(prob_row)

        outer.addWidget(group)
        outer.addSpacing(t.SP_XL)
        self._register_group(master, group, [prob_row])

    def _build_anti_cluster(self, outer: QVBoxLayout) -> None:
        outer.addWidget(GroupHeader("Anti-cluster"))
        group = SettingsGroup()

        master_row, master = self._build_switch_row(
            "Repel from recent clicks",
            "New clicks repel from the last 10 click positions so the "
            "distribution doesn't form a tight bell.",
            cfg_key="anti_cluster_enabled",
        )
        group.add_row(master_row)

        radius_row = self._build_slider_row(
            "Minimum gap",
            "Pixels of separation the next click prefers from recent ones.",
            cfg_key="anti_cluster_radius",
            from_=2, to=60, steps=58, value_fmt="{} px", is_int=True,
        )
        group.add_row(radius_row)

        outer.addWidget(group)
        outer.addSpacing(t.SP_XL)
        self._register_group(master, group, [radius_row])

    def _build_stop_after(self, outer: QVBoxLayout) -> None:
        outer.addWidget(GroupHeader("Stop after"))
        group = SettingsGroup()

        clicks_master_row, clicks_master = self._build_switch_row(
            "Stop after click count",
            "End the session once this many clicks have fired.",
            cfg_key="stop_after_clicks_enabled",
        )
        group.add_row(clicks_master_row)

        clicks_row = self._build_slider_row(
            "Click count",
            "Total clicks at which the engine auto-stops.",
            cfg_key="stop_after_clicks",
            from_=10, to=10000, steps=999,
            value_fmt="{}", is_int=True,
        )
        group.add_row(clicks_row)

        time_master_row, time_master = self._build_switch_row(
            "Stop after duration",
            "End the session after this many minutes elapsed.",
            cfg_key="stop_after_minutes_enabled",
        )
        group.add_row(time_master_row)

        time_row = self._build_slider_row(
            "Minutes",
            "Wall-clock minutes at which the engine auto-stops.",
            cfg_key="stop_after_minutes",
            from_=1, to=480, steps=479,
            value_fmt="{} min", is_int=True,
        )
        group.add_row(time_row)

        outer.addWidget(group)
        # Two independent masters in this group — register one each.
        # _apply_master OR-aggregates them so the group's active stripe
        # shows whenever either master is on.
        self._register_group(clicks_master, group, [clicks_row])
        self._register_group(time_master, group, [time_row])

    def _register_group(self, master: IOSSwitch, widget: SettingsGroup,
                        sub_rows: List[SettingsRow]) -> None:
        g = _Group(master, widget, sub_rows)
        self._groups.append(g)
        master.toggled.connect(lambda _checked, gg=g: self._apply_master(gg))

    # -- Break clamps (preserved from prior BehaviorCard) ----------------

    def _clamp_break_max_low(self, v):
        cfg = self.app.cfg
        if cfg["break_max_clicks"] < v:
            cfg["break_max_clicks"] = int(v)
            save_config(cfg)
            self.app._push_config_to_clicker()
            self.refresh_advanced()

    def _clamp_break_max_low_paired(self, v):
        cfg = self.app.cfg
        if cfg["break_min_clicks"] > v:
            cfg["break_min_clicks"] = int(v)
            save_config(cfg)
            self.app._push_config_to_clicker()
            self.refresh_advanced()

    def _clamp_duration_max(self, v):
        cfg = self.app.cfg
        if cfg["break_max_duration"] < v:
            cfg["break_max_duration"] = float(v)
            save_config(cfg)
            self.app._push_config_to_clicker()
            self.refresh_advanced()

    def _clamp_duration_min(self, v):
        cfg = self.app.cfg
        if cfg["break_min_duration"] > v:
            cfg["break_min_duration"] = float(v)
            save_config(cfg)
            self.app._push_config_to_clicker()
            self.refresh_advanced()

    # -- Realism preset --------------------------------------------------

    def _on_realism_change(self, value: int) -> None:
        r = max(0.0, min(1.0, value / 100.0))
        self.apply_realism_preset(r)
        if (self.realism_slider.isSliderDown()
                or self.realism_slider.hasFocus()):
            self.app.toasts.post(
                "↻  Replaced Advanced values for this dial position.",
                kind="info",
            )

    def apply_realism_preset(self, r: float) -> None:
        app = self.app
        r = max(0.0, min(1.0, r))
        cfg = app.cfg
        cfg["realism"] = r
        derived = {
            "idle_wander_enabled": r > 0.05,
            "idle_wander_frequency": round(r * 0.7, 2),
            "idle_wander_padding": int(250 + r * 750),
            "fatigue_enabled": r > 0.10,
            "fatigue_intensity": round(r * 0.40, 2),
            # Break-burst gate moved from r>0.30 to r>0.50 so a default
            # realism (50%) user doesn't get them at all; only realism
            # turned past the midpoint opts into "I want long pauses."
            # Frequency floors raised so even max realism keeps breaks
            # to no closer than every ~80–150 clicks.
            "break_bursts_enabled": r > 0.50,
            "break_min_clicks": max(80, int(250 - r * 150)),
            "break_max_clicks": max(160, int(400 - r * 200)),
            "break_min_duration": float(round(15 + r * 15)),
            "break_max_duration": float(round(40 + r * 30)),
            "overshoot_enabled": r > 0.05,
            "overshoot_probability": round(r * 0.35, 2),
            "anti_cluster_enabled": True,
            # Pulled way down (was 10 + r*20 → up to 30 px). The runtime
            # zone-aware clamp (clicker.py _anti_cluster) will cut it
            # further on small zones; this is the soft ceiling for
            # zones large enough not to need the clamp.
            "anti_cluster_radius": int(4 + r * 8),
            "hover_enabled": r > 0.20,
            "hover_frequency": round(r * 0.30, 2),
            "hover_dwell_min": round(1.0 + r * 9.0, 1),
            "hover_dwell_max": round(3.0 + r * 17.0, 1),
        }
        cfg.update(derived)
        self.realism_value_lbl.setText(f"{int(r * 100)}%")
        # Keep the main slider in sync if the call came from a stub.
        self.realism_slider.blockSignals(True)
        self.realism_slider.setValue(int(round(r * 100)))
        self.realism_slider.blockSignals(False)
        # Walk all registered RealismStub widgets (Click + Record pages).
        for stub in getattr(app, "_realism_stubs", []):
            try:
                stub.set_value(r)
            except Exception:
                pass
        self.refresh_advanced()
        save_config(cfg)
        app._push_config_to_clicker()

    def refresh_advanced(self) -> None:
        cfg = self.app.cfg
        for key, (slider, val_lbl, fmt, is_int) in self.app._adv_sliders.items():
            if key not in cfg:
                continue
            v = cfg[key]
            try:
                slider.set(v)
            except Exception:
                pass
        for key, var in self.app._adv_vars.items():
            if key in cfg:
                try:
                    var.blockSignals(True)
                    var.setChecked(bool(cfg[key]))
                    var.blockSignals(False)
                except Exception:
                    pass
        # Re-apply enable state for every sub-group so disabled sub-rows
        # follow the new master state.
        for g in self._groups:
            self._apply_master(g)


class RealismStub(QWidget):
    """Compact realism slider for non-Behavior pages.

    Surfaces the canonical humanization dial on the Click and Record
    pages so a brand-new user finds it without having to hunt through
    Behavior. Slider position stays synced across all instances via
    ``app._realism_stubs``; moving any one routes through the
    BehaviorPageBody's :meth:`apply_realism_preset` to re-derive every
    Advanced value the same way it always has.
    """

    def __init__(self, app, *, compact: bool = False):
        """``compact=True`` suppresses the internal "Realism" label so the
        stub can sit inside a ``Card("Realism")`` without the title
        repeating. Default keeps the legacy in-stub header for callers
        (Click page) that wrap the stub in a plain ``role=panel`` frame.
        """
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.SP_XS)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)
        if not compact:
            title = QLabel("Realism")
            title.setProperty("role", "body")
            title.setStyleSheet("font-weight: 600;")
            head.addWidget(title)
        head.addStretch(1)
        self.value_lbl = value_label(
            f"{int(app.cfg.get('realism', 0.5) * 100)}%"
        )
        head.addWidget(self.value_lbl)
        layout.addLayout(head)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(app.cfg.get("realism", 0.5) * 100)))
        self.slider.setToolTip(
            "Single dial driving every humanization behavior. "
            "Open Behavior → Advanced to override individual settings."
        )
        self.slider.valueChanged.connect(self._on_change)
        layout.addWidget(self.slider)

        if not hasattr(app, "_realism_stubs"):
            app._realism_stubs = []
        app._realism_stubs.append(self)

    def _on_change(self, value: int) -> None:
        r = max(0.0, min(1.0, value / 100.0))
        bc = getattr(self.app, "_behavior_card", None)
        if bc is not None:
            bc.apply_realism_preset(r)

    def set_value(self, r: float) -> None:
        v = int(round(r * 100))
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.value_lbl.setText(f"{int(r * 100)}%")


# Back-compat alias: ui/app.py still references BehaviorCard.
BehaviorCard = BehaviorPageBody
