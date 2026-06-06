"""``HoverPageBody`` — settings-style body for the Hover page.

Composed entirely from the design-system primitives — :class:`GroupHeader`,
:class:`SettingsGroup`, :class:`SettingsRow`, :class:`IOSSwitch`,
:class:`EmptyState`, :class:`ZoneThumbnail`, :class:`QuietAccentButton`,
:class:`BorderlessButton`. No :class:`Card` chrome, no inline
``setStyleSheet`` calls.

Two groups:

* **Zones** — list of hover zones with per-row thumbnails. Header carries
  a shape menu trigger and a quiet-accent ``+ Add zone`` button. Empty
  state shows a centered placeholder + CTA.
* **Visits** — Enable / Frequency / Dwell time / Selection rows. The
  bottom three disable when Enable is off.

The dwell ``RangeSlider`` is still cross-coupled to the global Realism
dial via :class:`_DwellRegistryAdapter`. ``refresh_advanced`` is called
by :class:`~ui.cards.behavior.BehaviorCard` after a Realism push so the
slider + readout stay in sync with the canonical preset.
"""

from __future__ import annotations

from typing import Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from ui.config_io import save_config

from .. import theme as t
from ..widgets.empty_state import EmptyState
from ..widgets.group_header import GroupHeader
from ..widgets.interval_display import IntervalDisplay
from ..widgets.ios_switch import IOSSwitch
from ..widgets.labeled_slider import LabeledSlider
from ..widgets.quiet_button import BorderlessButton, QuietAccentButton
from ..widgets.range_slider import RangeSlider
from ..widgets.segmented import SegmentedControl
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow
from ..widgets.zone_thumbnail import ZoneThumbnail


_SHAPE_LABELS = {"rect": "Rect", "circle": "Circle", "polygon": "Custom"}


def _primary_monitor_size() -> Tuple[int, int]:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return (0, 0)
    geom = screen.geometry()
    return (int(geom.width()), int(geom.height()))


def _zone_kind_label(zone) -> str:
    if zone.shape == "rect":
        return "Rectangle"
    if zone.shape == "circle":
        return "Circle"
    return "Polygon"


def _zone_meta(zone) -> str:
    if zone.shape == "rect":
        x1, y1, x2, y2 = zone.rect
        return f"{x2-x1} × {y2-y1} at ({x1}, {y1})"
    if zone.shape == "circle":
        cx, cy, r = zone.circle
        return f"r={r} at ({cx}, {cy})"
    n = len(zone.vertices)
    x1, y1, x2, y2 = zone.aabb()
    return f"{n} corners · {x2-x1} × {y2-y1}"


class _DwellRegistryAdapter:
    """Shim so the dwell :class:`RangeSlider` can fit the
    :class:`LabeledSlider`-shaped ``_adv_sliders`` registry.

    Each adapter handles one cfg key; the pair keeps the RangeSlider in
    sync with both endpoints whenever Realism pushes a new value, and
    forwards the change to the body's :class:`IntervalDisplay`."""

    def __init__(self, body: "HoverPageBody", key: str, partner_key: str):
        self._body = body
        self._app = body.app
        self._key = key
        self._partner = partner_key

    def set(self, value: float) -> None:
        cfg = self._app.cfg
        if self._key.endswith("_min"):
            lo, hi = float(value), float(cfg.get(self._partner, value))
        else:
            lo, hi = float(cfg.get(self._partner, value)), float(value)
        self._body._dwell.set_values(lo, hi)
        self._body._dwell_display.set_values(lo, hi)


