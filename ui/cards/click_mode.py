"""Click mode editor cards, :class:`ClickZoneCard` (the area on screen) +
:class:`TimingCard` (interval, presets, button, pattern).

Built for the deck's editor pane, which is 480 to 700 px wide and sits
beside the live viewport: one column, every row reads label on the left
and control on the right, and the one primary action (DRAW ZONE) is the
widest thing on the card. Nothing here needs more than the pane's minimum
width, so the pane never clips.

The zone outline on screen is always the theme accent; the card only
offers whether it shows and how solid the fill is. The ON SCREEN switch
is the same toggle as the header's eye button (``App.set_overlay_visible``).
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider,
    QWidget,
)

from ui.config_io import save_config
from ui.tooltip_fmt import tooltip

from .. import icons, theme as t
from ..screen_utils import zone_screen_info
from ..widgets.card import Card
from ..widgets.field import value_label
from ..widgets.interval_display import IntervalDisplay
from ..widgets.ios_switch import IOSSwitch
from ..widgets.lock_control import ZoneLockControl
from ..widgets.preset_card import PresetCard
from ..widgets.range_spin_slider import RangeSpinSlider
from ..widgets.segmented import SegmentedControl
from ..widgets.state_pill import StatePill

# Left column of every label / control row, so the controls line up down
# the card.
_ROW_LABEL_W = 96


def row_label(text: str, tip: str = "") -> QLabel:
    """Uppercase tracked row label in TEXT_TERTIARY, fixed width."""
    lbl = QLabel(text.upper())
    lbl.setProperty("role", "section-label")
    font = lbl.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
    lbl.setFont(font)
    lbl.setFixedWidth(_ROW_LABEL_W)
    if tip:
        lbl.setToolTip(tip)
    return lbl


def control_row(label: str, *widgets: QWidget, stretch_last: bool = False,
                tip: str = "") -> QHBoxLayout:
    """``LABEL   [control] [control]`` on one line."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(t.SP_SM)
    row.addWidget(row_label(label, tip), 0, Qt.AlignVCenter)
    for i, w in enumerate(widgets):
        last = i == len(widgets) - 1
        row.addWidget(w, 1 if (stretch_last and last) else 0, Qt.AlignVCenter)
    if not stretch_last:
        row.addStretch(1)
    return row


def zone_summary(zone) -> str:
    """One line describing ``zone``: size, position and screen."""
    if zone is None:
        return "No zone yet. Draw one on screen; clicks land at random points inside it."
    label, _size, _origin = zone_screen_info(zone)
    screen = label.split(" · ")[0]
    if zone.shape == "rect":
        x1, y1, x2, y2 = zone.rect
        body = f"{x2 - x1} × {y2 - y1} px at ({x1}, {y1})"
    elif zone.shape == "circle":
        cx, cy, r = zone.circle
        body = f"circle, radius {r} px, centre ({cx}, {cy})"
    else:
        body = f"custom shape with {len(zone.vertices)} corners"
    return f"{body} on the {screen} screen"


