"""Click mode cards — :class:`ClickZoneCard` (zone setup, visual preview) +
:class:`TimingCard` (interval, presets, button, pattern, realism).

The 2026 redesign flattens both cards: instead of a stack of ``Section``
wrappers, each card body reads top-to-bottom as a single rhythm — preview /
controls / actions in the zone card, interval / presets / button-and-pattern
/ nested realism panel in the timing card. Section wrappers are reserved for
heavier groupings on the Behavior page; here we lean on :class:`SectionLabel`
eyebrows and inline rows so the card hugs its content.
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ui.config_io import save_config
from ui.tooltip_fmt import tooltip

from .. import theme as t
from ..widgets.card import Card
from ..widgets.field import value_label
from ..widgets.interval_display import IntervalDisplay
from ..widgets.preset_card import PresetCard
from ..widgets.range_spin_slider import RangeSpinSlider
from ..widgets.section_label import SectionLabel
from ..widgets.segmented import SegmentedControl
from ..widgets.state_pill import StatePill
from ..widgets.zone_preview import ZonePreview


def _primary_monitor_info() -> Tuple[str, Tuple[int, int]]:
    """Return ("WxH · primary", (w, h)) for the OS-reported primary screen."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return ("", (0, 0))
    geom = screen.geometry()
    w, h = int(geom.width()), int(geom.height())
    return (f"{w} × {h} · primary", (w, h))