class HoverPageBody(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Zones group ──────────────────────────────────────────────
        zones_header = GroupHeader("Zones")

        self._shape_btn = BorderlessButton(
            f"{_SHAPE_LABELS.get(app._hover_shape, 'Rect')}  ▾"
        )
        self._shape_btn.setMenu(self._build_shape_menu())
        zones_header.add_action(self._shape_btn)

        self._add_btn = app.locker.register(QuietAccentButton("+  Add zone"))
        self._add_btn.setToolTip("Drag a region the cursor will drift to.")
        self._add_btn.clicked.connect(self._on_add)
        zones_header.add_action(self._add_btn)

        outer.addWidget(zones_header)

        self._zones_group = SettingsGroup()
        outer.addWidget(self._zones_group)

        outer.addSpacing(t.SP_XL)

        # ── Visits group ────────────────────────────────────────────
        visits_header = GroupHeader("Visits")
        outer.addWidget(visits_header)

        self._visits_group = SettingsGroup()

        # Enable
        self._enable_switch = IOSSwitch()
        self._enable_switch.setChecked(bool(app.cfg.get("hover_enabled", True)))
        self._enable_switch.toggled.connect(self._on_enable_changed)
        app._adv_vars["hover_enabled"] = self._enable_switch
        self._enable_row = SettingsRow(
            "Enable hover visits",
            desc="Master switch for hover-zone drifts.",
        )
        self._enable_row.set_control(self._enable_switch)
        self._visits_group.add_row(self._enable_row)

        # Frequency — reuses LabeledSlider so the Realism dial registry
        # picks it up; stripped of its own label since SettingsRow owns
        # the title.
        self._freq_slider = LabeledSlider(
            app, "", "hover_frequency",
            from_=0.0, to=1.0, steps=100, value_fmt="{:.2f}",
        )
        self._freq_slider.label.hide()
        self._freq_slider.value_lbl.setMinimumWidth(40)
        self._freq_slider.setMinimumWidth(220)
        self._freq_row = SettingsRow(
            "Frequency",
            desc="Chance of a hover drift between clicks.",
        )
        self._freq_row.set_control(self._freq_slider)
        self._visits_group.add_row(self._freq_row)

        # Dwell — IntervalDisplay readout + RangeSlider stacked
        self._dwell_display = IntervalDisplay()
        self._dwell_display.set_values(
            float(app.cfg.get("hover_dwell_min", 1.0)),
            float(app.cfg.get("hover_dwell_max", 4.0)),
        )
        self._dwell = RangeSlider(
            from_=0.2, to=30.0, steps=298,
            init_min=app.cfg.get("hover_dwell_min", 1.0),
            init_max=app.cfg.get("hover_dwell_max", 4.0),
        )
        self._dwell.valueChanged.connect(self._on_dwell_change)
        self._dwell.setMinimumWidth(220)

        dwell_control = QWidget()
        dwell_col = QVBoxLayout(dwell_control)
        dwell_col.setContentsMargins(0, 0, 0, 0)
        dwell_col.setSpacing(2)
        dwell_col.addWidget(self._dwell_display, 0, Qt.AlignRight)
        dwell_col.addWidget(self._dwell)

        self._dwell_row = SettingsRow(
            "Dwell time",
            desc="How long the cursor lingers on each zone.",
        )
        self._dwell_row.set_control(dwell_control)
        self._visits_group.add_row(self._dwell_row)

        # Register dwell adapters with the Realism preset registry.
        app._adv_sliders["hover_dwell_min"] = (
            _DwellRegistryAdapter(self, "hover_dwell_min", "hover_dwell_max"),
            None, "{:.1f}", False,
        )
        app._adv_sliders["hover_dwell_max"] = (
            _DwellRegistryAdapter(self, "hover_dwell_max", "hover_dwell_min"),
            None, "{:.1f}", False,
        )

        # Selection
        self._sel_seg = SegmentedControl(
            [("random", "Random"), ("order", "In order")],
            value=app.cfg.get("hover_selection", "random"),
        )
        self._sel_seg.valueChanged.connect(self._on_selection)
        self._sel_row = SettingsRow(
            "Selection",
            desc="Pick zones randomly or cycle in order.",
        )
        self._sel_row.set_control(self._sel_seg)
        self._visits_group.add_row(self._sel_row)

        outer.addWidget(self._visits_group)

        outer.addSpacing(t.SP_MD)

        # ── Footer hint ─────────────────────────────────────────────
        footer = QLabel(
            'Tip: pair with <a href="behavior:idle_wander">Idle wander</a> '
            'in Behavior for short curved drifts on top of zone visits.'
        )
        footer.setProperty("role", "footer-hint")
        footer.setOpenExternalLinks(False)
        footer.setTextFormat(Qt.RichText)
        footer.setWordWrap(True)
        footer.linkActivated.connect(self._on_footer_link)
        outer.addWidget(footer)

        self._refresh_zones()
        self._refresh_visits_enabled_state()

    # -- Shape menu --------------------------------------------------------

    def _build_shape_menu(self) -> QMenu:
        menu = QMenu(self)
        for opt_id, label in (
            ("rect", "Rect"),
            ("circle", "Circle"),
            ("polygon", "Custom"),
        ):
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, oid=opt_id: self._on_shape_chosen(oid)
            )
        return menu

    def _on_shape_chosen(self, value: str) -> None:
        self.app._hover_shape = value
        self.app.cfg["hover_zone_shape"] = value
        save_config(self.app.cfg)
        self._shape_btn.setText(f"{_SHAPE_LABELS.get(value, 'Rect')}  ▾")

    # -- Zones list rendering ---------------------------------------------

    def _refresh_zones(self) -> None:
        self._zones_group.clear()
        zones = self.app._hover_zones
        if not zones:
            self._zones_group.add_widget(EmptyState(
                title="No hover zones yet",
                description=(
                    "Add a region for the cursor to drift to between clicks."
                ),
                cta_text="+  Add zone",
                on_cta=self._on_add,
            ))
            return
        click_zone = self.app._zone
        mw, mh = _primary_monitor_size()
        for idx, zone in enumerate(zones):
            self._zones_group.add_row(self._build_zone_row(idx, zone, click_zone, mw, mh))
        # Re-apply locker state in case we built buttons under an active engine.
        self.app.locker.apply(self.app._state_str)

    def _build_zone_row(self, idx: int, zone, click_zone, mw: int, mh: int) -> SettingsRow:
        thumb = ZoneThumbnail()
        thumb.set_monitor(mw, mh)
        thumb.set_zone(zone)
        if click_zone is not None:
            thumb.set_click_reference(click_zone)

        row = SettingsRow(
            _zone_kind_label(zone),
            desc=_zone_meta(zone),
            leading=thumb,
        )

        rm = self.app.locker.register(QPushButton("✕"))
        rm.setProperty("variant", "icon-danger")
        rm.setMaximumSize(28, 24)
        rm.setMinimumSize(28, 24)
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(lambda _, i=idx: self._on_remove(i))
        row.set_control(rm)
        return row

    # -- Visits row enable/disable ----------------------------------------

    def _refresh_visits_enabled_state(self) -> None:
        on = bool(self.app.cfg.get("hover_enabled", True))
        for row in (self._freq_row, self._dwell_row, self._sel_row):
            row.set_row_enabled(on)

    # -- Handlers ---------------------------------------------------------

    def _on_enable_changed(self, checked: bool) -> None:
        cfg = self.app.cfg
        cfg["hover_enabled"] = bool(checked)
        save_config(cfg)
        self._refresh_visits_enabled_state()
        self.app._push_config_to_clicker()

    def _on_dwell_change(self, lo: float, hi: float) -> None:
        cfg = self.app.cfg
        cfg["hover_dwell_min"] = float(lo)
        cfg["hover_dwell_max"] = float(hi)
        self._dwell_display.set_values(float(lo), float(hi))
        save_config(cfg)
        self.app._push_config_to_clicker()

    def _on_selection(self, value: str) -> None:
        self.app.cfg["hover_selection"] = value
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()

    def _on_add(self) -> None:
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return

        def _done(zone):
            if zone is None:
                self.app.overlay_manager.refresh_hover_overlays()
                self.app.overlay_manager.refresh_step_overlays()
                return
            self.app._hover_zones.append(zone)
            self._save_zones()
            self._refresh_zones()
            self.app._push_config_to_clicker()
            self.app.overlay_manager.refresh_hover_overlays()
            self.app.overlay_manager.refresh_step_overlays()

        self.app.open_zone_drawer(self.app._hover_shape, _done)

    def _on_remove(self, idx: int) -> None:
        if not (0 <= idx < len(self.app._hover_zones)):
            return
        if QMessageBox.question(
            self, "Remove hover zone",
            f"Remove this hover zone?",
        ) != QMessageBox.Yes:
            return
        del self.app._hover_zones[idx]
        self._save_zones()
        self._refresh_zones()
        self.app._push_config_to_clicker()
        self.app.overlay_manager.refresh_hover_overlays()

    def _on_footer_link(self, href: str) -> None:
        if href.startswith("behavior:"):
            self.app.nav_rail.set_current("behavior")

    def _save_zones(self) -> None:
        self.app.cfg["hover_zones"] = [z.to_json() for z in self.app._hover_zones]
        save_config(self.app.cfg)

    # -- Public hooks ------------------------------------------------------

    # Behavior card calls this after Realism pushes new values.
    def refresh_advanced(self) -> None:
        cfg = self.app.cfg
        lo = float(cfg.get("hover_dwell_min", 1.0))
        hi = float(cfg.get("hover_dwell_max", 4.0))
        self._dwell.set_values(lo, hi)
        self._dwell_display.set_values(lo, hi)

    # Command palette + external callers expect this method on the card.
    # Kept under the prior name so ``commands.py`` keeps working.
    def render_all(self) -> None:
        self._refresh_zones()


# Back-compat alias so ``app.py`` can still import HoverZonesCard if it
# stops getting updated in lock-step with renames.
HoverZonesCard = HoverPageBody