class ClickZoneCard(Card):
    def __init__(self, app):
        super().__init__("Click zone")
        self.app = app

        self.pill = StatePill("Not set", tone="neutral")
        self.add_to_header(self.pill)

        body = self.body_layout()
        body.setSpacing(t.SP_SM)

        # 1) One line of facts about the zone (or what to do next). The
        # area itself is drawn on the real screen and shown in the live
        # viewport and the zone map, so there is no mini-map here.
        self.summary = QLabel("")
        self.summary.setProperty("role", "body")
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)

        # 2) The action row. DRAW is the one primary button on the card.
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(t.SP_SM)

        self.draw_btn = app.locker.register(QPushButton("Draw zone"))
        self.draw_btn.setIcon(icons.icon("redraw", 16, t.TEXT_ON_ACCENT))
        self.draw_btn.setProperty("variant", "primary")
        self.draw_btn.setMinimumHeight(t.BUTTON_H_HERO)
        self.draw_btn.setCursor(Qt.PointingHandCursor)
        self.draw_btn.setToolTip(tooltip(
            "Open a fullscreen overlay and drag the zone to click in. "
            "Esc cancels.",
            shortcut="Ctrl+D",
        ))
        self.draw_btn.clicked.connect(self._on_draw)
        actions.addWidget(self.draw_btn, 1)

        self.clear_btn = app.locker.register(QPushButton("Clear"))
        self.clear_btn.setProperty("variant", "ghost")
        self.clear_btn.setMinimumHeight(t.BUTTON_H_HERO)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setToolTip("Remove the current zone.")
        self.clear_btn.clicked.connect(self._on_clear)
        actions.addWidget(self.clear_btn)
        body.addLayout(actions)

        body.addSpacing(t.SP_XS)

        # 3) Settings rows: shape, lock, on-screen outline.
        self._shape = SegmentedControl(
            [("rect", "Rect"), ("circle", "Circle"), ("polygon", "Custom")],
            value=app._zone_shape,
            tooltips={
                "rect": "Next DRAW: drag a rectangle. Clicks land at random points inside it.",
                "circle": "Next DRAW: drag a circle from its centre. Clicks land inside the circle.",
                "polygon": "Next DRAW: click corner by corner to outline any shape, then close it.",
            },
        )
        self._shape.valueChanged.connect(self._on_shape)
        body.addLayout(control_row(
            "Shape", self._shape,
            tip="The shape the next DRAW ZONE uses. Changing it does not alter the current zone."))

        self.lock_ctl = ZoneLockControl()
        self.lock_ctl.modeChanged.connect(self._on_lock_mode)
        self.lock_ctl.windowChosen.connect(self._on_lock_window)
        app.locker.register(self.lock_ctl)
        body.addWidget(self.lock_ctl)

        self.overlay_switch = IOSSwitch()
        self.overlay_switch.setToolTip(
            "Show the zone as a blue outline on your real screen so you can "
            "see where clicks will land. Same as the eye button in the "
            "header and Ctrl+H. The outline never blocks clicks; the engine "
            "clicks straight through it."
        )
        self.overlay_switch.setChecked(bool(app.cfg.get("show_zone_overlay", True)))
        self.overlay_switch.toggled.connect(self._on_overlay_switch)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(int(app.cfg["zone_opacity"] * 100))
        self.opacity_slider.setToolTip(
            "How solid the fill inside the on-screen outline is. Low keeps "
            "the game readable through it; high makes the area obvious. "
            "The border stays at full strength either way.")
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.opacity_slider.setMinimumWidth(80)
        self.opacity_value = value_label(f"{int(app.cfg['zone_opacity'] * 100)}%")

        overlay_row = QHBoxLayout()
        overlay_row.setContentsMargins(0, 0, 0, 0)
        overlay_row.setSpacing(t.SP_SM)
        overlay_row.addWidget(row_label(
            "On screen",
            "Draw the click zone on your real screen as a blue outline. The "
            "switch shows or hides it; the slider sets how solid the fill is."))
        overlay_row.addWidget(self.overlay_switch, 0, Qt.AlignVCenter)
        overlay_row.addSpacing(t.SP_XS)
        overlay_row.addWidget(self.opacity_slider, 1, Qt.AlignVCenter)
        overlay_row.addWidget(self.opacity_value, 0, Qt.AlignVCenter)
        body.addLayout(overlay_row)

        self._refresh_preview()

    # -- State -------------------------------------------------------------

    def _refresh_preview(self) -> None:
        zone = self.app._zone
        self.lock_ctl.set_zone(zone)
        self.summary.setText(zone_summary(zone))
        self.draw_btn.setText("Redraw zone" if zone is not None else "Draw zone")
        self.clear_btn.setEnabled(zone is not None)
        self._refresh_pill()

    def _refresh_pill(self, override: Optional[Tuple[str, str]] = None) -> None:
        if override is not None:
            text, tone = override
            self.pill.set_state(text, tone)
            return
        if self.app._zone is None:
            self.pill.set_state("Not set", "neutral")
        else:
            self.pill.set_state("Ready", "accent")

    def sync_overlay_switch(self) -> None:
        """Mirror ``show_zone_overlay`` without re-emitting the toggle."""
        on = bool(self.app.cfg.get("show_zone_overlay", True))
        if self.overlay_switch.isChecked() != on:
            self.overlay_switch.blockSignals(True)
            self.overlay_switch.setChecked(on)
            self.overlay_switch.blockSignals(False)

    # -- Handlers ----------------------------------------------------------

    def _on_shape(self, value: str) -> None:
        self.app._zone_shape = value
        self.app.cfg["zone_shape"] = value
        save_config(self.app.cfg)

    def _on_lock_mode(self, mode: str) -> None:
        zone = self.app._zone
        if zone is None:
            return
        from modules.zone_lock import apply_lock_mode
        new_zone = apply_lock_mode(zone, mode)
        if mode == "window" and new_zone.lock is None:
            self.app.toasts.post(
                "No window under the zone centre, so it stays screen-locked.",
                kind="warn",
            )
        self.app._zone = new_zone
        self.app.cfg["zone"] = new_zone.to_json()
        save_config(self.app.cfg)
        self.app.zone_locks.forget("main")
        self._refresh_preview()
        self.app._push_config_to_clicker()
        self.app.overlay_manager.apply_visibility()

    def _on_lock_window(self, info) -> None:
        """The user picked another window from the LOCK list: move the
        zone onto it, keeping its place relative to the window."""
        zone = self.app._zone
        if zone is None or info is None:
            return
        from modules.zone_lock import retarget_lock
        new_zone = retarget_lock(zone, info)
        self.app._zone = new_zone
        self.app.cfg["zone"] = new_zone.to_json()
        save_config(self.app.cfg)
        self.app.zone_locks.forget("main")
        self._refresh_preview()
        self.app._push_config_to_clicker()
        self.app.overlay_manager.apply_visibility()
        self.app.toasts.post(f"Zone now follows {info.title or info.cls}.", kind="info")

    def _on_draw(self) -> None:
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return

        self._refresh_pill(("Drawing", "accent"))

        def _done(zone):
            if zone is None:
                # Cancelled: put the overlays back and settle the pill.
                self.app.overlay_manager.apply_visibility()
                self._refresh_pill()
                return
            self.app._zone = zone
            self.app.cfg["zone"] = zone.to_json()
            save_config(self.app.cfg)
            self._refresh_preview()
            self.app._push_config_to_clicker()
            self.app.overlay_manager.apply_visibility()

        self.app.open_zone_drawer(self.app._zone_shape, _done, attach_lock=True)

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

    def _on_overlay_switch(self, on: bool) -> None:
        self.app.set_overlay_visible(bool(on))

    def _on_opacity(self, value: int) -> None:
        cfg = self.app.cfg
        cfg["zone_opacity"] = value / 100.0
        self.opacity_value.setText(f"{value}%")
        # Overlay repaints live; the disk write waits for the drag to end.
        self.app.save_config_later()
        main = self.app.overlay_manager._main
        if self.app._zone is not None and main is not None:
            main.update_style(t.ZONE_DEFAULT_COLOR, cfg["zone_opacity"])