class ClickZoneCard(Card):
    def __init__(self, app):
        super().__init__("Click area")
        self.app = app

        # Header pill: tracks zone state. Update via _refresh_pill().
        self.pill = StatePill("Not set", tone="neutral")
        self.add_to_header(self.pill)

        body = self.body_layout()
        body.setSpacing(t.SP_SM)

        # 1) Visual zone preview ------------------------------------------
        self.preview = ZonePreview()
        body.addWidget(self.preview)

        # 2) Inline controls row: shape segmented (left), overlay swatch +
        #    opacity slider + value chip (right).
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(t.SP_MD)

        shape_lbl = QLabel("Shape")
        shape_lbl.setProperty("role", "body")
        controls_row.addWidget(shape_lbl)

        self._shape = SegmentedControl(
            [("rect", "Rect"), ("circle", "Circle"), ("polygon", "Custom")],
            value=app._zone_shape,
        )
        self._shape.valueChanged.connect(self._on_shape)
        controls_row.addWidget(self._shape)

        controls_row.addSpacing(t.SP_MD)

        self.color_btn = app.locker.register(QPushButton(""))
        self.color_btn.setFixedSize(22, 22)
        self.color_btn.setCursor(Qt.PointingHandCursor)
        self.color_btn.setToolTip("Pick the zone overlay color.")
        self._sync_color_btn(app.cfg["zone_color"])
        self.color_btn.clicked.connect(self._on_pick_color)
        controls_row.addWidget(self.color_btn)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(int(app.cfg["zone_opacity"] * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.opacity_slider.setMinimumWidth(80)
        controls_row.addWidget(self.opacity_slider, 1)

        self.opacity_value = value_label(f"{int(app.cfg['zone_opacity']*100)}%")
        controls_row.addWidget(self.opacity_value)

        body.addLayout(controls_row)

        # 3) Action row ---------------------------------------------------
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(t.SP_SM)

        self.draw_btn = app.locker.register(QPushButton("↻  Redraw zone"))
        self.draw_btn.setProperty("variant", "primary")
        self.draw_btn.setMinimumHeight(t.BUTTON_H_PRIMARY)
        self.draw_btn.setCursor(Qt.PointingHandCursor)
        self.draw_btn.setToolTip(tooltip(
            "Open a fullscreen overlay. Drag to define the zone. "
            "Esc cancels.",
            shortcut="Ctrl+D",
        ))
        self.draw_btn.clicked.connect(self._on_draw)
        action_row.addWidget(self.draw_btn, 1)

        self.clear_btn = app.locker.register(QPushButton("Clear"))
        self.clear_btn.setMinimumHeight(t.BUTTON_H)
        self.clear_btn.setMinimumWidth(80)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setToolTip("Remove the current zone.")
        self.clear_btn.clicked.connect(self._on_clear)
        action_row.addWidget(self.clear_btn)

        body.addLayout(action_row)

        self._refresh_preview()

    # -- Behavior ----------------------------------------------------------

    def _sync_color_btn(self, hex_color: str) -> None:
        self.color_btn.setStyleSheet(
            f"background: {hex_color}; "
            f"border: 1px solid {t.BORDER_STRONG}; "
            f"border-radius: 4px;"
        )

    def _refresh_preview(self) -> None:
        label, size = _primary_monitor_info()
        self.preview.set_zone(self.app._zone, label, size)
        self._refresh_pill()

    def _refresh_pill(self, override: Optional[Tuple[str, str]] = None) -> None:
        if override is not None:
            text, tone = override
            self.pill.set_state(text, tone)
            return
        if self.app._zone is None:
            self.pill.set_state("Not set", "neutral")
        else:
            self.pill.set_state("Configured", "accent")

    def _on_shape(self, value: str) -> None:
        self.app._zone_shape = value
        self.app.cfg["zone_shape"] = value
        save_config(self.app.cfg)

    def _on_draw(self) -> None:
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return

        self._refresh_pill(("Drawing…", "accent"))

        def _done(zone):
            if zone is None:
                # Cancelled — restore overlay if we had one, restore pill.
                if self.app._zone is not None and self.app.cfg.get("show_zone_overlay", True):
                    self.app.overlay_manager.show_main(
                        self.app._zone, self.app.cfg["zone_color"],
                        self.app.cfg["zone_opacity"],
                    )
                self.app.overlay_manager.refresh_step_overlays()
                self.app.overlay_manager.refresh_hover_overlays()
                self._refresh_pill()
                return
            self.app._zone = zone
            self.app.cfg["zone"] = zone.to_json()
            save_config(self.app.cfg)
            self._refresh_preview()
            self.app._push_config_to_clicker()
            if self.app.cfg.get("show_zone_overlay", True):
                self.app.overlay_manager.show_main(
                    zone, self.app.cfg["zone_color"], self.app.cfg["zone_opacity"],
                )
            self.app.overlay_manager.refresh_hover_overlays()
            self.app.overlay_manager.refresh_step_overlays()

        self.app.open_zone_drawer(self.app._zone_shape, _done)

    def _on_clear(self) -> None:
        if self.app._zone is None:
            return
        if QMessageBox.question(
            self, "Clear click zone",
            "Remove the current zone?",
        ) != QMessageBox.Yes:
            return
        self.app._zone = None
        self.app.cfg["zone"] = None
        save_config(self.app.cfg)
        self.app.overlay_manager.hide_main()
        self._refresh_preview()
        self.app._push_config_to_clicker()

    def _on_pick_color(self) -> None:
        cfg = self.app.cfg
        result = QColorDialog.getColor(QColor(cfg["zone_color"]), self,
                                       "Zone color")
        if result.isValid():
            hex_color = result.name()
            cfg["zone_color"] = hex_color
            self._sync_color_btn(hex_color)
            save_config(cfg)
            if self.app._zone is not None and self.app.overlay_manager._main:
                self.app.overlay_manager._main.update_style(
                    hex_color, cfg["zone_opacity"],
                )

    def _on_opacity(self, value: int) -> None:
        cfg = self.app.cfg
        cfg["zone_opacity"] = value / 100.0
        self.opacity_value.setText(f"{value}%")
        save_config(cfg)
        if self.app._zone is not None and self.app.overlay_manager._main:
            self.app.overlay_manager._main.update_style(
                cfg["zone_color"], cfg["zone_opacity"],
            )


class TimingCard(Card):
    def __init__(self, app):
        super().__init__("Timing")
        self.app = app

        body = self.body_layout()
        body.setSpacing(t.SP_SM)

        # 1) Interval ----------------------------------------------------
        body.addWidget(SectionLabel("Interval between clicks"))

        self.interval_display = IntervalDisplay()
        self.interval_display.set_values(
            float(app.cfg["min_delay"]), float(app.cfg["max_delay"])
        )
        body.addWidget(self.interval_display)

        # Log-scaled slider with companion spinboxes — same behavior as
        # the per-step delay slider on the Record tab. Sub-second values
        # occupy roughly half the drag distance instead of <1 %.
        self.range_slider = RangeSpinSlider(
            from_=0.01, to=300.0,
            init_min=app.cfg["min_delay"], init_max=app.cfg["max_delay"],
        )
        self.range_slider.valueChanged.connect(self._on_range_change)
        body.addWidget(self.range_slider)

        # 2) Quick presets (2x2 grid of PresetCards) ---------------------
        body.addWidget(SectionLabel("Quick presets"))

        self._preset_defs = [
            ("Bank-fast", "50 – 150 ms", 0.05, 0.15),
            ("Fast", "0.5 – 2 s", 0.5, 2.0),
            ("Medium", "3 – 10 s", 3.0, 10.0),
            ("Slow", "10 – 30 s", 10.0, 30.0),
        ]
        self._preset_cards: list[PresetCard] = []
        preset_grid = QGridLayout()
        preset_grid.setContentsMargins(0, 0, 0, 0)
        preset_grid.setHorizontalSpacing(t.SP_SM)
        preset_grid.setVerticalSpacing(t.SP_SM)
        for idx, (name, range_text, lo, hi) in enumerate(self._preset_defs):
            card = PresetCard(name, range_text, lo, hi)
            card.clicked.connect(
                lambda _checked=False, c=card: self._on_preset_click(c)
            )
            row, col = divmod(idx, 2)
            preset_grid.addWidget(card, row, col)
            self._preset_cards.append(card)
        body.addLayout(preset_grid)

        self._sync_preset_checks()

        # Typographic spacing break (not a section hairline rule).
        # Audit confirmed this is intentional rhythm whitespace separating
        # the preset grid from the inline button/pattern rows — do not
        # remove. Section hairlines were dropped from Section() in round 2;
        # this divider is a different beast.
        divider = QFrame()
        divider.setProperty("role", "divider")
        divider.setFixedHeight(1)
        body.addSpacing(t.SP_XS)
        body.addWidget(divider)
        body.addSpacing(t.SP_XS)

        # 3) Button + Pattern (inline rows) ------------------------------
        body.addLayout(self._segmented_row(
            "Button",
            SegmentedControl(
                [("left", "Left"), ("right", "Right")],
                value=app.cfg["click_type"],
            ),
            self._on_click_type,
            attr_name="_button_seg",
        ))
        body.addLayout(self._segmented_row(
            "Pattern",
            SegmentedControl(
                [("single", "Single"), ("double", "Double")],
                value=app.cfg["click_mode"],
            ),
            self._on_click_mode,
            attr_name="_pattern_seg",
        ))

        # 4) Nested Realism panel ----------------------------------------
        from .behavior import RealismStub
        panel = QFrame()
        panel.setProperty("role", "panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(t.SP_MD, t.SP_SM, t.SP_MD, t.SP_SM)
        panel_layout.setSpacing(t.SP_XS)
        panel_layout.addWidget(RealismStub(app))
        body.addSpacing(t.SP_XS)
        body.addWidget(panel)

    def _segmented_row(self, label_text, seg, handler, attr_name):
        seg.valueChanged.connect(handler)
        setattr(self, attr_name, seg)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(t.SP_MD)
        lbl = QLabel(label_text)
        lbl.setProperty("role", "body")
        row.addWidget(lbl)
        row.addStretch(1)
        row.addWidget(seg)
        return row

    # -- Behavior ----------------------------------------------------------

    def _on_range_change(self, lo: float, hi: float) -> None:
        cfg = self.app.cfg
        cfg["min_delay"] = float(lo)
        cfg["max_delay"] = float(hi)
        self.interval_display.set_values(float(lo), float(hi))
        self._sync_preset_checks()
        save_config(cfg)
        self.app._push_config_to_clicker()

    def _on_preset_click(self, card: PresetCard) -> None:
        self._apply_preset(card.lo_seconds, card.hi_seconds)

    def _apply_preset(self, lo: float, hi: float) -> None:
        cfg = self.app.cfg
        cfg["min_delay"] = lo
        cfg["max_delay"] = hi
        self.range_slider.set_values(lo, hi)
        self.interval_display.set_values(lo, hi)
        self._sync_preset_checks()
        save_config(cfg)
        self.app._push_config_to_clicker()

    def _sync_preset_checks(self) -> None:
        """Mark the preset card whose range matches the current cfg as
        checked; clear all others. Tolerance is loose so floating-point
        round-trip from JSON doesn't desync the visual."""
        cfg = self.app.cfg
        lo = float(cfg["min_delay"])
        hi = float(cfg["max_delay"])
        eps = 1e-3
        for card in self._preset_cards:
            match = (
                abs(card.lo_seconds - lo) < eps
                and abs(card.hi_seconds - hi) < eps
            )
            if card.isChecked() != match:
                card.setChecked(match)

    def _on_click_type(self, value: str) -> None:
        self.app.cfg["click_type"] = value
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()

    def _on_click_mode(self, value: str) -> None:
        self.app.cfg["click_mode"] = value
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()