class TimingCard(Card):
    def __init__(self, app):
        # No card title: the page wraps this in a "Timing details" expander.
        super().__init__(None)
        self.app = app

        body = self.body_layout()
        body.setSpacing(t.SP_SM)

        hint = QLabel(
            "How long the engine waits between clicks, which mouse button "
            "fires and whether each fire is one click or a double click. "
            "The deck's MIN / MAX sliders move the same interval.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        body.addWidget(hint)

        # 1) Interval: big readout, log slider with typed min / max.
        self.interval_display = IntervalDisplay()
        self.interval_display.setToolTip(
            "Shortest and longest wait between two clicks. Each wait is a "
            "random draw from this range, weighted toward the low end.")
        self.interval_display.set_values(
            float(app.cfg["min_delay"]), float(app.cfg["max_delay"])
        )
        body.addWidget(self.interval_display)

        self.range_slider = RangeSpinSlider(
            from_=0.01, to=300.0,
            init_min=app.cfg["min_delay"], init_max=app.cfg["max_delay"],
        )
        self.range_slider.setToolTip(
            "Every wait between clicks is drawn from this range. Drag the "
            "ends or type exact values."
        )
        self.range_slider.valueChanged.connect(self._on_range_change)
        body.addWidget(self.range_slider)

        # 2) Presets, 2 x 2 so they fit the pane.
        self._preset_defs = [
            ("Bank", "50 – 150 ms", 0.05, 0.15),
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

        body.addSpacing(t.SP_XS)

        # 3) Button + pattern rows.
        self._button_seg = SegmentedControl(
            [("left", "Left"), ("right", "Right"), ("middle", "Middle")],
            value=app.cfg["click_type"],
            tooltips={
                "left": "Fire the left mouse button. The usual choice.",
                "right": "Fire the right mouse button, for context menus and RuneScape option menus.",
                "middle": "Fire the middle button (wheel click).",
            },
        )
        self._button_seg.valueChanged.connect(self._on_click_type)
        body.addLayout(control_row(
            "Button", self._button_seg,
            tip="Which mouse button each click uses. Also on the deck as L / R / M."))

        self._pattern_seg = SegmentedControl(
            [("single", "Single"), ("double", "Double")],
            value=app.cfg["click_mode"],
            tooltips={
                "single": "One click per fire.",
                "double": "Two clicks per fire, 40 to 120 ms apart, like a real double click.",
            },
        )
        self._pattern_seg.valueChanged.connect(self._on_click_mode)
        body.addLayout(control_row(
            "Pattern", self._pattern_seg,
            tip="Whether each fire is a single click or a double click."))

    # -- Behavior ----------------------------------------------------------

    def _on_range_change(self, lo: float, hi: float) -> None:
        cfg = self.app.cfg
        cfg["min_delay"] = float(lo)
        cfg["max_delay"] = float(hi)
        self.interval_display.set_values(float(lo), float(hi))
        self._sync_preset_checks()
        # Fires on every slider pixel; persist once the drag settles.
        self.app.save_config_later()

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

    def _refresh_entries(self) -> None:
        """Re-read the interval from config (palette commands write it
        directly) and refresh every readout that shows it."""
        cfg = self.app.cfg
        lo, hi = float(cfg["min_delay"]), float(cfg["max_delay"])
        self.range_slider.set_values(lo, hi)
        self.interval_display.set_values(lo, hi)
        self._sync_preset_checks()

    def _sync_preset_checks(self) -> None:
        """Mark the preset whose range matches the current cfg as checked;
        clear all others. Tolerance is loose so floating-point round-trip
        from JSON doesn't desync the visual."""
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
        # The control deck's L / R / M mirror the same setting.
        deck = getattr(self.app, "deck", None)
        sync = getattr(getattr(deck, "control_deck", None), "_sync_click_type", None)
        if callable(sync):
            try:
                sync()
            except Exception:
                pass

    def _on_click_mode(self, value: str) -> None:
        self.app.cfg["click_mode"] = value
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()
